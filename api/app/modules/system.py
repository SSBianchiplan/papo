"""Estado ao vivo das peças do fluxo (para o desenho em Configuração → Fluxo do sistema). Só administradores."""
from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx
from fastapi import APIRouter

from .. import bus, costs, storage
from ..auth import Admin, CurrentUser
from ..config import get_settings
from ..db import rows, scalar, tx

router = APIRouter(prefix="/api/admin", tags=["administração"])


async def _timed(fn: Any) -> dict[str, Any]:
    t = time.perf_counter()
    try:
        extra = await asyncio.wait_for(fn(), timeout=4)
        return {"ok": True, "ms": round((time.perf_counter() - t) * 1000), **(extra or {})}
    except Exception as e:  # noqa: BLE001 — o painel mostra a falha, não derruba
        return {"ok": False, "ms": round((time.perf_counter() - t) * 1000), "error": str(e)[:200]}


@router.get("/system")
async def system(user: CurrentUser = Admin) -> dict[str, Any]:
    s = get_settings()

    async def db() -> dict[str, Any]:
        async with tx(user.id) as conn:
            return {"version": str(await scalar(conn, "SHOW server_version"))}

    async def redis() -> dict[str, Any]:
        r = bus.redis()
        await r.ping()
        return {"queue": int(await r.zcard("arq:queue")), "worker_seen": bool(await r.exists("arq:queue:health-check"))}

    async def store() -> dict[str, Any]:
        b = s.s3_bucket
        ok = await asyncio.to_thread(storage.client().bucket_exists, b) if not s.storage_dir else True
        return {"bucket": b, "exists": ok}

    async def hubgw() -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=3) as c:
            (await c.get(f"{s.hubgw_url}/healthz")).raise_for_status()
        return {}

    checks = dict(zip(["postgres", "redis", "storage", "hubgw"],
                      await asyncio.gather(_timed(db), _timed(redis), _timed(store), _timed(hubgw)), strict=True))
    async with tx(user.id) as conn:
        ai = await costs.load_ai_config(conn)
        sources = await rows(conn, """SELECT name, label, kind, enabled, status, last_error, last_scan_at, file_count
                                        FROM hub_source ORDER BY label""")
        runs = await rows(conn, """SELECT status, count(*) AS n, avg(extract(epoch FROM finished_at - started_at)) AS secs
                                     FROM agent_run WHERE queued_at > now() - interval '24 hours' GROUP BY status""")
        docs = await rows(conn, """SELECT status, count(*) AS n FROM document WHERE created_at > now() - interval '24 hours' GROUP BY status""")
    _, ws, source = costs.credentials(ai)
    return {
        "checks": checks,
        "ai": {"key_source": source, "workspace": bool(ws), "models_checked_at": ai.models_checked_at,
               "models": {t: costs.model_for(ai, t) for t in costs.TIERS}},
        "hub_sources": [dict(r) for r in sources],
        "runs_24h": {r["status"]: {"n": int(r["n"]), "avg_s": round(float(r["secs"]), 1) if r["secs"] is not None else None} for r in runs},
        "docs_24h": {r["status"]: int(r["n"]) for r in docs},
    }
