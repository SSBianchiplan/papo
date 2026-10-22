"""Skills: biblioteca de pacotes de instruções; ativação por agente e por conversa."""
from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, File, UploadFile
from sqlalchemy import text

from ..auth import CurrentUser, User
from ..db import row, rows, scalar, tx
from ..errors import DomainError, Invalid, NotFound
from ..schemas import SkillDetail, SkillIds, SkillOut, SkillPatch, SkillUploadResult
from ..skills import MAX_ZIP, parse_upload

router = APIRouter(prefix="/api", tags=["skills"])

SELECT = """
  SELECT s.id, s.name, s.description, s.version, s.enabled, s.shared, s.size_bytes, s.updated_at, s.owner_id = :me AS mine,
         (SELECT count(*) FROM skill_file f WHERE f.skill_id = s.id) AS files,
         (SELECT count(*) FROM agent_skill a WHERE a.skill_id = s.id) AS agents,
         (SELECT count(*) FROM conversation_skill c WHERE c.skill_id = s.id) AS conversations
    FROM skill s
"""


class Forbidden(DomainError):
    status = 403
    code = "proibido"


@router.get("/skills", response_model=list[SkillOut])
async def list_skills(user: CurrentUser = User) -> list[SkillOut]:
    async with tx(user.id) as conn:
        return [SkillOut(**r) for r in await rows(conn, SELECT + " ORDER BY s.owner_id <> :me, lower(s.name)", me=user.id)]


async def import_skills(conn: Any, owner: UUID, filename: str, data: bytes) -> SkillUploadResult:
    """Lê o pacote e grava cada skill: nome novo cria; nome existente vira versão nova (mantém ativação e vínculos)."""
    parsed = parse_upload(filename, data)
    created, updated, ids = [], [], []
    for sk in parsed:
        size = len(sk.body.encode()) + sum(len(v.encode()) for v in sk.files.values())
        cur = await row(conn, "SELECT id FROM skill WHERE owner_id = :o AND lower(name) = lower(:n)", o=owner, n=sk.name)
        if cur:
            sid = cur["id"]
            await conn.execute(text("""UPDATE skill SET description = :d, body = :b, version = version + 1, size_bytes = :s, updated_at = now()
                                        WHERE id = :i"""), {"d": sk.description, "b": sk.body, "s": size, "i": sid})
            await conn.execute(text("DELETE FROM skill_file WHERE skill_id = :i"), {"i": sid})
            updated.append(sk.name)
        else:
            sid = await scalar(conn, """INSERT INTO skill (owner_id, name, description, body, size_bytes)
                                        VALUES (:o, :n, :d, :b, :s) RETURNING id""", o=owner, n=sk.name, d=sk.description, b=sk.body, s=size)
            created.append(sk.name)
        ids.append(sid)
        for path, body in sk.files.items():
            await conn.execute(text("INSERT INTO skill_file (skill_id, path, body) VALUES (:i, :p, :b)"), {"i": sid, "p": path, "b": body})
    return SkillUploadResult(created=created, updated=updated, ids=ids)


@router.post("/skills", response_model=SkillUploadResult, status_code=201)
async def upload_skills(file: UploadFile = File(...), user: CurrentUser = User) -> SkillUploadResult:
    data = await file.read(MAX_ZIP + 1)
    if not data:
        raise Invalid("Arquivo vazio.")
    async with tx(user.id) as conn:
        return await import_skills(conn, user.id, file.filename or "skill.md", data)


@router.post("/documents/{document_id}/as-skill", response_model=SkillUploadResult)
async def document_as_skill(document_id: UUID, user: CurrentUser = User) -> SkillUploadResult:
    """Converte um .skill (ou SKILL.md) que entrou como arquivo comum: importa e ativa onde ele estava.
    Na base de um agente, o arquivo sai da base; numa conversa, o anexo fica (a mensagem é imutável)."""
    from .. import storage

    async with tx(user.id) as conn:
        d = await row(conn, """SELECT id, filename, storage_key, agent_id, conversation_id,
                                      EXISTS (SELECT 1 FROM document_purge p WHERE p.document_id = document.id) AS purged
                                 FROM document WHERE id = :d""", d=document_id)
    if not d:
        raise NotFound("Arquivo não encontrado.")
    if d["purged"]:
        raise Invalid("Esse arquivo já foi removido.")
    data = await storage.get(d["storage_key"])
    name = d["filename"] if d["filename"].lower().endswith((".skill", ".zip", ".md", ".markdown")) else f"{d['filename']}.skill"
    async with tx(user.id) as conn:
        res = await import_skills(conn, user.id, name, data)
        table, col, target = ("agent_skill", "agent_id", d["agent_id"]) if d["agent_id"] else ("conversation_skill", "conversation_id", d["conversation_id"])
        for sid in res.ids:
            await conn.execute(text(f"INSERT INTO {table} (owner_id, {col}, skill_id) VALUES (:o, :t, :s) ON CONFLICT DO NOTHING"),
                               {"o": user.id, "t": target, "s": sid})
        if d["agent_id"]:
            await conn.execute(text("DELETE FROM document WHERE id = :d"), {"d": document_id})
    if d["agent_id"]:
        await storage.remove(d["storage_key"])
    return res


async def _visible(conn: Any, me: UUID, sid: UUID) -> dict[str, Any]:
    r = await row(conn, SELECT + " WHERE s.id = :i", me=me, i=sid)
    if not r:
        raise NotFound("Skill não encontrada.")
    return r


@router.get("/skills/{skill_id}", response_model=SkillDetail)
async def get_skill(skill_id: UUID, user: CurrentUser = User) -> SkillDetail:
    async with tx(user.id) as conn:
        r = await _visible(conn, user.id, skill_id)
        body = await scalar(conn, "SELECT body FROM skill WHERE id = :i", i=skill_id)
        paths = [f["path"] for f in await rows(conn, "SELECT path FROM skill_file WHERE skill_id = :i ORDER BY path", i=skill_id)]
    return SkillDetail(**r, body=body, file_paths=paths)


@router.patch("/skills/{skill_id}", response_model=SkillOut)
async def patch_skill(skill_id: UUID, body: SkillPatch, user: CurrentUser = User) -> SkillOut:
    async with tx(user.id) as conn:
        r = await _visible(conn, user.id, skill_id)
        if not r["mine"]:
            raise Forbidden("Esta skill foi compartilhada por outra pessoa; só ela pode alterá-la.")
        if body.shared is not None and not user.is_admin:
            raise Forbidden("Só administradores compartilham skills com todos.")
        await conn.execute(text("""UPDATE skill SET enabled = coalesce(:e, enabled), shared = coalesce(:s, shared), updated_at = now()
                                    WHERE id = :i"""), {"e": body.enabled, "s": body.shared, "i": skill_id})
        return SkillOut(**await _visible(conn, user.id, skill_id))


@router.delete("/skills/{skill_id}", status_code=204, response_model=None)
async def delete_skill(skill_id: UUID, user: CurrentUser = User) -> None:
    async with tx(user.id) as conn:
        if not (await _visible(conn, user.id, skill_id))["mine"]:
            raise Forbidden("Esta skill foi compartilhada por outra pessoa; só ela pode apagá-la.")
        await conn.execute(text("DELETE FROM skill WHERE id = :i"), {"i": skill_id})


async def _set_links(conn: Any, me: UUID, table: str, col: str, target: UUID, ids: list[UUID]) -> list[UUID]:
    visible = {r["id"] for r in await rows(conn, "SELECT id FROM skill WHERE id = ANY(:ids)", ids=ids)} if ids else set()
    missing = [str(i) for i in ids if i not in visible]
    if missing:
        raise NotFound("Skill não encontrada: " + ", ".join(missing))
    await conn.execute(text(f"DELETE FROM {table} WHERE {col} = :t"), {"t": target})
    for i in dict.fromkeys(ids):
        await conn.execute(text(f"INSERT INTO {table} (owner_id, {col}, skill_id) VALUES (:o, :t, :s)"), {"o": me, "t": target, "s": i})
    return list(dict.fromkeys(ids))


@router.get("/agents/{agent_id}/skills", response_model=SkillIds)
async def agent_skills(agent_id: UUID, user: CurrentUser = User) -> SkillIds:
    async with tx(user.id) as conn:
        return SkillIds(skill_ids=[r["skill_id"] for r in await rows(conn, "SELECT skill_id FROM agent_skill WHERE agent_id = :a", a=agent_id)])


@router.put("/agents/{agent_id}/skills", response_model=SkillIds)
async def put_agent_skills(agent_id: UUID, body: SkillIds, user: CurrentUser = User) -> SkillIds:
    async with tx(user.id) as conn:
        if not await scalar(conn, "SELECT 1 FROM agent WHERE id = :a", a=agent_id):
            raise NotFound("Agente não encontrado.")
        return SkillIds(skill_ids=await _set_links(conn, user.id, "agent_skill", "agent_id", agent_id, body.skill_ids))


@router.get("/conversations/{cid}/skills", response_model=SkillIds)
async def conversation_skills(cid: UUID, user: CurrentUser = User) -> SkillIds:
    async with tx(user.id) as conn:
        return SkillIds(skill_ids=[r["skill_id"] for r in await rows(conn, "SELECT skill_id FROM conversation_skill WHERE conversation_id = :c", c=cid)])


@router.put("/conversations/{cid}/skills", response_model=SkillIds)
async def put_conversation_skills(cid: UUID, body: SkillIds, user: CurrentUser = User) -> SkillIds:
    async with tx(user.id) as conn:
        if not await scalar(conn, "SELECT 1 FROM conversation WHERE id = :c", c=cid):
            raise NotFound("Conversa não encontrada.")
        return SkillIds(skill_ids=await _set_links(conn, user.id, "conversation_skill", "conversation_id", cid, body.skill_ids))

