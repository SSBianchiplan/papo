"""Consumo e custo de IA: cada usuário vê o seu; o administrador vê o de todos."""
from __future__ import annotations

from collections import defaultdict
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Query

from .. import costs
from ..auth import Admin, CurrentUser, User
from ..db import rows, tx
from ..schemas import AdminUsage, PriceOut, Usage, UsageDay, UsageModel, UsageUser

router = APIRouter(prefix="/api", tags=["consumo"])


def _summarize(data: list[dict[str, Any]], prices: list[costs.Price], days: int) -> dict[str, Any]:
    by_day: dict[Any, list[float]] = defaultdict(lambda: [0, 0, 0.0])
    by_model: dict[str, list[float]] = defaultdict(lambda: [0, 0, 0.0])
    today, month = costs.today(), costs.month_start().date()
    today_tokens, month_cost = 0, 0.0
    for r in data:
        i, o = int(r["input_tokens"]), int(r["output_tokens"])
        c = costs.cost_usd(r["model"], i, o, prices)
        if r["day"] >= month:
            month_cost += c
        if r["day"] == today:
            today_tokens += i + o
        if r["day"] < costs.days_ago(days).date():
            continue
        d, m = by_day[r["day"]], by_model[r["model"]]
        d[0] += i; d[1] += o; d[2] += c          # noqa: E702
        m[0] += i; m[1] += o; m[2] += c          # noqa: E702
    start = costs.days_ago(days).date()
    series = []
    for n in range(days):
        day = start.fromordinal(start.toordinal() + n)
        v = by_day.get(day, [0, 0, 0.0])
        series.append(UsageDay(day=day, input_tokens=int(v[0]), output_tokens=int(v[1]), cost_usd=round(v[2], 6)))
    models = []
    for model, v in sorted(by_model.items(), key=lambda kv: -kv[1][2]):
        p = costs.price_for(model, prices)
        models.append(UsageModel(model=model, label=p.label if p else model, input_tokens=int(v[0]), output_tokens=int(v[1]), cost_usd=round(v[2], 6)))
    return {"days": series, "by_model": models, "total_tokens": sum(int(m.input_tokens + m.output_tokens) for m in models),
            "total_cost_usd": round(sum(m.cost_usd for m in models), 6), "today_tokens": today_tokens, "month_cost_usd": round(month_cost, 6),
            "prices": [PriceOut(**p.__dict__) for p in prices]}


async def _own_rows(conn: Any, uid: UUID, since: Any) -> list[dict[str, Any]]:
    return await rows(conn, """SELECT (at AT TIME ZONE 'America/Sao_Paulo')::date AS day, model,
                                      sum(input_tokens) AS input_tokens, sum(output_tokens) AS output_tokens
                                 FROM usage_event WHERE user_id = :u AND at >= :s GROUP BY 1, 2""", u=uid, s=since)


@router.get("/usage", response_model=Usage)
async def my_usage(days: int = Query(default=30, ge=1, le=92), user: CurrentUser = User) -> Usage:
    since = min(costs.days_ago(days), costs.month_start())
    async with tx(user.id) as conn:
        prices = await costs.load_prices(conn)
        ai = await costs.load_ai_config(conn)
        data = await _own_rows(conn, user.id, since)
    return Usage(**_summarize(data, prices, days), daily_limit=costs.effective_daily_limit(ai))


@router.get("/admin/usage", response_model=AdminUsage)
async def all_usage(days: int = Query(default=30, ge=1, le=92), user: CurrentUser = Admin) -> AdminUsage:
    since = min(costs.days_ago(days), costs.month_start())
    async with tx(user.id) as conn:
        prices = await costs.load_prices(conn)
        ai = await costs.load_ai_config(conn)
        data = await costs.rollup(conn, since)
    window = costs.days_ago(days).date()
    users: dict[UUID, dict[str, Any]] = {}
    for r in data:
        u = users.setdefault(r["user_id"], {"user_id": r["user_id"], "name": r["user_name"] or r["email"] or "—", "email": r["email"],
                                            "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0, "today_tokens": 0})
        i, o = int(r["input_tokens"]), int(r["output_tokens"])
        if r["day"] == costs.today():
            u["today_tokens"] += i + o
        if r["day"] >= window:
            u["input_tokens"] += i
            u["output_tokens"] += o
            u["cost_usd"] += costs.cost_usd(r["model"], i, o, prices)
    summary = _summarize(data, prices, days)
    by_user = sorted((UsageUser(**{**u, "cost_usd": round(u["cost_usd"], 6)}) for u in users.values()), key=lambda u: -u.cost_usd)
    return AdminUsage(**summary, daily_limit=costs.effective_daily_limit(ai), by_user=by_user,
                      month_cost_all_usd=summary["month_cost_usd"], monthly_budget_usd=ai.monthly_budget_usd, alert_pct=ai.alert_pct)
