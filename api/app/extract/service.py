"""Processa um documento enviado: baixa do storage, extrai e grava partes/abas. Roda no worker."""
from __future__ import annotations

import asyncio
import json
import logging
from uuid import UUID

from sqlalchemy import text

from .. import bus, storage
from ..db import row, tx
from .parsers import Extracted, parse

log = logging.getLogger("papo.extract")
BATCH = 1000


async def process_document(owner: UUID, document_id: UUID) -> None:
    async with tx(owner) as conn:
        d = await row(conn, "SELECT id, filename, mime, storage_key, status, agent_id, conversation_id FROM document WHERE id = :d",
                      d=document_id)
    if not d or d["status"] != "pending":
        return
    status, note, pages = "failed", None, None
    try:
        data = await storage.get(d["storage_key"])
        ex: Extracted = await asyncio.to_thread(parse, data, d["filename"], d["mime"])
        pages, note = ex.pages, ex.note
        async with tx(owner) as conn:
            for i in range(0, len(ex.parts), BATCH):
                batch = [{"d": document_id, "o": i + j + 1, "l": lab[:60], "b": body[:40000]}
                         for j, (lab, body) in enumerate(ex.parts[i:i + BATCH])]
                await conn.execute(text("INSERT INTO doc_chunk (document_id, ord, label, body) VALUES (:d, :o, :l, :b)"), batch)
            for si, sh in enumerate(ex.sheets, start=1):
                await conn.execute(text("""INSERT INTO doc_sheet (document_id, ord, name, columns, total_rows, stored_rows)
                                           VALUES (:d, :o, :n, CAST(:c AS jsonb), :t, :s)"""),
                                   {"d": document_id, "o": si, "n": sh.name, "c": json.dumps(sh.columns, ensure_ascii=False),
                                    "t": max(sh.total, len(sh.rows)), "s": len(sh.rows)})
                for i in range(0, len(sh.rows), BATCH):
                    await conn.execute(text("INSERT INTO doc_row (document_id, sheet_ord, ord, cells) VALUES (:d, :s, :o, CAST(:c AS jsonb))"),
                                       [{"d": document_id, "s": si, "o": i + j + 1, "c": json.dumps(r, ensure_ascii=False, default=str)}
                                        for j, r in enumerate(sh.rows[i:i + BATCH])])
            status = "ready" if ex.readable else "unreadable"
            await conn.execute(text("UPDATE document SET status = :s, pages = :p, note = :n, processed_at = now() WHERE id = :d"),
                               {"s": status, "p": pages, "n": (note or None) and note[:500], "d": document_id})
    except Exception as e:  # noqa: BLE001 — arquivo corrompido/protegido não pode travar a fila
        log.exception("falha ao ler %s", document_id)
        note = "Não foi possível ler o arquivo. Verifique se não está corrompido ou protegido por senha." \
            if "senha" not in str(e) else "PDF protegido por senha."
        async with tx(owner) as conn:
            await conn.execute(text("""UPDATE document SET status = 'failed', note = :n, processed_at = now()
                                        WHERE id = :d AND status = 'pending'"""), {"n": note, "d": document_id})
        status = "failed"
    await bus.publish(owner, "document.updated", {"document_id": document_id, "status": status,
                                                  "agent_id": d["agent_id"], "conversation_id": d["conversation_id"]})
