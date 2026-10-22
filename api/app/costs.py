"""Custos e credenciais do serviço de IA: preços por modelo, orçamento mensal, limite diário e chave em uso."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any, Literal
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncConnection

from . import secretbox
from .config import get_settings
from .db import row, rows

TZ = ZoneInfo("America/Sao_Paulo")       # o dia e o mês do consumo seguem o horário de Brasília


@dataclass(frozen=True)
class Price:
    model: str
    label: str
    input_usd_mtok: float
    output_usd_mtok: float


@dataclass(frozen=True)
class AiConfig:
    key_enc: bytes | None
    key_hint: str | None
    workspace_id: str | None
    monthly_budget_usd: float | None
    alert_pct: int
    daily_token_limit: int | None
    models: dict[str, str | None] | None = None       # quick/default/complex/router → ID escolhido no painel (None = .env)
    models_available: list[str] | None = None
    models_checked_at: datetime | None = None


async def load_prices(conn: AsyncConnection) -> list[Price]:
    rs = await rows(conn, "SELECT model, label, input_usd_mtok, output_usd_mtok FROM model_price ORDER BY output_usd_mtok DESC, model")
    return [Price(r["model"], r["label"], float(r["input_usd_mtok"]), float(r["output_usd_mtok"])) for r in rs]


def price_for(model: str, prices: list[Price]) -> Price | None:
    """Casamento por prefixo, o mais longo vence: claude-haiku-4-5 cobre claude-haiku-4-5-20251001."""
    hits = [p for p in prices if model == p.model or model.startswith(p.model + "-")]
    return max(hits, key=lambda p: len(p.model)) if hits else None


def cost_usd(model: str, input_tokens: int, output_tokens: int, prices: list[Price]) -> float:
    p = price_for(model, prices)
    if not p:
        return 0.0
    return (input_tokens * p.input_usd_mtok + output_tokens * p.output_usd_mtok) / 1_000_000


async def load_ai_config(conn: AsyncConnection) -> AiConfig:
    r = await row(conn, """SELECT anthropic_key_enc, anthropic_key_hint, anthropic_workspace_id, monthly_budget_usd,
                                  alert_pct, daily_token_limit, model_quick, model_default, model_complex, model_router,
                                  models_available, models_checked_at FROM app_config""")
    if not r:
        return AiConfig(None, None, None, None, 80, None)
    budget = r["monthly_budget_usd"]
    return AiConfig(bytes(r["anthropic_key_enc"]) if r["anthropic_key_enc"] else None, r["anthropic_key_hint"], r["anthropic_workspace_id"],
                    float(budget) if isinstance(budget, Decimal | int | float) else None, int(r["alert_pct"]), r["daily_token_limit"],
                    {t: r[f"model_{t}"] for t in TIERS}, list(r["models_available"]) if r["models_available"] else None, r["models_checked_at"])


TIERS = ("quick", "default", "complex", "router")


def model_for(cfg: AiConfig, tier: str) -> str:
    """Modelo de cada nível: o escolhido no painel, senão o do .env."""
    s = get_settings()
    env = {"quick": s.model_quick, "default": s.model_default, "complex": s.model_complex, "router": s.model_router}
    t = tier if tier in env else "default"
    return (cfg.models or {}).get(t) or env[t]


def effective_daily_limit(cfg: AiConfig) -> int:
    return cfg.daily_token_limit if cfg.daily_token_limit is not None else get_settings().daily_token_limit


KeySource = Literal["painel", "servidor", "nenhuma"]


def credentials(cfg: AiConfig) -> tuple[str, str, KeySource]:
    """Chave e workspace em uso. A do painel vence a do .env; o workspace do painel vence o do .env."""
    s = get_settings()
    ws = cfg.workspace_id or s.anthropic_workspace_id
    if cfg.key_enc:
        return secretbox.open_(cfg.key_enc), ws, "painel"
    if s.anthropic_api_key:
        return s.anthropic_api_key, ws, "servidor"
    return "", ws, "nenhuma"


def month_start(now: datetime | None = None) -> datetime:
    n = (now or datetime.now(UTC)).astimezone(TZ)
    return n.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def days_ago(days: int) -> datetime:
    n = datetime.now(UTC).astimezone(TZ).replace(hour=0, minute=0, second=0, microsecond=0)
    return n - timedelta(days=days - 1)


def today() -> date:
    return datetime.now(UTC).astimezone(TZ).date()


async def rollup(conn: AsyncConnection, since: datetime) -> list[dict[str, Any]]:
    """Consumo de todos os usuários (função SECURITY DEFINER; só contagens)."""
    return await rows(conn, "SELECT * FROM papo_usage_rollup(:s)", s=since)


async def month_cost(conn: AsyncConnection, prices: list[Price]) -> float:
    return sum(cost_usd(r["model"], int(r["input_tokens"]), int(r["output_tokens"]), prices) for r in await rollup(conn, month_start()))
