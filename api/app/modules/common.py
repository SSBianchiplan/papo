"""Consultas compartilhadas entre os módulos (serialização de mensagens e documentos)."""
from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncConnection

from ..db import rows
from ..schemas import Document, Message, SheetOut

STATUS_SQL = """(SELECT r.state FROM message_receipt r WHERE r.message_id = m.id
                 ORDER BY CASE r.state WHEN 'read' THEN 3 WHEN 'delivered' THEN 2 ELSE 1 END DESC LIMIT 1)"""


async def documents_by_id(conn: AsyncConnection, ids: list[UUID]) -> dict[UUID, Document]:
    if not ids:
        return {}
    docs = await rows(conn, """SELECT d.*, (SELECT count(*) FROM doc_chunk c WHERE c.document_id = d.id) AS parts,
                                      EXISTS (SELECT 1 FROM document_purge p WHERE p.document_id = d.id) AS purged
                               FROM document d WHERE d.id = ANY(:ids)""", ids=ids)
    sheets = await rows(conn, "SELECT document_id, name, columns, stored_rows, total_rows FROM doc_sheet WHERE document_id = ANY(:ids) ORDER BY ord",
                        ids=ids)
    out: dict[UUID, Document] = {}
    for d in docs:
        out[d["id"]] = Document(**{k: d[k] for k in Document.model_fields if k in d and k != "sheets"},
                                sheets=[SheetOut(name=s["name"], columns=list(s["columns"]), stored_rows=s["stored_rows"],
                                                 total_rows=s["total_rows"]) for s in sheets if s["document_id"] == d["id"]])
    return out


def to_message(m: dict[str, Any], docs: dict[UUID, Document]) -> Message:
    return Message(
        id=m["id"], conversation_id=m["conversation_id"], seq=m["seq"], author=m["author"], agent_id=m["agent_id"],
        agent_name=m["agent_name"], body=m["body"], document=docs.get(m["document_id"]) if m["document_id"] else None,
        image_key=m["image_key"], run_id=m["run_id"], sources=list(m["sources"] or []), steps=list(m["steps"] or []),
        error=m["error"], status=m.get("status"), created_at=m["created_at"], card=m.get("card"))


async def messages(conn: AsyncConnection, where: str, **params: Any) -> list[Message]:
    ms = await rows(conn, f"SELECT m.*, {STATUS_SQL} AS status FROM message m WHERE {where}", **params)
    docs = await documents_by_id(conn, [m["document_id"] for m in ms if m["document_id"]])
    return [to_message(m, docs) for m in ms]
