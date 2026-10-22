"""Conta: perfil, preferências, exportação e exclusão (LGPD)."""
from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter
from fastapi.responses import Response

from .. import costs, storage
from ..agent.engine import load_config, usage_today
from ..auth import CurrentUser, User
from ..db import row, rows, tx
from ..schemas import Me, UserConfig

router = APIRouter(prefix="/api", tags=["conta"])


@router.get("/me", response_model=Me)
async def me(user: CurrentUser = User) -> Me:
    async with tx(user.id) as conn:
        u = await row(conn, "SELECT id, display_name, email FROM app_user WHERE id = :u", u=user.id)
        cfg = await load_config(conn, user.id)
        used = await usage_today(conn, user.id)
        ai = await costs.load_ai_config(conn)
        prices = await costs.load_prices(conn)
    assert u
    tiers = {}
    for t in ("quick", "default", "complex"):
        m = costs.model_for(ai, t)
        p = costs.price_for(m, prices)
        tiers[t] = p.label if p else m
    return Me(id=u["id"], name=u["display_name"], email=u["email"], settings=cfg, usage_today=used,
              daily_limit=costs.effective_daily_limit(ai), is_admin=user.is_admin, is_master=user.is_master, tiers=tiers)


@router.put("/settings", response_model=UserConfig)
async def put_settings(body: UserConfig, user: CurrentUser = User) -> UserConfig:
    async with tx(user.id) as conn:
        await conn.execute(_t("""INSERT INTO user_settings (user_id, data, updated_at) VALUES (:u, CAST(:d AS jsonb), now())
                                 ON CONFLICT (user_id) DO UPDATE SET data = EXCLUDED.data, updated_at = now()"""),
                           {"u": user.id, "d": body.model_dump_json()})
    return body


@router.get("/export", response_class=Response, responses={200: {"content": {"application/json": {}}}})
async def export(user: CurrentUser = User) -> Response:
    async with tx(user.id) as conn:
        data: dict[str, Any] = {
            "app": "papo", "version": 1,
            "agents": await rows(conn, "SELECT id, name, emoji, color, persona, created_at FROM agent ORDER BY created_at"),
            "conversations": await rows(conn, "SELECT id, kind, agent_id, name, emoji, color, created_at FROM conversation"),
            "members": await rows(conn, "SELECT conversation_id, agent_id FROM conversation_member"),
            "messages": await rows(conn, """SELECT conversation_id, seq, author, agent_name, body, sources, error, created_at
                                            FROM message ORDER BY conversation_id, seq"""),
            "documents": await rows(conn, "SELECT id, filename, kind, status, size_bytes, sha256, agent_id, conversation_id, created_at FROM document"),
            "settings": (await load_config(conn, user.id)).model_dump(),
        }
    body = json.dumps(data, ensure_ascii=False, default=str, indent=1)
    return Response(body, media_type="application/json",
                    headers={"Content-Disposition": 'attachment; filename="papo-export.json"'})


@router.delete("/me", status_code=204, response_model=None)
async def delete_account(user: CurrentUser = User) -> None:
    async with tx(user.id) as conn:
        await conn.execute(_t("DELETE FROM app_user WHERE id = :u"), {"u": user.id})
    await storage.remove_prefix(f"{user.id}/")


def _t(sql: str) -> Any:
    from sqlalchemy import text
    return text(sql)
