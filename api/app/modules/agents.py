"""Agentes e sua base de arquivos."""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, File, UploadFile
from sqlalchemy import text

from .. import storage
from ..auth import CurrentUser, User
from ..db import row, rows, scalar, tx
from ..errors import Conflict, NotFound
from ..schemas import Agent, AgentIn, AgentPatch, Document
from .common import documents_by_id
from .uploads import store_document

router = APIRouter(prefix="/api/agents", tags=["agentes"])

SELECT = """SELECT a.id, a.name, a.emoji, a.color, a.persona, a.created_at, a.kind,
                   coalesce(f.ativo, false) AS ativo, coalesce(f.nivel, 'M0') AS nivel, f.camada_real AS camada,
                   (SELECT count(*) FROM document d WHERE d.agent_id = a.id) AS documents
              FROM agent a LEFT JOIN agent_ficha f ON f.agent_id = a.id"""


@router.get("", response_model=list[Agent])
async def list_agents(user: CurrentUser = User) -> list[Agent]:
    async with tx(user.id) as conn:
        return [Agent(**a) for a in await rows(conn, SELECT + " ORDER BY a.created_at")]


@router.post("", response_model=Agent, status_code=201)
async def create_agent(body: AgentIn, user: CurrentUser = User) -> Agent:
    async with tx(user.id) as conn:
        aid = await scalar(conn, """INSERT INTO agent (owner_id, name, emoji, color, persona) VALUES (:o, :n, :e, :c, :p)
                                    RETURNING id""", o=user.id, n=body.name.strip(), e=body.emoji, c=body.color, p=body.persona)
        a = await row(conn, SELECT + " WHERE a.id = :i", i=aid)
    assert a
    return Agent(**a)


@router.patch("/{agent_id}", response_model=Agent)
async def patch_agent(agent_id: UUID, body: AgentPatch, user: CurrentUser = User) -> Agent:
    fields = body.model_dump(exclude_none=True)
    async with tx(user.id) as conn:
        if fields:
            sets = ", ".join(f"{k} = :{k}" for k in fields)
            res = await conn.execute(text(f"UPDATE agent SET {sets}, updated_at = now() WHERE id = :id"),
                                     {**{k: (v.strip() if k == "name" else v) for k, v in fields.items()}, "id": agent_id})
            if res.rowcount == 0:
                raise NotFound("Agente não encontrado.")
        a = await row(conn, SELECT + " WHERE a.id = :i", i=agent_id)
    if not a:
        raise NotFound("Agente não encontrado.")
    return Agent(**a)


@router.delete("/{agent_id}", status_code=204, response_model=None)
async def delete_agent(agent_id: UUID, user: CurrentUser = User) -> None:
    async with tx(user.id) as conn:
        if await scalar(conn, """SELECT 1 FROM agent_run r WHERE r.agent_id = :a AND r.status IN ('queued','running') LIMIT 1""", a=agent_id):
            raise Conflict("O agente está respondendo agora. Interrompa a resposta e tente de novo.")
        keys = [r["storage_key"] for r in await rows(conn, """
            SELECT d.storage_key FROM document d
             WHERE d.agent_id = :a OR d.conversation_id IN (SELECT id FROM conversation WHERE kind = 'dm' AND agent_id = :a)""", a=agent_id)]
        dms = [r["id"] for r in await rows(conn, "SELECT id FROM conversation WHERE kind = 'dm' AND agent_id = :a", a=agent_id)]
        res = await conn.execute(text("DELETE FROM agent WHERE id = :a"), {"a": agent_id})
        if res.rowcount == 0:
            raise NotFound("Agente não encontrado.")
    for k in keys:
        await storage.remove(k)
    for c in dms:
        await storage.remove_prefix(f"{user.id}/img/{c}/")


@router.get("/{agent_id}/documents", response_model=list[Document])
async def agent_documents(agent_id: UUID, user: CurrentUser = User) -> list[Document]:
    async with tx(user.id) as conn:
        ids = [r["id"] for r in await rows(conn, "SELECT id FROM document WHERE agent_id = :a ORDER BY created_at", a=agent_id)]
        docs = await documents_by_id(conn, ids)
    return [docs[i] for i in ids]


@router.post("/{agent_id}/documents", response_model=Document, status_code=201)
async def upload_agent_document(agent_id: UUID, file: UploadFile = File(...), user: CurrentUser = User) -> Document:
    async with tx(user.id) as conn:
        if not await scalar(conn, "SELECT 1 FROM agent WHERE id = :a", a=agent_id):
            raise NotFound("Agente não encontrado.")
    return await store_document(user.id, file, agent_id=agent_id)


@router.delete("/{agent_id}/documents/{document_id}", status_code=204, response_model=None)
async def delete_agent_document(agent_id: UUID, document_id: UUID, user: CurrentUser = User) -> None:
    async with tx(user.id) as conn:
        key = await scalar(conn, "DELETE FROM document WHERE id = :d AND agent_id = :a RETURNING storage_key", d=document_id, a=agent_id)
    if not key:
        raise NotFound("Arquivo não encontrado.")
    await storage.remove(key)
