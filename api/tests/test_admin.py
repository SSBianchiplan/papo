"""Administração da IA e controle de custos: permissão, chave cifrada, preços, teto mensal e limite diário."""
from __future__ import annotations

from typing import Any

import httpx
import pytest
from test_flow import FakeLLM, H, run_jobs

from app import costs, secretbox

KEY = "sk-ant-api03-" + "x" * 40 + "AbCd"


@pytest.fixture
async def reset_ai(client: httpx.AsyncClient) -> Any:
    yield
    await client.delete("/api/admin/ai/key", headers=H("admin"))
    await client.put("/api/admin/ai", json={"workspace_id": None, "monthly_budget_usd": None, "alert_pct": 80, "daily_token_limit": None},
                     headers=H("admin"))


def test_preco_casa_por_prefixo_mais_longo() -> None:
    prices = [costs.Price("claude-haiku-4-5", "Haiku", 1, 5), costs.Price("claude-opus-5-5", "Opus", 4, 20), costs.Price("claude-opus-5", "Opus 5", 5, 25)]
    assert costs.price_for("claude-haiku-4-5-20251001", prices).label == "Haiku"  # type: ignore[union-attr]
    assert costs.price_for("claude-opus-5-5", prices).label == "Opus"  # type: ignore[union-attr]
    assert costs.price_for("claude-opus-5", prices).label == "Opus 5"  # type: ignore[union-attr]
    assert costs.price_for("modelo-desconhecido", prices) is None
    assert costs.cost_usd("claude-opus-5-5", 1_000_000, 500_000, prices) == pytest.approx(14.0)   # 4 + 0,5×20


def test_cifra_da_chave_ida_e_volta_e_resumo() -> None:
    blob = secretbox.seal(KEY)
    assert KEY.encode() not in blob and secretbox.open_(blob) == KEY
    assert secretbox.hint(KEY) == "sk-ant-api03-…AbCd"


async def test_area_admin_fechada_para_usuario_comum(client: httpx.AsyncClient) -> None:
    for method, url in [("GET", "/api/admin/ai"), ("PUT", "/api/admin/ai/key"), ("GET", "/api/admin/usage"), ("PUT", "/api/admin/prices")]:
        r = await client.request(method, url, headers=H("bia"), json={"api_key": KEY} if "key" in url else [] if "prices" in url else None)
        assert r.status_code == 403, url
    assert (await client.get("/api/me", headers=H("bia"))).json()["is_admin"] is False
    assert (await client.get("/api/me", headers=H("admin"))).json()["is_admin"] is True


async def test_chave_gravada_cifrada_e_nunca_devolvida(client: httpx.AsyncClient, reset_ai: Any, app_conn: Any) -> None:
    r = await client.put("/api/admin/ai/key", json={"api_key": KEY, "workspace_id": "wrkspc_01ABC"}, headers=H("admin"))
    assert r.status_code == 200, r.text
    st = r.json()
    assert st["key_source"] == "painel" and st["key_hint"] == "sk-ant-api03-…AbCd" and st["workspace_id"] == "wrkspc_01ABC"
    assert KEY not in r.text and KEY not in (await client.get("/api/admin/ai", headers=H("admin"))).text
    with app_conn() as c:
        enc = c.execute("SELECT anthropic_key_enc FROM app_config").fetchone()[0]
    assert KEY.encode() not in bytes(enc)

    r = await client.put("/api/admin/ai/key", json={"api_key": "sk-ant-admin01-" + "y" * 30}, headers=H("admin"))
    assert r.status_code == 422                                     # chave de administração da organização não serve
    r = await client.put("/api/admin/ai/key", json={"api_key": "chave qualquer"}, headers=H("admin"))
    assert r.status_code == 422

    r = await client.delete("/api/admin/ai/key", headers=H("admin"))
    assert r.json()["key_source"] in ("servidor", "nenhuma")


async def test_worker_usa_a_chave_do_painel(client: httpx.AsyncClient, reset_ai: Any) -> None:
    from app.agent.llm import AnthropicLLM, UnconfiguredLLM
    from app.worker import current_llm

    ctx: dict[str, Any] = {}
    assert isinstance(await current_llm(ctx), UnconfiguredLLM)
    await client.put("/api/admin/ai/key", json={"api_key": KEY, "workspace_id": "wrkspc_01ABC"}, headers=H("admin"))
    llm = await current_llm(ctx)
    assert isinstance(llm, AnthropicLLM)
    assert llm.client.api_key == KEY and llm.client.default_headers["anthropic-workspace-id"] == "wrkspc_01ABC"
    assert await current_llm(ctx) is llm                           # reaproveita o cliente enquanto a chave não muda


async def test_consumo_e_custo_por_usuario_e_no_painel(client: httpx.AsyncClient, jobs: list[Any]) -> None:
    from test_flow import setup_agent_with_sheet

    _, conv = await setup_agent_with_sheet(client, jobs, "caio")
    await client.post(f"/api/conversations/{conv}/messages", json={"body": "oi"}, headers=H("caio"))
    await run_jobs(jobs, FakeLLM([("text", "Olá!")]))

    u = (await client.get("/api/usage?days=7", headers=H("caio"))).json()
    assert len(u["days"]) == 7 and u["today_tokens"] == 240 and u["total_tokens"] == 240
    m = u["by_model"][0]
    assert m["model"] == "claude-sonnet-5-5" and m["label"] == "Claude Sonnet 5.5"
    assert m["cost_usd"] == pytest.approx((200 * 2 + 40 * 10) / 1_000_000)
    assert u["days"][-1]["cost_usd"] == pytest.approx(m["cost_usd"])

    a = (await client.get("/api/admin/usage?days=7", headers=H("admin"))).json()
    caio = next(x for x in a["by_user"] if x["name"] == "caio")
    assert caio["today_tokens"] == 240 and caio["cost_usd"] == pytest.approx(m["cost_usd"])
    assert a["month_cost_all_usd"] >= m["cost_usd"]


async def test_teto_mensal_e_limite_diario_bloqueiam_sem_chamar_o_modelo(client: httpx.AsyncClient, jobs: list[Any], reset_ai: Any) -> None:
    from test_flow import setup_agent_with_sheet

    _, conv = await setup_agent_with_sheet(client, jobs, "duda")
    await client.post(f"/api/conversations/{conv}/messages", json={"body": "oi"}, headers=H("duda"))
    await run_jobs(jobs, FakeLLM([("text", "Olá!")]))             # gera consumo > 0

    r = await client.put("/api/admin/ai", json={"monthly_budget_usd": 0, "alert_pct": 80}, headers=H("admin"))
    assert r.status_code == 200 and r.json()["monthly_budget_usd"] == 0
    await client.post(f"/api/conversations/{conv}/messages", json={"body": "de novo"}, headers=H("duda"))
    llm = FakeLLM([])
    await run_jobs(jobs, llm)
    assert llm.calls == []
    last = (await client.get(f"/api/conversations/{conv}/messages", headers=H("duda"))).json()[-1]
    assert last["author"] == "system" and "orçamento mensal" in last["body"]

    await client.put("/api/admin/ai", json={"monthly_budget_usd": None, "daily_token_limit": 100}, headers=H("admin"))
    assert (await client.get("/api/me", headers=H("duda"))).json()["daily_limit"] == 100
    await client.post(f"/api/conversations/{conv}/messages", json={"body": "e agora"}, headers=H("duda"))
    await run_jobs(jobs, llm)
    assert llm.calls == []
    last = (await client.get(f"/api/conversations/{conv}/messages", headers=H("duda"))).json()[-1]
    assert "Limite diário" in last["body"]


async def test_tabela_de_precos_editavel(client: httpx.AsyncClient) -> None:
    original = (await client.get("/api/admin/ai", headers=H("admin"))).json()["prices"]
    novo = [*original, {"model": "claude-teste-9", "label": "Modelo de teste", "input_usd_mtok": 90, "output_usd_mtok": 900}]
    r = await client.put("/api/admin/prices", json=novo, headers=H("admin"))
    assert r.status_code == 200 and r.json()[0]["model"] == "claude-teste-9"
    assert (await client.put("/api/admin/prices", json=[original[0], original[0]], headers=H("admin"))).status_code == 422
    assert (await client.put("/api/admin/prices", json=original, headers=H("admin"))).status_code == 200


async def test_nome_do_workspace_recusado_no_lugar_do_id(client: httpx.AsyncClient, reset_ai: Any) -> None:
    r = await client.put("/api/admin/ai", json={"workspace_id": "papo-rag", "alert_pct": 80}, headers=H("admin"))
    assert r.status_code == 422 and "nome do workspace" in r.json()["message"] and "wrkspc_" in r.json()["hint"]
    r = await client.put("/api/admin/ai/key", json={"api_key": KEY, "workspace_id": "papo-rag"}, headers=H("admin"))
    assert r.status_code == 422
    r = await client.put("/api/admin/ai", json={"workspace_id": "wrkspc_01AbCdEf", "alert_pct": 80}, headers=H("admin"))
    assert r.status_code == 200 and r.json()["workspace_id"] == "wrkspc_01AbCdEf"


async def test_catalogo_e_escolha_de_modelo_por_nivel(client: httpx.AsyncClient, jobs: list[Any]) -> None:
    from test_flow import setup_agent_with_sheet

    st = (await client.get("/api/admin/ai", headers=H("admin"))).json()
    ids = {m["model"] for m in st["catalog"]}
    assert {"claude-fable-5-1", "claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-4-5", "claude-sonnet-4-6"} <= ids
    assert st["models"]["default"] == "claude-sonnet-5-5" and "default" in next(m for m in st["catalog"] if m["model"] == "claude-sonnet-5-5")["used_by"]

    r = await client.put("/api/admin/models", json={"default": "claude-opus-5-5", "router": "claude-haiku-4-5"}, headers=H("admin"))
    assert r.status_code == 200 and r.json()["models"]["default"] == "claude-opus-5-5"
    assert (await client.get("/api/me", headers=H("eva"))).json()["tiers"]["default"] == "Claude Opus 5.5"

    _, conv = await setup_agent_with_sheet(client, jobs, "eva")
    await client.post(f"/api/conversations/{conv}/messages", json={"body": "oi"}, headers=H("eva"))
    llm = FakeLLM([("text", "Olá!")])
    await run_jobs(jobs, llm)
    assert llm.calls[0]["model"] == "claude-opus-5-5"                # a escolha do painel vale no próximo job

    assert (await client.put("/api/admin/models", json={"default": "gpt-qualquer"}, headers=H("admin"))).status_code == 422
    assert (await client.put("/api/admin/models", json={"default": "claude-opus-5-5"}, headers=H("bia"))).status_code == 403
    r = await client.put("/api/admin/models", json={}, headers=H("admin"))          # volta ao .env
    assert r.json()["models"]["default"] == "claude-sonnet-5-5"
