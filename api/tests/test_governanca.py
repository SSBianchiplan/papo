"""Governança de IA (SPEC-GPS-CAMADAS-001 e ficha da SPEC-GPS-PAPO-CIA-001 §7): ficha, matriz, I4, gatilhos, canais, ferramentas."""
from __future__ import annotations

from typing import Any

import httpx
import pytest
from test_flow import FakeLLM, H, run_jobs


async def _agent_dm(client: httpx.AsyncClient, user: str, name: str = "Analista") -> tuple[str, str]:
    a = (await client.post("/api/agents", json={"name": name}, headers=H(user))).json()["id"]
    c = (await client.post("/api/conversations", json={"kind": "dm", "agent_id": a}, headers=H(user))).json()["id"]
    return a, c


async def _ficha(client: httpx.AsyncClient, user: str, agent: str) -> dict[str, Any]:
    return next(f for f in (await client.get("/api/governanca/fichas", headers=H(user))).json() if f["agent_id"] == agent)


async def _put(client: httpx.AsyncClient, user: str, agent: str, **chg: Any) -> httpx.Response:
    f = await _ficha(client, user, agent)
    body = {k: f[k] for k in ("dono", "camada_real", "nivel", "fontes", "ferramentas", "raio_acao", "max_iteracoes", "max_custo_conversa_usd",
                              "max_segundos_turno", "aprovacao_humana", "gatilhos", "canais", "retencao_dias", "camadas_no_contexto",
                              "uso_interno_evidencia", "excecao_m3", "ativo")}
    return await client.put(f"/api/governanca/fichas/{agent}", json=body | chg, headers=H(user))


async def test_todo_agente_nasce_com_ficha_completa_m1(client: httpx.AsyncClient) -> None:
    a, _ = await _agent_dm(client, "gv1")
    f = await _ficha(client, "gv1", a)
    assert f["completa"] and f["ativo"] and f["nivel"] == "M1" and f["camada_real"] == 6 and f["dono"] == "gv1"
    assert {t["nome"] for t in f["ferramentas"]} >= {"ler_documento", "gerar_arquivo"} and f["permissao_matriz"] == "Padrão"
    m = (await client.get("/api/governanca/modelo", headers=H("gv1"))).json()
    assert m["versao"] == "1.0.0" and len(m["camadas"]) == 6 and m["matriz"]["5"]["M3"] == "Proibido" and "T8" in m["gatilhos"]


async def test_i4_e_matriz_no_banco(client: httpx.AsyncClient, app_conn: Any) -> None:
    import psycopg

    a, _ = await _agent_dm(client, "gv2")
    uid = (await client.get("/api/me", headers=H("gv2"))).json()["id"]
    with app_conn() as c:
        c.execute("SELECT set_config('papo.uid', %s, false)", (uid,))
        with pytest.raises(psycopg.errors.CheckViolation):                     # I4 (G09): ativo sem dono
            c.execute("UPDATE agent_ficha SET dono = '' WHERE agent_id = %s", (a,))
        with pytest.raises(psycopg.errors.CheckViolation):                     # matriz: M3 proibido na camada 5
            c.execute("UPDATE agent_ficha SET camada_real = 5, nivel = 'M3' WHERE agent_id = %s", (a,))
        with pytest.raises(psycopg.errors.CheckViolation):                     # M3 na agêntica sem exceção aprovada
            c.execute("UPDATE agent_ficha SET nivel = 'M3' WHERE agent_id = %s", (a,))
    r = await _put(client, "gv2", a, raio_acao="", ativo=True)
    assert r.status_code == 422 and "raio de ação" in r.json()["hint"]
    assert (await client.patch(f"/api/governanca/fichas/{a}/ativo?ativo=false", headers=H("gv2"))).json()["ativo"] is False
    assert (await _put(client, "gv2", a, nivel="M2")).status_code == 403               # promoção só por administrador
    hist = (await client.get(f"/api/governanca/fichas/{a}/historico", headers=H("gv2"))).json()
    assert hist[0]["versao"] > 1 and hist[0]["ativo"] is False


async def test_agente_inativo_nao_responde(client: httpx.AsyncClient, jobs: list[Any]) -> None:
    a, c = await _agent_dm(client, "gv3")
    await client.patch(f"/api/governanca/fichas/{a}/ativo?ativo=false", headers=H("gv3"))
    await client.post(f"/api/conversations/{c}/messages", json={"body": "oi"}, headers=H("gv3"))
    llm = FakeLLM([])
    await run_jobs(jobs, llm)
    assert llm.calls == []
    last = (await client.get(f"/api/conversations/{c}/messages", headers=H("gv3"))).json()[-1]
    assert last["author"] == "system" and "desativado na governança" in last["body"]
    ev = (await client.get("/api/governanca/eventos", headers=H("gv3"))).json()
    assert ev[0]["codigo"] == "INATIVO"


async def test_lista_fechada_m0_camadas_e_gatilho(client: httpx.AsyncClient, jobs: list[Any]) -> None:
    a, c = await _agent_dm(client, "gv4")
    f = await _ficha(client, "gv4", a)
    sem_arquivo = [t for t in f["ferramentas"] if t["nome"] != "gerar_arquivo"]
    await _put(client, "gv4", a, ferramentas=sem_arquivo, camadas_no_contexto=True)
    await client.post(f"/api/conversations/{c}/messages", json={"body": "gere um relatório"}, headers=H("gv4"))
    llm = FakeLLM([("tool", "gerar_arquivo", {"formato": "md", "nome": "x", "titulo": "X", "conteudo": "x"}), ("text", "Não posso gerar arquivo.")])
    await run_jobs(jobs, llm)
    assert "gerar_arquivo" not in {t["name"] for t in llm.calls[0]["tools"]}                 # C6.1: fora da lista, nem é oferecida
    assert "Modelo de Camadas" in llm.calls[0]["system"]
    assert llm.calls[1]["messages"][-1]["content"][0]["is_error"]                             # e se o modelo tentar, é recusada
    ev = (await client.get("/api/governanca/eventos", headers=H("gv4"))).json()
    assert ev[0]["codigo"] == "T8" and "gerar_arquivo" in ev[0]["detalhe"]

    await _put(client, "gv4", a, nivel="M0", ferramentas=f["ferramentas"])                    # M0: escrita nunca é oferecida
    await client.post(f"/api/conversations/{c}/messages", json={"body": "de novo"}, headers=H("gv4"))
    llm = FakeLLM([("text", "ok")])
    await run_jobs(jobs, llm)
    assert "gerar_arquivo" not in {t["name"] for t in llm.calls[0]["tools"]} and "M0" in llm.calls[0]["system"]


async def test_teto_de_custo_para_o_turno_t7(client: httpx.AsyncClient, jobs: list[Any]) -> None:
    a, c = await _agent_dm(client, "gv5")
    await client.post(f"/api/conversations/{c}/messages", json={"body": "oi"}, headers=H("gv5"))
    await run_jobs(jobs, FakeLLM([("text", "Olá")]))                      # gera consumo
    await _put(client, "gv5", a, max_custo_conversa_usd=0.0001)
    await client.post(f"/api/conversations/{c}/messages", json={"body": "continue"}, headers=H("gv5"))
    llm = FakeLLM([])
    await run_jobs(jobs, llm)
    assert llm.calls == []
    last = (await client.get(f"/api/conversations/{c}/messages", headers=H("gv5"))).json()[-1]
    assert "teto de custo" in last["body"]
    assert (await client.get("/api/governanca/eventos", headers=H("gv5"))).json()[0]["codigo"] == "T7"


async def test_canais_e_opcoes_por_conversa(client: httpx.AsyncClient, jobs: list[Any]) -> None:
    a1, _ = await _agent_dm(client, "gv6", "Ana")
    a2, _ = await _agent_dm(client, "gv6", "Beto")
    g = (await client.post("/api/conversations", json={"kind": "group", "name": "Time", "members": [a1, a2]}, headers=H("gv6"))).json()["id"]
    await _put(client, "gv6", a2, canais=["direto", "mencao"])               # Beto só responde em grupo quando mencionado
    assert (await client.put(f"/api/governanca/conversas/{g}", json={"camadas": True}, headers=H("gv6"))).status_code == 200
    await client.post(f"/api/conversations/{g}/messages", json={"body": "todos: opinião?"}, headers=H("gv6"))
    llm = FakeLLM([("text", "Ana aqui")])
    await run_jobs(jobs, llm)
    assert len(llm.calls) == 1 and "Modelo de Camadas" in llm.calls[0]["system"]
    msgs = (await client.get(f"/api/conversations/{g}/messages", headers=H("gv6"))).json()
    assert [m["agent_name"] for m in msgs if m["author"] == "agent"] == ["Ana"]
