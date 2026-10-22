"""Administração do serviço de IA: chave da Anthropic, workspace, orçamento, limite diário e preços por modelo.

A chave entra por aqui, sai cifrada para o banco (AES-GCM, SECRETS_KEY só no ambiente) e nunca volta inteira:
a API devolve apenas um resumo (prefixo…final). O teste roda no worker, o único serviço com saída para a internet.
"""
from __future__ import annotations

import logging
import re
from typing import Any

from fastapi import APIRouter

from .. import bus, costs, secretbox
from ..auth import Admin, CurrentUser
from ..config import get_settings
from ..db import tx
from ..errors import Invalid
from ..schemas import AiConfigIn, AiStatus, KeyIn, KeyTest, ModelChoice, ModelInfo, PriceOut

router = APIRouter(prefix="/api/admin", tags=["administração"])
log = logging.getLogger("papo.admin")


def _workspace(ws: str | None) -> str | None:
    """O header aceita só o ID (wrkspc_…). O nome do workspace, que é o que o Console mostra em destaque, é recusado."""
    ws = (ws or "").strip() or None
    if ws and not ws.startswith("wrkspc_"):
        raise Invalid(f'"{ws}" parece ser o nome do workspace, não o ID.',
                      hint="O ID começa com wrkspc_. No Console: Settings → Workspaces → abra o workspace e copie o ID.")
    return ws


def _t(sql: str) -> Any:
    from sqlalchemy import text
    return text(sql)


async def _status(user: CurrentUser) -> AiStatus:
    async with tx(user.id) as conn:
        ai = await costs.load_ai_config(conn)
        prices = await costs.load_prices(conn)
        month = await costs.month_cost(conn, prices)
    s = get_settings()
    source: costs.KeySource = "painel" if ai.key_enc else "servidor" if s.anthropic_api_key else "nenhuma"
    hint = ai.key_hint if ai.key_enc else secretbox.hint(s.anthropic_api_key) if s.anthropic_api_key else None
    in_use = {t: costs.model_for(ai, t) for t in costs.TIERS}
    avail = set(ai.models_available) if ai.models_available is not None else None
    # disponível = o ID exato, ou ele com sufixo de data (claude-haiku-4-5-20251001); claude-sonnet-5 não herda claude-sonnet-5-5
    catalog = [ModelInfo(**p.__dict__, available=None if avail is None else any(re.fullmatch(re.escape(p.model) + r"(-\d{8})?", m) for m in avail),
                         used_by=[t for t, m in in_use.items() if costs.price_for(m, prices) == p]) for p in prices]
    return AiStatus(key_source=source, key_hint=hint, workspace_id=ai.workspace_id or s.anthropic_workspace_id or None,
                    secrets_ready=bool(s.secrets_key), monthly_budget_usd=ai.monthly_budget_usd, alert_pct=ai.alert_pct,
                    daily_token_limit=ai.daily_token_limit, server_daily_limit=s.daily_token_limit, month_cost_usd=round(month, 6),
                    prices=[PriceOut(**p.__dict__) for p in prices], models=in_use, models_panel=ModelChoice(**(ai.models or {})),
                    models_env={"quick": s.model_quick, "default": s.model_default, "complex": s.model_complex, "router": s.model_router},
                    catalog=catalog, models_checked_at=ai.models_checked_at)


@router.get("/ai", response_model=AiStatus)
async def get_ai(user: CurrentUser = Admin) -> AiStatus:
    return await _status(user)


@router.put("/ai", response_model=AiStatus)
async def put_ai(body: AiConfigIn, user: CurrentUser = Admin) -> AiStatus:
    async with tx(user.id) as conn:
        await conn.execute(_t("""UPDATE app_config SET anthropic_workspace_id = :w, monthly_budget_usd = :b, alert_pct = :a,
                                        daily_token_limit = :d, updated_by = :u, updated_at = now()"""),
                           {"w": _workspace(body.workspace_id), "b": body.monthly_budget_usd, "a": body.alert_pct, "d": body.daily_token_limit, "u": user.id})
    log.info("configuração da IA alterada por %s", user.id)
    return await _status(user)


@router.put("/models", response_model=AiStatus)
async def put_models(body: ModelChoice, user: CurrentUser = Admin) -> AiStatus:
    async with tx(user.id) as conn:
        prices = await costs.load_prices(conn)
        for model in body.model_dump().values():
            if model and not costs.price_for(model, prices):
                raise Invalid(f'"{model}" não está no catálogo.', hint="Cadastre o modelo e o preço em Preços por modelo antes de escolhê-lo.")
        await conn.execute(_t("""UPDATE app_config SET model_quick = :quick, model_default = :default, model_complex = :complex,
                                        model_router = :router, updated_by = :u, updated_at = now()"""), {**body.model_dump(), "u": user.id})
    log.info("modelos por nível alterados por %s: %s", user.id, body.model_dump())
    return await _status(user)


@router.put("/ai/key", response_model=AiStatus)
async def put_key(body: KeyIn, user: CurrentUser = Admin) -> AiStatus:
    key = body.api_key.strip()
    if key.startswith("sk-ant-admin"):
        raise Invalid("Essa é uma chave de administração da organização, não serve para conversar.", hint="Use uma chave de API (sk-ant-api… ou sk-ant-usr…).")
    blob = secretbox.seal(key)
    async with tx(user.id) as conn:
        await conn.execute(_t("""UPDATE app_config SET anthropic_key_enc = :k, anthropic_key_hint = :h,
                                        anthropic_workspace_id = coalesce(:w, anthropic_workspace_id), updated_by = :u, updated_at = now()"""),
                           {"k": blob, "h": secretbox.hint(key), "w": _workspace(body.workspace_id), "u": user.id})
    log.info("chave da IA trocada por %s (%s)", user.id, secretbox.hint(key))
    return await _status(user)


@router.delete("/ai/key", response_model=AiStatus)
async def delete_key(user: CurrentUser = Admin) -> AiStatus:
    async with tx(user.id) as conn:
        await conn.execute(_t("""UPDATE app_config SET anthropic_key_enc = NULL, anthropic_key_hint = NULL,
                                        updated_by = :u, updated_at = now()"""), {"u": user.id})
    log.info("chave da IA do painel removida por %s", user.id)
    return await _status(user)


@router.post("/ai/test", response_model=KeyTest)
async def test_key(user: CurrentUser = Admin) -> KeyTest:
    job = await (await bus.queue()).enqueue_job("job_test_key")
    if job is None:
        raise Invalid("Já há um teste em andamento.")
    try:
        r = await job.result(timeout=40, poll_delay=0.4)
    except TimeoutError:
        return KeyTest(ok=False, message="O worker não respondeu a tempo. Verifique se ele está no ar.")
    return KeyTest(**r)


@router.put("/prices", response_model=list[PriceOut])
async def put_prices(body: list[PriceOut], user: CurrentUser = Admin) -> list[PriceOut]:
    if not body:
        raise Invalid("Informe ao menos um modelo.")
    if len({p.model for p in body}) != len(body):
        raise Invalid("Modelo repetido na tabela de preços.")
    async with tx(user.id) as conn:
        await conn.execute(_t("DELETE FROM model_price WHERE NOT (model = ANY(:m))"), {"m": [p.model for p in body]})
        for p in body:
            await conn.execute(_t("""INSERT INTO model_price (model, label, input_usd_mtok, output_usd_mtok) VALUES (:m, :l, :i, :o)
                                     ON CONFLICT (model) DO UPDATE SET label = EXCLUDED.label, input_usd_mtok = EXCLUDED.input_usd_mtok,
                                         output_usd_mtok = EXCLUDED.output_usd_mtok, updated_at = now()"""),
                               {"m": p.model, "l": p.label, "i": p.input_usd_mtok, "o": p.output_usd_mtok})
        prices = await costs.load_prices(conn)
    return [PriceOut(**p.__dict__) for p in prices]
