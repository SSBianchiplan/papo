"""Motor de planilha e números em formato brasileiro."""
from __future__ import annotations

import math

import pytest

from app.agent.tools import DocInfo, Filtro, ToolFail, agrupar, apply_filters, describe, filtrar, find_doc, to_num

COLS = ["Região", "Valor", "Mês"]
DATA = [["Sul", "1.200,50", "jan"], ["Norte", 300, "jan"], ["Sul", 99.5, "fev"], ["Sudeste", "2.000", "fev"], ["Sul", "", "mar"]]


@pytest.mark.parametrize(("v", "n"), [("R$ 1.234,56", 1234.56), ("1,234.5", 1234.5), ("12,5%", 12.5), (7, 7.0), ("2.000", 2000.0), ("-3,2", -3.2)])
def test_to_num(v: object, n: float) -> None:
    assert to_num(v) == n


@pytest.mark.parametrize("v", ["abc", "", None, True, "1.2.3,4,5"])
def test_to_num_nao_numero(v: object) -> None:
    assert math.isnan(to_num(v))


def test_agrupar_soma_por_regiao_sem_acento() -> None:
    r = agrupar(COLS, DATA, ["regiao"], "valor", "soma", "desc", 30)
    assert r["agrupado_por"] == ["Região"] and r["total_geral"] == 3600.0
    assert [(g["grupo"], g["valor"]) for g in r["resultado"]] == [("Sudeste", 2000.0), ("Sul", 1300.0), ("Norte", 300.0)]


def test_agrupar_media_ignora_vazio() -> None:
    r = agrupar(COLS, DATA, ["Região"], "Valor", "media", "desc", 30)
    sul = next(g for g in r["resultado"] if g["grupo"] == "Sul")
    assert sul["valor"] == 650.0 and sul["linhas"] == 3


def test_filtrar_numerico_ordenado() -> None:
    rows = apply_filters(COLS, DATA, [Filtro(coluna="Valor", op=">", valor="500")])
    r = filtrar(COLS, rows, "Valor", "desc", [], 30)
    assert r["total_encontrado"] == 2 and r["linhas"][0]["Região"] == "Sudeste"


def test_filtro_texto_contem_sem_acento() -> None:
    rows = apply_filters(COLS, DATA, [Filtro(coluna="Região", op="contem", valor="sudes")])
    assert len(rows) == 1


def test_coluna_inexistente_explica() -> None:
    with pytest.raises(ToolFail) as e:
        apply_filters(COLS, DATA, [Filtro(coluna="Preço", op="=", valor=1)])
    assert "Colunas" in (e.value.hint or "")


def test_descrever() -> None:
    d = describe(COLS, DATA, 5)
    valor = d["colunas"][1]
    assert valor["tipo"] == "numérico" and valor["soma"] == 3600.0 and valor["preenchidos"] == 4


def test_find_doc_aproximado() -> None:
    import uuid

    docs = [DocInfo(uuid.uuid4(), "Contrato Fornecimento.pdf", "pdf", 3, None, 3), DocInfo(uuid.uuid4(), "vendas.xlsx", "table", None, None, 0)]
    assert find_doc(docs, "contrato fornecimento") is docs[0]
    assert find_doc(docs, "VENDAS") is docs[1]
    assert find_doc(docs, "inexistente") is None


@pytest.mark.parametrize(("op", "valor", "n"), [("=", "sul", 3), ("!=", "Sul", 2), (">=", 300, 3), ("<", 300, 1), ("<=", 99.5, 1)])
def test_operadores_de_filtro(op: str, valor: object, n: int) -> None:
    col = "Região" if op in ("=", "!=") else "Valor"
    assert len(apply_filters(COLS, DATA, [Filtro(coluna=col, op=op, valor=valor)])) == n  # type: ignore[arg-type]


def test_agrupar_contagem_sem_coluna_e_ordem_asc() -> None:
    r = agrupar(COLS, DATA, ["Mês"], None, "contagem", "asc", 30)
    assert r["total_geral"] == 5 and r["resultado"][0]["valor"] == 1.0


def test_agrupar_exige_coluna_numerica() -> None:
    with pytest.raises(ToolFail):
        agrupar(COLS, DATA, ["Região"], None, "soma", "desc", 30)


def test_filtrar_ordem_texto_e_colunas() -> None:
    r = filtrar(COLS, DATA, "Região", "asc", ["Região"], 2)
    assert r["mostrando"] == 2 and list(r["linhas"][0]) == ["Região"] and r["linhas"][0]["Região"] == "Norte"
    with pytest.raises(ToolFail):
        filtrar(COLS, DATA, "Nada", "asc", [], 2)


def test_descrever_texto_com_valores() -> None:
    mes = describe(COLS, DATA, 5)["colunas"][2]
    assert mes["tipo"] == "texto" and mes["valores"] == ["fev", "jan", "mar"]


def test_tool_specs_validos() -> None:
    from app.agent.tools import tool_specs

    names = {t["name"] for t in tool_specs()}
    assert names == {"listar_documentos", "buscar_nos_documentos", "ler_documento", "analisar_planilha", "gerar_arquivo", "buscar_na_conversa"}
    assert {t["name"] for t in tool_specs(with_docs=False)} == {"gerar_arquivo", "buscar_na_conversa"}
    assert all(t["description"] and t["input_schema"]["type"] == "object" for t in tool_specs())


async def test_sem_chave_da_ia_falha_com_aviso_legivel() -> None:
    from app.agent.engine import friendly_error
    from app.agent.llm import LLMNotConfigured, UnconfiguredLLM

    with pytest.raises(LLMNotConfigured) as e:
        await UnconfiguredLLM().complete(model="m", prompt="oi")
    assert "não foi configurado" in friendly_error(e.value)
