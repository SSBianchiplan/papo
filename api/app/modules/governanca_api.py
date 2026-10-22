"""Governança de IA e Consultor de IA: modelo de camadas, fichas dos agentes, opções por conversa, eventos, rubricas e avaliações.

Ficha é plano de controle: o dono do agente edita até M1 e liga/desliga; promoção para M2 ou M3 é decisão de administrador,
registrada (decidido_por). O banco recusa combinações proibidas pela matriz camada × moderação e ativação sem ficha completa (I4).
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field
from sqlalchemy import text

from .. import governanca
from ..auth import Admin, CurrentUser, User
from ..consultor import engine as consultor
from ..db import row, rows, scalar, tx
from ..errors import DomainError, Invalid, NotFound

router = APIRouter(prefix="/api/governanca", tags=["governança de IA"])


class Forbidden(DomainError):
    status = 403
    code = "proibido"


# ----------------------------------------------------------------- modelo de camadas (referência)
@router.get("/modelo")
async def modelo(user: CurrentUser = User) -> dict[str, Any]:
    return {"versao": governanca.MODELO_VERSAO, "camadas": governanca.CAMADAS, "matriz": governanca.MATRIZ, "niveis": governanca.NIVEIS,
            "gatilhos": governanca.GATILHOS, "transversais": governanca.TRANSVERSAIS}


# ----------------------------------------------------------------- fichas
class Ferramenta(BaseModel):
    nome: str = Field(pattern=r"^[a-z_]{3,40}$")
    tipo: Literal["leitura", "escrita", "escrita_propria"]


class FichaIn(BaseModel):
    dono: str = Field(default="", max_length=120)
    camada_real: int | None = Field(default=None, ge=1, le=6)
    nivel: Literal["M0", "M1", "M2", "M3"] = "M1"
    fontes: list[str] = Field(default_factory=list, max_length=30)
    ferramentas: list[Ferramenta] = Field(default_factory=list, max_length=30)
    raio_acao: str = Field(default="", max_length=500)
    max_iteracoes: int | None = Field(default=None, ge=1, le=16)
    max_custo_conversa_usd: float | None = Field(default=None, gt=0, le=1000)
    max_segundos_turno: int | None = Field(default=None, ge=10, le=600)
    aprovacao_humana: list[str] = Field(default_factory=list, max_length=20)
    gatilhos: list[Literal["T1", "T2", "T3", "T4", "T5", "T6", "T7", "T8"]] = Field(default_factory=list)
    canais: list[Literal["direto", "grupo", "mencao"]] = Field(default_factory=lambda: ["direto"])  # type: ignore[arg-type]
    retencao_dias: int = Field(default=90, ge=1, le=3650)
    camadas_no_contexto: bool = False
    uso_interno_evidencia: bool = False
    excecao_m3: str | None = Field(default=None, max_length=1000)
    ativo: bool = False


class FichaOut(FichaIn):
    agent_id: UUID
    agent_name: str
    kind: str
    versao: int
    completa: bool
    faltando: list[str]
    decidido_por: UUID | None
    atualizado_em: datetime
    permissao_matriz: str


FIELDS = list(FichaIn.model_fields)


def _faltando(r: dict[str, Any]) -> list[str]:
    f = []
    if not (r["dono"] or "").strip():
        f.append("dono")
    if r["camada_real"] is None:
        f.append("camada real")
    if not r["ferramentas"]:
        f.append("ferramentas")
    if not r["canais"]:
        f.append("canais")
    if r["max_iteracoes"] is None or r["max_custo_conversa_usd"] is None or r["max_segundos_turno"] is None:
        f.append("condições de parada")
    if not (r["raio_acao"] or "").strip():
        f.append("raio de ação")
    return f


def _out(r: dict[str, Any]) -> FichaOut:
    falta = _faltando(r)
    perm = governanca.MATRIZ.get(r["camada_real"] or 0, {}).get(r["nivel"], "—")
    data = {k: r[k] for k in FIELDS if k in r}
    data["ferramentas"] = list(r["ferramentas"] or [])
    data["max_custo_conversa_usd"] = float(r["max_custo_conversa_usd"]) if r["max_custo_conversa_usd"] is not None else None
    return FichaOut(**data, agent_id=r["agent_id"], agent_name=r["agent_name"], kind=r["kind"], versao=r["versao"], completa=not falta,
                    faltando=falta, decidido_por=r["decidido_por"], atualizado_em=r["atualizado_em"], permissao_matriz=perm)


FICHA_SQL = "SELECT f.*, a.name AS agent_name, a.kind FROM agent_ficha f JOIN agent a ON a.id = f.agent_id"


@router.get("/fichas", response_model=list[FichaOut])
async def fichas(user: CurrentUser = User) -> list[FichaOut]:
    async with tx(user.id) as conn:
        return [_out(r) for r in await rows(conn, FICHA_SQL + " ORDER BY a.kind DESC, lower(a.name)")]


@router.put("/fichas/{agent_id}", response_model=FichaOut)
async def put_ficha(agent_id: UUID, body: FichaIn, user: CurrentUser = User) -> FichaOut:
    async with tx(user.id) as conn:
        cur = await row(conn, FICHA_SQL + " WHERE f.agent_id = :a", a=agent_id)
        if not cur:
            raise NotFound("Agente não encontrado.")
        if body.nivel in ("M2", "M3") and body.nivel != cur["nivel"] and not user.is_admin:
            raise Forbidden("Promover para M2 ou M3 é decisão de administrador, registrada.", hint="Peça a um administrador do Papo.")
        if body.nivel == "M3" and body.camada_real == 6 and not (body.excecao_m3 or "").strip():
            raise Invalid("M3 na camada agêntica exige exceção aprovada, rollback provado e kill-switch (descreva na exceção).")
        if body.nivel == "M2" and body.camada_real == 5 and not body.uso_interno_evidencia:
            raise Invalid("M2 na camada generativa só para uso interno com evidência acumulada.")
        if body.nivel == "M3" and body.camada_real not in (1, 6):
            raise Invalid(f"M3 é proibido na camada {body.camada_real} pela matriz do Modelo de Camadas.")
        if body.ativo:
            falta = _faltando({**body.model_dump(), "ferramentas": [f.model_dump() for f in body.ferramentas]})
            if falta:
                raise Invalid("Ficha incompleta: não dá para ativar (I4).", hint="Falta: " + ", ".join(falta))
        p = body.model_dump()
        p["ferramentas"] = json.dumps([f.model_dump() for f in body.ferramentas], ensure_ascii=False)
        sets = ", ".join(f"{k} = :{k}" if k != "ferramentas" else "ferramentas = CAST(:ferramentas AS jsonb)" for k in FIELDS)
        await conn.execute(text(f"UPDATE agent_ficha SET {sets}, decidido_por = :u WHERE agent_id = :a"), {**p, "u": user.id, "a": agent_id})
        r = await row(conn, FICHA_SQL + " WHERE f.agent_id = :a", a=agent_id)
    assert r
    return _out(r)


@router.patch("/fichas/{agent_id}/ativo", response_model=FichaOut)
async def set_ativo(agent_id: UUID, ativo: bool, user: CurrentUser = User) -> FichaOut:
    async with tx(user.id) as conn:
        cur = await row(conn, FICHA_SQL + " WHERE f.agent_id = :a", a=agent_id)
        if not cur:
            raise NotFound("Agente não encontrado.")
        if ativo and (falta := _faltando(cur)):
            raise Invalid("Ficha incompleta: não dá para ativar (I4).", hint="Falta: " + ", ".join(falta))
        await conn.execute(text("UPDATE agent_ficha SET ativo = :v, decidido_por = :u WHERE agent_id = :a"), {"v": ativo, "u": user.id, "a": agent_id})
        r = await row(conn, FICHA_SQL + " WHERE f.agent_id = :a", a=agent_id)
    assert r
    return _out(r)


@router.get("/fichas/{agent_id}/historico")
async def historico(agent_id: UUID, user: CurrentUser = User) -> list[dict[str, Any]]:
    async with tx(user.id) as conn:
        return await rows(conn, """SELECT h.versao, h.em, h.ficha->>'nivel' AS nivel, (h.ficha->>'ativo')::boolean AS ativo,
                                          h.ficha->>'camada_real' AS camada, coalesce(u.display_name, u.email, 'sistema') AS por
                                     FROM agent_ficha_historico h LEFT JOIN app_user u ON u.id = h.decidido_por
                                    WHERE h.agent_id = :a ORDER BY h.versao DESC LIMIT 30""", a=agent_id)


# ----------------------------------------------------------------- por conversa
class FeatureIn(BaseModel):
    camadas: bool = False
    consultor: bool = False


@router.get("/conversas")
async def conversas(user: CurrentUser = User) -> list[dict[str, Any]]:
    async with tx(user.id) as conn:
        return await rows(conn, """SELECT c.id, c.kind, coalesce(c.name, a.name) AS titulo, coalesce(f.camadas, false) AS camadas,
                                          coalesce(f.consultor, false) AS consultor, a.kind AS agent_kind
                                     FROM conversation c LEFT JOIN agent a ON a.id = c.agent_id
                                     LEFT JOIN conversation_feature f ON f.conversation_id = c.id
                                    ORDER BY c.last_activity_at DESC LIMIT 200""")


@router.put("/conversas/{cid}")
async def put_conversa(cid: UUID, body: FeatureIn, user: CurrentUser = User) -> dict[str, Any]:
    async with tx(user.id) as conn:
        c = await row(conn, "SELECT id, kind FROM conversation WHERE id = :c", c=cid)
        if not c:
            raise NotFound("Conversa não encontrada.")
        await conn.execute(text("""INSERT INTO conversation_feature (conversation_id, owner_id, camadas, consultor) VALUES (:c, :o, :ca, :co)
                                   ON CONFLICT (conversation_id) DO UPDATE SET camadas = EXCLUDED.camadas, consultor = EXCLUDED.consultor"""),
                           {"c": cid, "o": user.id, "ca": body.camadas, "co": body.consultor})
        if body.consultor and c["kind"] == "group":       # consultor entra no grupo (responde só quando mencionado)
            cons = await scalar(conn, "SELECT id FROM agent WHERE kind = 'consultor'")
            if not cons:
                raise Invalid("Ative o Consultor de IA primeiro.")
            await conn.execute(text("""INSERT INTO conversation_member (owner_id, conversation_id, agent_id) VALUES (:o, :c, :a)
                                       ON CONFLICT DO NOTHING"""), {"o": user.id, "c": cid, "a": cons})
    return {"id": str(cid), **body.model_dump()}


@router.get("/eventos")
async def eventos(limit: int = Query(default=50, ge=1, le=200), user: CurrentUser = User) -> list[dict[str, Any]]:
    async with tx(user.id) as conn:
        return await rows(conn, """SELECT e.em, e.codigo, e.detalhe, e.nivel_antes, e.nivel_depois, a.name AS agente,
                                          coalesce(c.name, ca.name) AS conversa
                                     FROM governanca_evento e LEFT JOIN agent a ON a.id = e.agent_id
                                     LEFT JOIN conversation c ON c.id = e.conversation_id LEFT JOIN agent ca ON ca.id = c.agent_id
                                    ORDER BY e.em DESC LIMIT :n""", n=limit)


# ----------------------------------------------------------------- consultor: contato, avaliações, respostas
@router.post("/consultor/ativar")
async def ativar_consultor(user: CurrentUser = User) -> dict[str, Any]:
    async with tx(user.id) as conn:
        a = await scalar(conn, "SELECT id FROM agent WHERE kind = 'consultor'")
        if not a:
            a = await scalar(conn, """INSERT INTO agent (owner_id, name, emoji, color, persona, kind)
                                      VALUES (:o, 'Consultor de IA', '🧭', '#12343B', :p, 'consultor') RETURNING id""",
                             o=user.id, p="Avalia propostas de IA: classifica nas seis camadas, entrevista sobre as lacunas e emite parecer com nota "
                                          "determinística. A IA propõe, o humano decide.")
        conv = await scalar(conn, "SELECT id FROM conversation WHERE kind = 'dm' AND agent_id = :a", a=a)
        if not conv:
            conv = await scalar(conn, "INSERT INTO conversation (owner_id, kind, agent_id) VALUES (:o, 'dm', :a) RETURNING id", o=user.id, a=a)
            await conn.execute(text("""INSERT INTO message (conversation_id, author, body) VALUES (:c, 'system', :b)"""),
                               {"c": conv, "b": "Envie a proposta de IA em PDF ou Word. O Consultor classifica a camada real, pergunta só o que "
                                                 "faltar no documento e entrega um parecer com nota, condições e PDF. A IA propõe, o humano decide."})
        await conn.execute(text("UPDATE agent_ficha SET ativo = true, decidido_por = :u WHERE agent_id = :a AND NOT ativo"), {"u": user.id, "a": a})
    return {"agent_id": str(a), "conversation_id": str(conv)}


@router.get("/consultor/avaliacoes")
async def avaliacoes(user: CurrentUser = User) -> list[dict[str, Any]]:
    async with tx(user.id) as conn:
        return await rows(conn, """SELECT v.id, v.conversation_id, v.titulo, v.estado, v.camada_declarada, v.camada_real, v.camada_minima,
                                          v.rubrica_versao, v.atualizado_em, p.versao AS parecer_versao, p.nota_geral, p.veredito, p.risco,
                                          p.pdf_document_id
                                     FROM consultor_avaliacao v LEFT JOIN LATERAL (
                                          SELECT * FROM consultor_parecer x WHERE x.avaliacao_id = v.id ORDER BY versao DESC LIMIT 1) p ON true
                                    ORDER BY v.atualizado_em DESC LIMIT 100""")


@router.get("/consultor/avaliacoes/{aid}")
async def avaliacao(aid: UUID, user: CurrentUser = User) -> dict[str, Any]:
    async with tx(user.id) as conn:
        av = await row(conn, "SELECT * FROM consultor_avaliacao WHERE id = :a", a=aid)
        if not av:
            raise NotFound("Avaliação não encontrada.")
        pareceres = await rows(conn, """SELECT versao, nota_geral, veredito, risco, hash, hash_anterior, hash_entrada, pdf_document_id, em
                                          FROM consultor_parecer WHERE avaliacao_id = :a ORDER BY versao""", a=aid)
        quebra = await rows(conn, "SELECT * FROM verify_parecer_chain(:a)", a=aid)
        estados = await rows(conn, """SELECT e.criterio_id, e.estado, e.origem, e.justificativa, e.em, ev.pagina, ev.trecho
                                        FROM consultor_criterio_estado e LEFT JOIN consultor_evidencia ev ON ev.id = e.evidencia_id
                                       WHERE e.avaliacao_id = :a ORDER BY e.id""", a=aid)
    return {"avaliacao": av, "pareceres": pareceres, "cadeia_ok": not quebra, "historico_estados": estados}


class RespostaIn(BaseModel):
    criterio_id: str = Field(pattern=r"^(N0[1-5]|C[1-6]\.[1-5])$")
    indice: int | None = Field(default=None, ge=0, le=9)
    confirmar: bool | None = None


@router.post("/consultor/avaliacoes/{aid}/respostas", status_code=204, response_model=None)
async def responder(aid: UUID, body: RespostaIn, user: CurrentUser = User) -> None:
    await consultor.responder(user.id, aid, body.criterio_id, body.indice, body.confirmar)


class ContestacaoIn(BaseModel):
    criterio_id: str = Field(pattern=r"^(N0[1-5]|C[1-6]\.[1-5])$")
    indice: int = Field(ge=0, le=9)
    justificativa: str = Field(default="", max_length=500)


@router.post("/consultor/avaliacoes/{aid}/contestacoes")
async def contestar(aid: UUID, body: ContestacaoIn, user: CurrentUser = User) -> dict[str, Any]:
    return await consultor.contestar(user.id, aid, body.criterio_id, body.indice, body.justificativa)


# ----------------------------------------------------------------- rubricas (versionadas)
@router.get("/rubricas")
async def rubricas(user: CurrentUser = User) -> list[dict[str, Any]]:
    async with tx(user.id) as conn:
        return await rows(conn, "SELECT versao, ativa, nota, criada_em, definicao FROM rubrica_versao ORDER BY criada_em DESC")


class CriterioIn(BaseModel):
    id: str = Field(pattern=r"^(N0[1-5]|C[1-6]\.[1-5])$")
    camada: str | int
    texto: str = Field(min_length=3, max_length=200)
    peso: int = Field(ge=1, le=5)
    critico: bool
    pergunta: str = Field(min_length=5, max_length=400)
    respostas_rapidas: list[str] = Field(min_length=2, max_length=4)
    mapa_resposta: dict[str, Literal["DECLARADO", "NAO_ATENDE", "LACUNA"]]


class RubricaIn(BaseModel):
    base: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    criterios: list[CriterioIn] = Field(min_length=5, max_length=60)
    limiar_pronta: int = Field(ge=1, le=100)
    nota: str = Field(min_length=3, max_length=500)
    ativar: bool = True


def _bump(base: str, kind: Literal["patch", "minor"]) -> str:
    ma, mi, pa = (int(x) for x in base.split("."))
    return f"{ma}.{mi}.{pa + 1}" if kind == "patch" else f"{ma}.{mi + 1}.0"


@router.post("/rubricas", status_code=201)
async def nova_rubrica(body: RubricaIn, user: CurrentUser = Admin) -> dict[str, Any]:
    """Editar gera versão nova (CAMADAS-001 §14): texto/pergunta = patch; peso, crítico, critério ou limiar = menor. Avaliação selada
    nunca é recalculada; a versão antiga continua valendo para quem a usou."""
    async with tx(user.id) as conn:
        base = await row(conn, "SELECT definicao FROM rubrica_versao WHERE versao = :v", v=body.base)
        if not base:
            raise NotFound("Versão base não encontrada.")
        old = {c["id"]: c for c in base["definicao"]["criterios"]}
        ids = [c.id for c in body.criterios]
        if len(set(ids)) != len(ids):
            raise Invalid("Critério repetido.")
        for c in body.criterios:
            if len(c.mapa_resposta) != len(c.respostas_rapidas) or set(c.mapa_resposta) != {str(i) for i in range(len(c.respostas_rapidas))}:
                raise Invalid(f"{c.id}: cada resposta rápida precisa de um estado no mapa (G11).")
            camada_ok = c.camada == "nucleo" if c.id.startswith("N") else str(c.camada) == c.id[1]
            if not camada_ok:
                raise Invalid(f"{c.id}: camada não confere com o ID.")
        removidos = set(old) - set(ids)
        estrutural = (removidos or set(ids) - set(old) or body.limiar_pronta != base["definicao"]["veredito"]["limiar_pronta"]
                      or any((o := old.get(c.id)) and (o["peso"] != c.peso or o["critico"] != c.critico) for c in body.criterios))
        versao = _bump(body.base, "minor" if estrutural else "patch")
        while await scalar(conn, "SELECT 1 FROM rubrica_versao WHERE versao = :v", v=versao):
            versao = _bump(versao, "patch")
        defn = {**base["definicao"], "versao": versao, "veredito": {"limiar_pronta": body.limiar_pronta},
                "criterios": [{**c.model_dump(), "camada": c.camada if c.camada == "nucleo" else int(c.camada),
                               "mapa_resposta": {int(k): v for k, v in c.mapa_resposta.items()}} for c in body.criterios],
                "obsoletos": sorted(set(base["definicao"].get("obsoletos", [])) | removidos)}
        if set(ids) & set(defn["obsoletos"]):
            raise Invalid("ID obsoleto não pode ser reaproveitado (§14).")
        if body.ativar:
            await conn.execute(text("UPDATE rubrica_versao SET ativa = false WHERE ativa"))
        await conn.execute(text("""INSERT INTO rubrica_versao (versao, definicao, ativa, nota, criada_por)
                                   VALUES (:v, CAST(:d AS jsonb), :a, :n, :u)"""),
                           {"v": versao, "d": json.dumps(defn, ensure_ascii=False), "a": body.ativar, "n": body.nota, "u": user.id})
    return {"versao": versao, "tipo": "menor" if estrutural else "patch", "ativa": body.ativar}


@router.post("/rubricas/{versao}/ativar")
async def ativar_rubrica(versao: str, user: CurrentUser = Admin) -> dict[str, str]:
    if not re.fullmatch(r"\d+\.\d+\.\d+", versao):
        raise Invalid("Versão inválida.")
    async with tx(user.id) as conn:
        if not await scalar(conn, "SELECT 1 FROM rubrica_versao WHERE versao = :v", v=versao):
            raise NotFound("Versão não encontrada.")
        await conn.execute(text("UPDATE rubrica_versao SET ativa = false WHERE ativa"))
        await conn.execute(text("UPDATE rubrica_versao SET ativa = true WHERE versao = :v"), {"v": versao})
    return {"versao": versao}

