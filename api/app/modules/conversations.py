"""Conversas, mensagens, anexos e cancelamento."""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, File, Query, UploadFile
from fastapi.responses import Response
from sqlalchemy import text

from .. import bus, storage
from ..auth import CurrentUser, User
from ..config import get_settings
from ..db import row, rows, scalar, tx
from ..errors import Conflict, Invalid, NotFound, TooMany
from ..schemas import Conversation, ConversationIn, ConversationPatch, Message, MessageIn, Upload
from .common import STATUS_SQL, messages
from .uploads import IMAGE_MIMES, store_document, store_image

router = APIRouter(prefix="/api", tags=["conversas"])


def busy_key(conversation_id: UUID) -> str:
    return f"papo:busy:{conversation_id}"


async def _conversations(user: CurrentUser, where: str = "TRUE", **params: object) -> list[Conversation]:
    async with tx(user.id) as conn:
        cs = await rows(conn, f"""
            SELECT c.id, c.kind, c.agent_id, c.name, c.emoji, c.color, c.last_activity_at,
                   coalesce((SELECT array_agg(m.agent_id) FROM conversation_member m WHERE m.conversation_id = c.id), '{{}}') AS members,
                   EXISTS (SELECT 1 FROM agent_run r WHERE r.conversation_id = c.id AND r.status IN ('queued','running')) AS active_run,
                   (SELECT m.id FROM message m WHERE m.conversation_id = c.id ORDER BY m.seq DESC LIMIT 1) AS last_id
              FROM conversation c WHERE {where} ORDER BY c.last_activity_at DESC""", **params)
        last_ids = [c["last_id"] for c in cs if c["last_id"]]
        last = {m.id: m for m in (await messages(conn, "m.id = ANY(:ids)", ids=last_ids) if last_ids else [])}
    return [Conversation(id=c["id"], kind=c["kind"], agent_id=c["agent_id"], name=c["name"], emoji=c["emoji"], color=c["color"],
                         members=list(c["members"] or []), last_activity_at=c["last_activity_at"],
                         last_message=last.get(c["last_id"]), active_run=c["active_run"]) for c in cs]


async def _one(user: CurrentUser, cid: UUID) -> Conversation:
    cs = await _conversations(user, "c.id = :id", id=cid)
    if not cs:
        raise NotFound("Conversa não encontrada.")
    return cs[0]


@router.get("/conversations", response_model=list[Conversation])
async def list_conversations(user: CurrentUser = User) -> list[Conversation]:
    return await _conversations(user)


@router.post("/conversations", response_model=Conversation, status_code=201)
async def create_conversation(body: ConversationIn, user: CurrentUser = User) -> Conversation:
    async with tx(user.id) as conn:
        if body.kind == "dm":
            if not body.agent_id:
                raise Invalid("Informe o agente da conversa.")
            cid = await scalar(conn, "SELECT id FROM conversation WHERE kind = 'dm' AND agent_id = :a", a=body.agent_id)
            if not cid:
                cid = await scalar(conn, "INSERT INTO conversation (owner_id, kind, agent_id) VALUES (:o, 'dm', :a) RETURNING id",
                                   o=user.id, a=body.agent_id)
        else:
            if not body.name or not body.members:
                raise Invalid("Grupo precisa de nome e de pelo menos um agente.")
            cid = await scalar(conn, """INSERT INTO conversation (owner_id, kind, name, emoji, color)
                                        VALUES (:o, 'group', :n, :e, :c) RETURNING id""",
                               o=user.id, n=body.name.strip(), e=body.emoji, c=body.color)
            await conn.execute(text("INSERT INTO conversation_member (conversation_id, owner_id, agent_id) VALUES (:c, :o, :a)"),
                               [{"c": cid, "o": user.id, "a": a} for a in dict.fromkeys(body.members)])
            await conn.execute(text("INSERT INTO message (conversation_id, author, body) VALUES (:c, 'system', :b)"),
                               {"c": cid, "b": f"Você criou o grupo {body.name.strip()}"})
    return await _one(user, cid)


@router.patch("/conversations/{cid}", response_model=Conversation)
async def patch_conversation(cid: UUID, body: ConversationPatch, user: CurrentUser = User) -> Conversation:
    async with tx(user.id) as conn:
        kind = await scalar(conn, "SELECT kind FROM conversation WHERE id = :c", c=cid)
        if kind is None:
            raise NotFound("Conversa não encontrada.")
        if kind != "group":
            raise Invalid("Só grupos podem ser editados.")
        if body.name:
            await conn.execute(text("UPDATE conversation SET name = :n WHERE id = :c"), {"n": body.name.strip(), "c": cid})
        if body.members is not None:
            await conn.execute(text("DELETE FROM conversation_member WHERE conversation_id = :c AND NOT (agent_id = ANY(:m))"),
                               {"c": cid, "m": body.members})
            await conn.execute(text("""INSERT INTO conversation_member (conversation_id, owner_id, agent_id) VALUES (:c, :o, :a)
                                       ON CONFLICT DO NOTHING"""), [{"c": cid, "o": user.id, "a": a} for a in dict.fromkeys(body.members)])
    return await _one(user, cid)


@router.delete("/conversations/{cid}", status_code=204, response_model=None)
async def delete_conversation(cid: UUID, user: CurrentUser = User) -> None:
    async with tx(user.id) as conn:
        if await scalar(conn, "SELECT 1 FROM agent_run WHERE conversation_id = :c AND status IN ('queued','running')", c=cid):
            raise Conflict("Há uma resposta em andamento. Interrompa e tente de novo.")
        keys = [r["storage_key"] for r in await rows(conn, "SELECT storage_key FROM document WHERE conversation_id = :c", c=cid)]
        res = await conn.execute(text("DELETE FROM conversation WHERE id = :c"), {"c": cid})
        if res.rowcount == 0:
            raise NotFound("Conversa não encontrada.")
    for k in keys:
        await storage.remove(k)
    await storage.remove_prefix(f"{user.id}/img/{cid}/")


@router.get("/conversations/{cid}/messages", response_model=list[Message])
async def list_messages(cid: UUID, before: int | None = Query(default=None, ge=1), limit: int = Query(default=60, ge=1, le=200),
                        user: CurrentUser = User) -> list[Message]:
    async with tx(user.id) as conn:
        ms = await messages(conn, "m.conversation_id = :c AND (CAST(:b AS bigint) IS NULL OR m.seq < :b) ORDER BY m.seq DESC LIMIT :n",
                            c=cid, b=before, n=limit)
    return list(reversed(ms))


@router.post("/conversations/{cid}/attachments", response_model=Upload, status_code=201)
async def upload_attachment(cid: UUID, file: UploadFile = File(...), user: CurrentUser = User) -> Upload:
    async with tx(user.id) as conn:
        if not await scalar(conn, "SELECT 1 FROM conversation WHERE id = :c", c=cid):
            raise NotFound("Conversa não encontrada.")
    if (file.content_type or "") in IMAGE_MIMES:
        return Upload(kind="image", image_key=await store_image(user.id, cid, file))
    return Upload(kind="document", document=await store_document(user.id, file, conversation_id=cid))


@router.post("/conversations/{cid}/messages", response_model=Message, status_code=201)
async def post_message(cid: UUID, body: MessageIn, user: CurrentUser = User) -> Message:
    s = get_settings()
    if not await bus.rate_ok(user.id, "msg", s.messages_per_minute):
        raise TooMany("Muitas mensagens em pouco tempo. Aguarde um minuto.")
    if not body.body.strip() and not body.document_id and not body.image_key:
        raise Invalid("Mensagem vazia.")
    r = bus.redis()
    if not await r.set(busy_key(cid), "1", nx=True, ex=900):
        raise Conflict("Aguarde a resposta terminar ou interrompa antes de enviar outra mensagem.")
    try:
        async with tx(user.id) as conn:
            if not await scalar(conn, "SELECT 1 FROM conversation WHERE id = :c", c=cid):
                raise NotFound("Conversa não encontrada.")
            if body.document_id and await scalar(conn, "SELECT status FROM document WHERE id = :d", d=body.document_id) == "pending":
                raise Conflict("O arquivo ainda está sendo lido. Envie quando terminar.")
            mid = await scalar(conn, """INSERT INTO message (conversation_id, author, body, document_id, image_key)
                                        VALUES (:c, 'user', :b, :d, :i) RETURNING id""",
                               c=cid, b=body.body.strip(), d=body.document_id, i=body.image_key)
            m = (await messages(conn, "m.id = :i", i=mid))[0]
        await bus.clear_cancel(cid)
        await bus.enqueue("job_respond", str(user.id), str(cid), str(mid))
    except Exception:
        await r.delete(busy_key(cid))
        raise
    await bus.publish(user.id, "message.created", {"conversation_id": cid, "message_id": m.id})
    return m


@router.post("/conversations/{cid}/cancel", status_code=202)
async def cancel(cid: UUID, user: CurrentUser = User) -> dict[str, bool]:
    async with tx(user.id) as conn:
        if not await scalar(conn, "SELECT 1 FROM conversation WHERE id = :c", c=cid):
            raise NotFound("Conversa não encontrada.")
    await bus.request_cancel(cid)
    return {"ok": True}


@router.get("/images/{key:path}", response_class=Response, responses={200: {"content": {"image/jpeg": {}}}})
async def image(key: str, user: CurrentUser = User) -> Response:
    if not key.startswith(f"{user.id}/img/") or ".." in key:
        raise NotFound("Imagem não encontrada.")
    async with tx(user.id) as conn:      # só serve imagem referenciada por mensagem visível ao usuário
        if not await scalar(conn, "SELECT 1 FROM message WHERE image_key = :k LIMIT 1", k=key):
            raise NotFound("Imagem não encontrada.")
    data = await storage.get(key)
    return Response(data, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=86400"})


__all__ = ["router", "busy_key", "STATUS_SQL", "row"]
