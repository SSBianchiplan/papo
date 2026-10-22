"""Trilha das execuções — alimenta o módulo Fluxo e a auditoria."""
from __future__ import annotations

from fastapi import APIRouter, Query

from ..auth import CurrentUser, User
from ..db import rows, scalar, tx
from ..schemas import Run, RunEvent

router = APIRouter(prefix="/api/runs", tags=["execuções"])


@router.get("", response_model=list[Run])
async def latest_runs(limit: int = Query(default=10, ge=1, le=50), user: CurrentUser = User) -> list[Run]:
    async with tx(user.id) as conn:
        rs = await rows(conn, """
            SELECT r.*, coalesce(c.name, a.name, r.agent_name) AS conversation_title
              FROM agent_run r JOIN conversation c ON c.id = r.conversation_id LEFT JOIN agent a ON a.id = c.agent_id
             ORDER BY r.queued_at DESC LIMIT :n""", n=limit)
        out = []
        for r in rs:
            ev = await rows(conn, "SELECT at, kind, payload FROM agent_run_event WHERE run_id = :r ORDER BY id", r=r["id"])
            broken = await scalar(conn, "SELECT count(*) FROM verify_run_chain(:r)", r=r["id"])
            out.append(Run(id=r["id"], conversation_id=r["conversation_id"], conversation_title=r["conversation_title"],
                           agent_name=r["agent_name"], status=r["status"], tier=r["tier"], read_mode=r["read_mode"], model=r["model"],
                           input_tokens=r["input_tokens"], output_tokens=r["output_tokens"], tool_calls=r["tool_calls"],
                           queued_at=r["queued_at"], started_at=r["started_at"], finished_at=r["finished_at"],
                           events=[RunEvent(**e) for e in ev], chain_ok=broken == 0))
    return out
