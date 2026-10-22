"""Monta o conector de uma fonte a partir do banco (o segredo é decifrado só aqui, dentro do gateway)."""
from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from sqlalchemy import text

from .. import secretbox
from ..config import get_settings
from ..db import row, tx
from .backends import Backend, Local, Remote, Sftp


def local_roots() -> dict[str, str]:
    return dict(i.split("=", 1) for i in get_settings().hubgw_local_roots.split(",") if "=" in i)


async def load(source_id: UUID) -> tuple[dict[str, Any], Backend]:
    async with tx(None) as conn:
        s = await row(conn, "SELECT * FROM hub_source WHERE id = :i AND enabled", i=source_id)
    if not s:
        raise LookupError("fonte não encontrada ou desativada")
    cfg: dict[str, Any] = dict(s["config"] or {})
    secret = secretbox.open_(bytes(s["secret_enc"])) if s["secret_enc"] else ""
    exts = set(s["extensions"])
    if s["kind"] == "local":
        roots = local_roots()
        wanted = cfg.get("roots") or list(roots)
        return s, Local({k: v for k, v in roots.items() if k in wanted}, exts)
    if s["kind"] == "remote":
        return s, Remote(cfg["url"], secret, cfg["cert_pem"], exts)
    return s, Sftp(cfg["host"], int(cfg.get("port", 22)), cfg["user"], secret, cfg.get("root", "."), cfg.get("host_key", ""), exts)


async def remember_host_key(source_id: UUID, host_key: str) -> None:
    async with tx(None) as conn:
        await conn.execute(text("""UPDATE hub_source SET config = config || CAST(:c AS jsonb)
                                    WHERE id = :i AND coalesce(config->>'host_key', '') = ''"""),
                           {"c": json.dumps({"host_key": host_key}), "i": source_id})
