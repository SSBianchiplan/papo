"""Ferramentas que o agente usa para ler arquivos e dados.

Todas são de LEITURA (política AUTO). Nenhuma ferramenta altera dado do usuário,
então não há proposta a aprovar — se um dia houver ferramenta de escrita, ela entra
como CONFIRM com gate humano (P4), nunca aqui.
"""
from __future__ import annotations

import hashlib
import math
import re
import unicodedata
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from ..costs import TZ
from ..db import row, rows

Log = Callable[[str, str], Awaitable[None]]


# ---------------------------------------------------------------- utilidades
def norm(s: Any) -> str:
    t = unicodedata.normalize("NFD", str(s if s is not None else ""))
    return "".join(c for c in t if unicodedata.category(c) != "Mn").lower()


_BR_THOUSANDS = re.compile(r"^-?\d{1,3}(\.\d{3})+(,\d+)?$")
_BR_DECIMAL = re.compile(r"^-?\d+,\d+$")
_US_THOUSANDS = re.compile(r"^-?\d{1,3}(,\d{3})+(\.\d+)?$")
_PLAIN = re.compile(r"^-?\d+(\.\d+)?([eE]-?\d+)?$")


def to_num(v: Any) -> float:
    """Número em formato brasileiro ou internacional; NaN se não for número."""
    if isinstance(v, bool):
        return math.nan
    if isinstance(v, int | float):
        return float(v)
    s = re.sub(r"R\$|\s|%", "", str(v if v is not None else "").strip())
    if not s:
        return math.nan
    if _BR_THOUSANDS.match(s) or _BR_DECIMAL.match(s):
        s = s.replace(".", "").replace(",", ".")
    elif _US_THOUSANDS.match(s):
        s = s.replace(",", "")
    return float(s) if _PLAIN.match(s) else math.nan


def rnd(x: float | None) -> float | None:
    if x is None or (isinstance(x, float) and (math.isnan(x) or math.isinf(x))):
        return None
    return round(x, 4)


def snippet(text: str, terms: list[str], width: int = 650) -> str:
    t = norm(text)
    at = next((i for w in terms if (i := t.find(w)) >= 0), -1)
    s = max(0, at - 220)
    return ("…" if s else "") + text[s:s + width].strip() + ("…" if s + width < len(text) else "")


# ---------------------------------------------------------------- catálogo
@dataclass
class SheetInfo:
    ord: int
    name: str
    columns: list[str]
    stored: int
    total: int


@dataclass
class DocInfo:
    id: UUID
    name: str
    kind: str
    pages: int | None
    note: str | None
    parts: int
    sheets: list[SheetInfo] = field(default_factory=list)

    def label(self) -> str:
        if self.kind == "pdf":
            return f"{self.pages or self.parts} páginas"
        if self.sheets:
            return "; ".join(f"aba {s.name}: {s.stored} linhas, colunas {', '.join(s.columns[:25])}" for s in self.sheets)
        return f"{self.parts} seções"


async def load_docs(conn: AsyncConnection, conversation_id: UUID, agent_ids: list[UUID]) -> list[DocInfo]:
    docs = await rows(conn, """
        SELECT d.id, d.filename, d.kind, d.pages, d.note,
               (SELECT count(*) FROM doc_chunk c WHERE c.document_id = d.id) AS parts
          FROM document d
         WHERE d.status = 'ready'
           AND NOT EXISTS (SELECT 1 FROM document_purge p WHERE p.document_id = d.id)
           AND (d.conversation_id = :c OR d.agent_id = ANY(:a))
         ORDER BY d.created_at""", c=conversation_id, a=agent_ids)
    out = [DocInfo(id=d["id"], name=d["filename"], kind=d["kind"], pages=d["pages"], note=d["note"], parts=int(d["parts"])) for d in docs]
    if out:
        sheets = await rows(conn, """SELECT document_id, ord, name, columns, stored_rows, total_rows
                                       FROM doc_sheet WHERE document_id = ANY(:ids) ORDER BY document_id, ord""",
                            ids=[d.id for d in out])
        by = {d.id: d for d in out}
        for s in sheets:
            by[s["document_id"]].sheets.append(SheetInfo(s["ord"], s["name"], list(s["columns"]), s["stored_rows"], s["total_rows"]))
    return out


def find_doc(docs: list[DocInfo], name: str) -> DocInfo | None:
    n = norm(name).strip()
    if not n:
        return None
    for d in docs:
        if norm(d.name) == n:
            return d
    stem = re.sub(r"\.[a-z0-9]+$", "", n)
    for d in docs:
        dn = norm(d.name)
        if n in dn or (stem and stem in dn) or re.sub(r"\.[a-z0-9]+$", "", dn) in n:
            return d
    return None


def find_col(columns: list[str], name: str) -> int:
    n = norm(name).strip()
    for i, c in enumerate(columns):
        if norm(c) == n:
            return i
    for i, c in enumerate(columns):
        if n and n in norm(c):
            return i
    return -1


# ---------------------------------------------------------------- motor de planilha (puro)
class Filtro(BaseModel):
    coluna: str
    op: Literal["=", "!=", ">", ">=", "<", "<=", "contem"] = "="
    valor: str | float | int | None = None


class ToolFail(Exception):
    def __init__(self, error: str, hint: str | None = None) -> None:
        super().__init__(error)
        self.error = error
        self.hint = hint


def apply_filters(columns: list[str], data: list[list[Any]], filtros: list[Filtro]) -> list[list[Any]]:
    out = data
    for f in filtros:
        ci = find_col(columns, f.coluna)
        if ci < 0:
            raise ToolFail(f'Coluna "{f.coluna}" não existe.', "Colunas: " + ", ".join(columns))
        nv = to_num(f.valor)

        def ok(r: list[Any], ci: int = ci, f: Filtro = f, nv: float = nv) -> bool:
            cell = r[ci] if ci < len(r) else ""
            nc = to_num(cell)
            both = not math.isnan(nv) and not math.isnan(nc)
            if f.op == "=":
                return nc == nv if both else norm(cell).strip() == norm(f.valor).strip()
            if f.op == "!=":
                return nc != nv if both else norm(cell).strip() != norm(f.valor).strip()
            if f.op == "contem":
                return norm(f.valor) in norm(cell)
            if not both:
                return False
            return {">": nc > nv, ">=": nc >= nv, "<": nc < nv, "<=": nc <= nv}[f.op]

        out = [r for r in out if ok(r)]
    return out


def describe(columns: list[str], data: list[list[Any]], total: int) -> dict[str, Any]:
    cols = []
    for i, c in enumerate(columns):
        vals = [r[i] for r in data if i < len(r) and r[i] not in ("", None)]
        nums = [x for x in (to_num(v) for v in vals) if not math.isnan(x)]
        info: dict[str, Any] = {"coluna": c, "preenchidos": len(vals)}
        if nums and len(nums) >= 0.8 * len(vals):
            s = sum(nums)
            info.update(tipo="numérico", min=rnd(min(nums)), max=rnd(max(nums)), soma=rnd(s), media=rnd(s / len(nums)))
        else:
            distinct = {str(v) for v in vals}
            info.update(tipo="texto", valores_distintos=len(distinct))
            if len(distinct) <= 12:
                info["valores"] = sorted(distinct)
        cols.append(info)
    return {"linhas": len(data), "linhas_no_arquivo": total, "colunas": cols,
            "amostra": [dict(zip(columns, r, strict=False)) for r in data[:5]]}


def filtrar(columns: list[str], data: list[list[Any]], ordenar_por: str | None, ordem: str, colunas: list[str], limite: int) -> dict[str, Any]:
    out = list(data)
    if ordenar_por:
        ci = find_col(columns, ordenar_por)
        if ci < 0:
            raise ToolFail(f'Coluna de ordenação "{ordenar_por}" não existe.', "Colunas: " + ", ".join(columns))
        nums = all(not math.isnan(to_num(r[ci])) for r in out if r[ci] not in ("", None))

        def key(r: list[Any]) -> Any:
            if not nums:
                return norm(r[ci])
            v = to_num(r[ci])
            return math.inf if math.isnan(v) else v

        out.sort(key=key, reverse=(ordem != "asc"))
    idx = [i for i in (find_col(columns, c) for c in colunas) if i >= 0] if colunas else list(range(len(columns)))
    return {"total_encontrado": len(out), "mostrando": min(limite, len(out)),
            "linhas": [{columns[i]: r[i] for i in idx} for r in out[:limite]]}


def agrupar(columns: list[str], data: list[list[Any]], por: list[str], coluna: str | None, funcao: str, ordem: str, limite: int) -> dict[str, Any]:
    gi = []
    for c in por:
        i = find_col(columns, c)
        if i < 0:
            raise ToolFail(f'Coluna "{c}" não existe.', "Colunas: " + ", ".join(columns))
        gi.append(i)
    mi = find_col(columns, coluna) if coluna else -1
    if funcao != "contagem" and mi < 0:
        raise ToolFail("Informe metrica.coluna com uma coluna numérica.", "Colunas: " + ", ".join(columns))
    groups: dict[str, list[float]] = {}
    counts: dict[str, int] = {}
    for r in data:
        k = " | ".join(str(r[i]) for i in gi) or "(total)"
        counts[k] = counts.get(k, 0) + 1
        bucket = groups.setdefault(k, [])
        if mi >= 0:
            v = to_num(r[mi])
            if not math.isnan(v):
                bucket.append(v)

    def val(k: str) -> float | None:
        b = groups[k]
        if funcao == "contagem":
            return float(counts[k])
        if not b:
            return None
        return {"soma": sum(b), "media": sum(b) / len(b), "min": min(b), "max": max(b)}[funcao]

    vals: list[tuple[str, float | None]] = [(k, rnd(val(k))) for k in groups]
    sign = 1 if ordem == "asc" else -1
    vals.sort(key=lambda kv: (kv[1] is None, sign * (kv[1] or 0.0)))    # vazios sempre por último
    res = [{"grupo": k, "valor": v, "linhas": counts[k]} for k, v in vals]
    total = sum(v or 0.0 for _, v in vals) if funcao in ("soma", "contagem") else None
    return {"agrupado_por": [columns[i] for i in gi], "funcao": funcao, "coluna": columns[mi] if mi >= 0 else None,
            "linhas_consideradas": len(data), "grupos": len(res), "total_geral": rnd(total) if total is not None else None,
            "resultado": res[:limite]}


# ---------------------------------------------------------------- esquemas das ferramentas
class ListarDocumentos(BaseModel):
    """Lista os documentos e planilhas disponíveis nesta conversa: nome, tipo, páginas ou seções, abas, colunas e linhas. Use primeiro para saber o que existe."""


class BuscarNosDocumentos(BaseModel):
    """Busca palavras-chave em todos os documentos (ou em um), sem depender de acento. Retorna os trechos mais relevantes com documento e página/seção; em planilhas, retorna linhas que contêm os termos."""
    consulta: str = Field(min_length=1, max_length=300, description="palavras-chave")
    documento: str | None = Field(default=None, description="opcional: nome do documento")


class LerDocumento(BaseModel):
    """Lê o texto integral de um documento por intervalo de páginas (PDF) ou seções (Word/texto). Numeração começa em 1; no máximo 8 partes por chamada."""
    documento: str
    de: int = Field(default=1, ge=1)
    ate: int | None = Field(default=None, ge=1)


class Metrica(BaseModel):
    coluna: str | None = None
    funcao: Literal["soma", "media", "contagem", "min", "max"] = "contagem"


class AnalisarPlanilha(BaseModel):
    """Consulta dados de planilha (xlsx, csv). operacao: 'descrever' (colunas, tipos, estatísticas, amostra), 'filtrar' (linhas que atendem os filtros, com ordenação) ou 'agrupar' (agrega a métrica por colunas). Use os nomes de coluna de listar_documentos. Faça as contas aqui em vez de estimar."""
    documento: str
    aba: str | None = None
    operacao: Literal["descrever", "filtrar", "agrupar"]
    filtros: list[Filtro] = Field(default_factory=list)
    agrupar_por: list[str] = Field(default_factory=list)
    metrica: Metrica = Field(default_factory=Metrica)
    ordenar_por: str | None = None
    ordem: Literal["asc", "desc"] = "desc"
    colunas: list[str] = Field(default_factory=list)
    limite: int = Field(default=30, ge=1, le=200)


Hex6 = Field(default=None, pattern=r"^#[0-9A-Fa-f]{6}$")


class Tema(BaseModel):
    primaria: str | None = Hex6
    escura: str | None = Hex6
    fundo: str | None = Hex6
    texto: str | None = Hex6


class GerarArquivo(BaseModel):
    """Cria um arquivo e o entrega na conversa como anexo que o usuário pode abrir e baixar. Use quando o usuário pedir relatório, página, documento, resumo para guardar, HTML ou Markdown. formato 'html': página pronta no design system do Papo (tabelas, citações e código já estilizados); 'md': Markdown puro. Escreva o conteúdo em Markdown (títulos ##, listas, tabelas |, citações >); não escreva HTML. Se houver um design system ou manual de marca nos arquivos da conversa (por exemplo um .md com cores e fonte), leia-o antes e passe as cores em tema e a fonte em fonte. Na resposta de texto, diga em uma ou duas frases o que o arquivo traz; não repita o conteúdo."""
    formato: Literal["html", "md"]
    nome: str = Field(min_length=1, max_length=80, description="nome do arquivo, sem extensão")
    titulo: str = Field(min_length=1, max_length=160)
    conteudo: str = Field(min_length=1, max_length=200_000, description="corpo em Markdown")
    tema: Tema | None = Field(default=None, description="opcional, só para html: cores do design system do contexto")
    fonte: str | None = Field(default=None, pattern=r"^[A-Za-z0-9 -]{2,40}$", description="opcional, só para html: nome da família de fonte")


class BuscarNaConversa(BaseModel):
    """Procura no histórico desta conversa (mensagens antigas que não estão mais à vista), sem depender de acento. Use quando o usuário se referir a algo dito antes ("aquele valor", "o que combinamos") e o trecho não estiver nas mensagens recentes."""
    consulta: str = Field(min_length=1, max_length=200)
    limite: int = Field(default=8, ge=1, le=20)


class UsarSkill(BaseModel):
    """Carrega as instruções completas de uma skill ativa nesta conversa (as skills disponíveis estão listadas nas instruções, com nome e descrição). Chame antes de executar uma tarefa que combine com a descrição de uma skill e siga o que ela mandar. Para um arquivo de referência citado pela skill, informe arquivo com o caminho exato."""
    nome: str = Field(min_length=1, max_length=80)
    arquivo: str | None = Field(default=None, max_length=200)


class HubBuscar(BaseModel):
    """Procura arquivos nos Docs do hub (sistemas do GPlanSiS ligados a este agente) pelo nome e pela pasta, sem depender de acento. Retorna fonte, caminho, tipo, tamanho e data. Use antes de hub_ler para achar o caminho exato."""
    consulta: str = Field(min_length=1, max_length=200, description="palavras do nome ou da pasta")
    tipo: str | None = Field(default=None, max_length=12, description="opcional: pdf, md, docx, xlsx…")
    limite: int = Field(default=20, ge=1, le=50)


class HubLer(BaseModel):
    """Lê um arquivo dos Docs do hub direto na origem (nada é copiado). operacao 'ler' devolve o texto por partes (páginas, slides ou seções; até 8 por chamada). Para planilha use 'descrever', 'filtrar' ou 'agrupar', como em analisar_planilha. Cite fonte e caminho na resposta."""
    fonte: str = Field(min_length=1, max_length=80)
    caminho: str = Field(min_length=1, max_length=1024)
    operacao: Literal["ler", "descrever", "filtrar", "agrupar"] = "ler"
    de: int = Field(default=1, ge=1)
    ate: int | None = Field(default=None, ge=1)
    aba: str | None = None
    filtros: list[Filtro] = Field(default_factory=list)
    agrupar_por: list[str] = Field(default_factory=list)
    metrica: Metrica = Field(default_factory=Metrica)
    ordenar_por: str | None = None
    ordem: Literal["asc", "desc"] = "desc"
    colunas: list[str] = Field(default_factory=list)
    limite: int = Field(default=30, ge=1, le=200)


TOOL_MODELS: dict[str, type[BaseModel]] = {
    "listar_documentos": ListarDocumentos,
    "buscar_nos_documentos": BuscarNosDocumentos,
    "ler_documento": LerDocumento,
    "analisar_planilha": AnalisarPlanilha,
    "gerar_arquivo": GerarArquivo,
    "buscar_na_conversa": BuscarNaConversa,
    "usar_skill": UsarSkill,
    "hub_buscar": HubBuscar,
    "hub_ler": HubLer,
}
DOC_TOOLS = ("listar_documentos", "buscar_nos_documentos", "ler_documento", "analisar_planilha")


def tool_specs(with_docs: bool = True, with_skills: bool = False, with_hub: bool = False) -> list[dict[str, Any]]:
    specs = []
    for name, m in TOOL_MODELS.items():
        if (name in DOC_TOOLS and not with_docs) or (name == "usar_skill" and not with_skills) or (name.startswith("hub_") and not with_hub):
            continue
        schema = m.model_json_schema()
        schema.pop("title", None)
        schema.pop("description", None)
        specs.append({"name": name, "description": (m.__doc__ or "").strip(), "input_schema": schema})
    return specs


# ---------------------------------------------------------------- execução
MAX_RESULT_CHARS = 24_000


@dataclass
class Output:
    """Onde a execução entrega arquivos e busca histórico (dono, conversa, execução, autor)."""
    owner: UUID
    conversation_id: UUID
    run_id: UUID
    agent_name: str
    files: list[UUID] = field(default_factory=list)
    skills: dict[str, UUID] = field(default_factory=dict)       # nome → id das skills ativas nesta execução
    hub: list[tuple[UUID, str, str]] = field(default_factory=list)   # (fonte, rótulo, pasta) que o agente pode ler no hub


MAX_FILES_PER_RUN = 5


class Toolbox:
    def __init__(self, conn: AsyncConnection, docs: list[DocInfo], log: Log, out: Output | None = None) -> None:
        self.conn = conn
        self.docs = docs
        self.log = log
        self.out = out

    def _doc(self, name: str) -> DocInfo:
        d = find_doc(self.docs, name)
        if d is None:
            raise ToolFail(f'Documento "{name}" não encontrado.', "Use listar_documentos para ver os nomes exatos.")
        return d

    async def run(self, name: str, raw: dict[str, Any]) -> dict[str, Any]:
        model = TOOL_MODELS.get(name)
        if model is None:
            return {"ok": False, "error": f"ferramenta desconhecida: {name}"}
        try:
            args = model.model_validate(raw)
            data = await getattr(self, name)(args)
            return {"ok": True, "data": data}
        except ValidationError as e:
            return {"ok": False, "error": "argumentos inválidos", "hint": e.errors(include_url=False, include_input=False).__repr__()[:800]}
        except ToolFail as e:
            await self.log("⚠️", e.error)          # falha também aparece no balão: transparência sobre o que não deu certo
            return {"ok": False, "error": e.error, "hint": e.hint}

    async def listar_documentos(self, _: ListarDocumentos) -> Any:
        await self.log("🗂️", "Conferiu os documentos disponíveis")
        return [{"nome": d.name, "tipo": d.kind, **({"paginas": d.pages} if d.pages else {}),
                 **({"partes": d.parts} if d.parts else {}),
                 **({"abas": [{"aba": s.name, "colunas": s.columns, "linhas": s.stored, "linhas_no_arquivo": s.total} for s in d.sheets]} if d.sheets else {}),
                 **({"observacao": d.note} if d.note else {})} for d in self.docs]

    async def buscar_nos_documentos(self, a: BuscarNosDocumentos) -> Any:
        terms = [w for w in re.split(r"[^a-z0-9]+", norm(a.consulta)) if len(w) > 2][:12]
        if not terms:
            raise ToolFail("Consulta sem termos úteis.", "Use palavras com 3 letras ou mais.")
        pool = [self._doc(a.documento)] if a.documento else self.docs
        ids = [d.id for d in pool]
        names = {d.id: d.name for d in pool}
        hits: list[dict[str, Any]] = []
        chunks = await rows(self.conn, """
            SELECT c.document_id, c.label, c.body, ts_rank(c.tsv, q) AS rank
              FROM doc_chunk c, to_tsquery('portuguese', :q) q
             WHERE c.document_id = ANY(:ids) AND c.tsv @@ q
             ORDER BY rank DESC LIMIT 8""", q=" | ".join(terms), ids=ids)
        if not chunks:     # radical não bateu (siglas, códigos): busca literal
            chunks = await rows(self.conn, """
                SELECT c.document_id, c.label, c.body, 0.0 AS rank FROM doc_chunk c
                 WHERE c.document_id = ANY(:ids) AND lower(f_unaccent(c.body)) LIKE ANY(:p)
                 ORDER BY c.document_id, c.ord LIMIT 8""", ids=ids, p=[f"%{t}%" for t in terms])
        for c in chunks:
            hits.append({"documento": names[c["document_id"]], "local": c["label"], "trecho": snippet(c["body"], terms)})
        trows = await rows(self.conn, """
            SELECT r.document_id, s.name AS aba, s.columns, r.cells
              FROM doc_row r JOIN doc_sheet s ON s.document_id = r.document_id AND s.ord = r.sheet_ord
             WHERE r.document_id = ANY(:ids) AND lower(f_unaccent(r.cells::text)) LIKE ANY(:p)
             LIMIT 10""", ids=ids, p=[f"%{t}%" for t in terms])
        for r in trows:
            hits.append({"documento": names[r["document_id"]], "local": f"aba {r['aba']}", "linha": dict(zip(r["columns"], r["cells"], strict=False))})
        q = a.consulta[:50]
        await self.log("🔎", f"Buscou “{q}”{' em ' + a.documento if a.documento else ''} · "
                             + (f"{len(hits)} {'resultado' if len(hits) == 1 else 'resultados'}" if hits else "nada encontrado"))
        return hits or "Nenhum trecho encontrado. Tente sinônimos ou leia o documento."

    async def ler_documento(self, a: LerDocumento) -> Any:
        d = self._doc(a.documento)
        if d.parts == 0:
            raise ToolFail("Documento sem texto." if not d.sheets else "É planilha: use analisar_planilha.", d.note)
        de = min(a.de, d.parts)
        ate = min(d.parts, max(de, a.ate or de + 3), de + 7)
        parts = await rows(self.conn, """SELECT label, body FROM doc_chunk WHERE document_id = :d AND ord BETWEEN :a AND :b
                                         ORDER BY ord""", d=d.id, a=de, b=ate)
        out, size = [], 0
        for p in parts:
            t = p["body"][: MAX_RESULT_CHARS - size]
            out.append({"local": p["label"], "texto": t})
            size += len(t)
            if size >= MAX_RESULT_CHARS:
                break
        unit = "páginas" if d.kind == "pdf" else "seções"
        await self.log("📄", f"Leu {d.name}, {unit} {de}{'–' + str(ate) if ate > de else ''}")
        return {"documento": d.name, "total_partes": d.parts, "partes": out}

    async def analisar_planilha(self, a: AnalisarPlanilha) -> Any:
        d = self._doc(a.documento)
        if not d.sheets:
            raise ToolFail(f'"{d.name}" não é planilha.', "Use ler_documento.")
        sheet = d.sheets[0]
        if a.aba:
            found = next((s for s in d.sheets if norm(s.name) == norm(a.aba)), None) or \
                next((s for s in d.sheets if norm(a.aba) in norm(s.name)), None)
            if found is None:
                raise ToolFail(f'Aba "{a.aba}" não existe.', "Abas: " + ", ".join(s.name for s in d.sheets))
            sheet = found
        raw = await rows(self.conn, "SELECT cells FROM doc_row WHERE document_id = :d AND sheet_ord = :s ORDER BY ord",
                         d=d.id, s=sheet.ord)
        data = apply_filters(sheet.columns, [list(r["cells"]) for r in raw], a.filtros)
        where = f"{d.name}{' (' + sheet.name + ')' if len(d.sheets) > 1 else ''}"
        if a.operacao == "descrever":
            await self.log("📊", f"Examinou a estrutura de {where}")
            return {"aba": sheet.name, **describe(sheet.columns, data, sheet.total)}
        if a.operacao == "filtrar":
            await self.log("📊", f"Filtrou {where}: {len(data)} {'linha' if len(data) == 1 else 'linhas'}")
            return filtrar(sheet.columns, data, a.ordenar_por, a.ordem, a.colunas, a.limite)
        res = agrupar(sheet.columns, data, a.agrupar_por, a.metrica.coluna, a.metrica.funcao, a.ordem, a.limite)
        by = f" por {', '.join(res['agrupado_por'])}" if res["agrupado_por"] else ""
        await self.log("📊", f"Calculou {a.metrica.funcao}{' de ' + res['coluna'] if res['coluna'] else ''}{by} em {where}")
        return res


    async def gerar_arquivo(self, a: GerarArquivo) -> Any:
        from .. import storage
        from ..extract.parsers import _chunk
        from .files import render_html, render_md, safe_filename

        if self.out is None:
            raise ToolFail("Gerar arquivo não está disponível aqui.")
        if len(self.out.files) >= MAX_FILES_PER_RUN:
            raise ToolFail(f"Limite de {MAX_FILES_PER_RUN} arquivos por resposta.", "Junte o conteúdo num arquivo só.")
        if a.formato == "html":
            data = render_html(titulo=a.titulo, conteudo=a.conteudo, agent_name=self.out.agent_name,
                               tema=a.tema.model_dump() if a.tema else None, fonte=a.fonte).encode()
            name, mime = safe_filename(a.nome, "html"), "text/html"
        else:
            data = render_md(titulo=a.titulo, conteudo=a.conteudo, agent_name=self.out.agent_name).encode()
            name, mime = safe_filename(a.nome, "md"), "text/markdown"
        key = storage.new_key(self.out.owner, "doc", name.rsplit(".", 1)[-1])
        await storage.put(key, data, f"{mime}; charset=utf-8")
        d = await row(self.conn, """INSERT INTO document (owner_id, conversation_id, filename, mime, size_bytes, sha256, storage_key, kind, origin, run_id)
                                    VALUES (:o, :c, :f, :m, :s, :h, :k, 'text', 'agent', :r) RETURNING id""",
                      o=self.out.owner, c=self.out.conversation_id, f=name, m=mime, s=len(data), h=hashlib.sha256(data).hexdigest(),
                      k=key, r=self.out.run_id)
        assert d is not None
        # o índice guarda o texto (Markdown), não o HTML: o arquivo vira contexto pesquisável na hora
        parts = _chunk(f"{a.titulo}\n\n{a.conteudo}")
        for i, (lab, body) in enumerate(parts, start=1):
            await self.conn.execute(text("INSERT INTO doc_chunk (document_id, ord, label, body) VALUES (:d, :o, :l, :b)"),
                                    {"d": d["id"], "o": i, "l": lab[:60], "b": body[:40000]})
        await self.conn.execute(text("""UPDATE document SET status = 'ready', note = :n, processed_at = now() WHERE id = :d"""),
                                {"n": f"Gerado por {self.out.agent_name}"[:500], "d": d["id"]})
        self.out.files.append(d["id"])
        await self.log("📝", f"Gerou {name}")
        return {"arquivo": name, "tamanho_bytes": len(data), "entregue": True}

    async def buscar_na_conversa(self, a: BuscarNaConversa) -> Any:
        if self.out is None:
            raise ToolFail("Busca no histórico indisponível aqui.")
        terms = [w for w in re.split(r"[^a-z0-9]+", norm(a.consulta)) if len(w) > 2][:8]
        if not terms:
            raise ToolFail("Consulta sem termos úteis.", "Use palavras com 3 letras ou mais.")
        found = await rows(self.conn, """
            SELECT seq, author, coalesce(agent_name, '') AS agent_name, body, created_at FROM message
             WHERE conversation_id = :c AND author <> 'system' AND body <> ''
               AND (SELECT bool_and(f_unaccent(lower(body)) LIKE '%' || t || '%') FROM unnest(CAST(:t AS text[])) t)
             ORDER BY seq DESC LIMIT :n""", c=self.out.conversation_id, t=terms, n=a.limite)
        await self.log("🔎", f"Procurou no histórico: {a.consulta[:60]}")
        if not found:
            return {"mensagens": [], "observacao": "Nada encontrado no histórico com esses termos."}
        return {"mensagens": [{"n": f["seq"], "quando": f["created_at"].astimezone(TZ).strftime("%d/%m/%Y %H:%M"),
                               "autor": "usuário" if f["author"] == "user" else f["agent_name"], "texto": f["body"][:1500]}
                              for f in reversed(found)]}


    async def usar_skill(self, a: UsarSkill) -> Any:
        if self.out is None or not self.out.skills:
            raise ToolFail("Nenhuma skill ativa nesta conversa.")
        key = norm(a.nome).strip()
        sid = next((i for n, i in self.out.skills.items() if norm(n) == key), None) \
            or next((i for n, i in self.out.skills.items() if key and (key in norm(n) or norm(n).endswith(":" + key))), None)
        if sid is None:
            raise ToolFail(f'Skill "{a.nome}" não está ativa.', "Ativas: " + ", ".join(self.out.skills))
        sk = await row(self.conn, "SELECT name, body FROM skill WHERE id = :i AND enabled", i=sid)
        if not sk:
            raise ToolFail(f'Skill "{a.nome}" foi desativada.')
        paths = [r["path"] for r in await rows(self.conn, "SELECT path FROM skill_file WHERE skill_id = :i ORDER BY path", i=sid)]
        if a.arquivo:
            f = await row(self.conn, "SELECT body FROM skill_file WHERE skill_id = :i AND path = :p", i=sid, p=a.arquivo.strip().lstrip("./"))
            if not f:
                raise ToolFail(f'A skill {sk["name"]} não tem o arquivo "{a.arquivo}".', "Arquivos: " + (", ".join(paths) or "nenhum"))
            await self.log("📘", f"Consultou {a.arquivo} da skill {sk['name']}")
            body = str(f["body"])
            return {"skill": sk["name"], "arquivo": a.arquivo, "conteudo": body[:60_000], **({"cortado": True} if len(body) > 60_000 else {})}
        await self.log("📘", f"Usou a skill {sk['name']}")
        body = str(sk["body"])
        return {"skill": sk["name"], "instrucoes": body[:60_000], "arquivos_de_referencia": paths,
                **({"cortado": True} if len(body) > 60_000 else {})}


    def _hub_scope(self) -> tuple[str, dict[str, Any]]:
        """Cláusula SQL que limita o catálogo às fontes/pastas ligadas ao agente."""
        if self.out is None or not self.out.hub:
            raise ToolFail("Nenhuma fonte do hub ligada a este agente.")
        conds: list[str] = []
        params: dict[str, Any] = {}
        for i, (sid, _, prefix) in enumerate(self.out.hub):
            params[f"s{i}"], params[f"p{i}"] = sid, (prefix.rstrip("/") + "/") if prefix else ""
            conds.append(f"(f.source_id = :s{i} AND f.path LIKE :p{i} || '%')")
        return "(" + " OR ".join(conds) + ")", params

    async def hub_buscar(self, a: HubBuscar) -> Any:
        scope, params = self._hub_scope()
        terms = [w for w in re.split(r"[^a-z0-9]+", norm(a.consulta)) if len(w) > 1][:6]
        cond = "".join(f" AND f_unaccent(lower(f.path)) LIKE '%' || :t{i} || '%'" for i in range(len(terms)))
        p = params | {f"t{i}": t for i, t in enumerate(terms)} | {"n": a.limite, "x": (a.tipo or "").lower().lstrip(".")}
        found = await rows(self.conn, f"""SELECT s.label AS fonte, f.path, f.ext, f.size_bytes, f.mtime FROM hub_file f
                                           JOIN hub_source s ON s.id = f.source_id AND s.enabled
                                          WHERE {scope}{cond} AND (:x = '' OR f.ext = :x) ORDER BY f.mtime DESC LIMIT :n""", **p)
        await self.log("🗄️", f"Procurou no hub: {a.consulta[:60]}")
        return {"arquivos": [{"fonte": f["fonte"], "caminho": f["path"], "tipo": f["ext"], "kb": round(f["size_bytes"] / 1024, 1),
                              "alterado": f["mtime"].astimezone(TZ).strftime("%d/%m/%Y")} for f in found],
                **({} if found else {"observacao": "Nada encontrado com esses termos nas fontes deste agente."})}

    async def hub_ler(self, a: HubLer) -> Any:
        import asyncio

        from ..extract.parsers import parse
        from ..hub import client

        scope, params = self._hub_scope()
        f = await row(self.conn, f"""SELECT f.source_id, s.label, f.path FROM hub_file f JOIN hub_source s ON s.id = f.source_id AND s.enabled
                                      WHERE {scope} AND f.path = :path AND (lower(s.label) = lower(:fonte) OR lower(s.name) = lower(:fonte)
                                            OR NOT EXISTS (SELECT 1 FROM hub_source x WHERE lower(x.label) = lower(:fonte) OR lower(x.name) = lower(:fonte)))
                                      LIMIT 1""", **params, path=a.caminho.strip().lstrip("/"), fonte=a.fonte)
        if not f:
            raise ToolFail(f'"{a.caminho}" não está nas fontes do hub deste agente.', "Use hub_buscar para achar o caminho exato.")
        data = await client.read(f["source_id"], f["path"])
        ex = await asyncio.to_thread(parse, data, f["path"].rsplit("/", 1)[-1], "")
        where = f'{f["label"]}: {f["path"]}'
        if a.operacao != "ler":
            if not ex.sheets:
                raise ToolFail(f"{where} não é planilha.", "Use operacao 'ler'.")
            sheet = ex.sheets[0]
            if a.aba:
                sheet = next((s for s in ex.sheets if norm(s.name) == norm(a.aba)), sheet)
            data_rows = apply_filters(sheet.columns, sheet.rows, a.filtros)
            await self.log("📊", f"Analisou {where}")
            if a.operacao == "descrever":
                return {"fonte": where, "aba": sheet.name, **describe(sheet.columns, data_rows, sheet.total)}
            if a.operacao == "filtrar":
                return {"fonte": where, "aba": sheet.name, **filtrar(sheet.columns, data_rows, a.ordenar_por, a.ordem, a.colunas, a.limite)}
            return {"fonte": where, "aba": sheet.name, **agrupar(sheet.columns, data_rows, a.agrupar_por, a.metrica.coluna, a.metrica.funcao, a.ordem, a.limite)}
        if not ex.parts and ex.sheets:
            sh = ex.sheets[0]
            await self.log("📊", f"Leu {where}")
            return {"fonte": where, "abas": [s.name for s in ex.sheets], "colunas": sh.columns, "linhas": sh.total,
                    "amostra": [dict(zip(sh.columns, r, strict=False)) for r in sh.rows[:15]],
                    "dica": "Para números use operacao 'agrupar' ou 'filtrar'."}
        total = len(ex.parts)
        if not total:
            raise ToolFail(f"{where}: {ex.note or 'sem texto legível'}")
        de = min(a.de, total)
        ate = min(a.ate or de + 2, de + 7, total)
        await self.log("📄", f"Leu {where} ({ex.parts[de - 1][0]}{'–' + ex.parts[ate - 1][0] if ate > de else ''})")
        return {"fonte": where, "total_partes": total, "partes": [{"parte": i, "rotulo": lab, "texto": txt}
                                                                  for i, (lab, txt) in enumerate(ex.parts[de - 1:ate], start=de)],
                **({"observacao": ex.note} if ex.note else {})}


async def docs_as_text(conn: AsyncConnection, docs: list[DocInfo], cap: int = 150_000) -> str:
    """Modo direto: conteúdo integral (limitado) vai no prompt."""
    out, left = [], cap
    for d in docs:
        if left <= 0:
            break
        if d.parts:
            ps = await rows(conn, "SELECT label, body FROM doc_chunk WHERE document_id = :d ORDER BY ord", d=d.id)
            body = "\n\n".join(f"[{p['label']}]\n{p['body']}" for p in ps)
        else:
            blocks = []
            for s in d.sheets:
                rs = await rows(conn, "SELECT cells FROM doc_row WHERE document_id = :d AND sheet_ord = :s ORDER BY ord LIMIT 400",
                                d=d.id, s=s.ord)
                blocks.append(f"[aba {s.name}]\n" + ";".join(s.columns) + "\n" + "\n".join(";".join(map(str, r["cells"])) for r in rs))
            body = "\n\n".join(blocks)
        body = body[:left]
        left -= len(body)
        out.append(f'<documento nome="{d.name}">\n{body}\n</documento>')
    return "\n\n".join(out)
