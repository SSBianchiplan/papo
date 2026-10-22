"""Gerenciador de arquivos: o que o usuário enviou ou os agentes geraram, quanto ocupa, o que está com problema ou duplicado.

Arquivo da base de um agente é apagado de vez. Anexo de conversa está preso a uma mensagem (append-only, INV-MSG-005):
nesse caso o gerenciador libera o espaço (tira o arquivo do storage e o índice do banco) e registra em document_purge;
a mensagem continua e o balão mostra "arquivo removido".
"""
from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Query
from fastapi.responses import Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from .. import storage
from ..auth import Admin, CurrentUser, User
from ..db import row, rows, scalar, tx
from ..errors import DomainError, NotFound
from ..schemas import ManagedDocument, PreviewOut, SheetOut, StorageGroup, StorageQuotaIn, StorageStats

router = APIRouter(prefix="/api", tags=["arquivos"])

KIND_LABEL = {"pdf": "PDF", "docx": "Documentos (Word, PowerPoint, ODF, RTF, EPUB, zip)", "table": "Planilhas",
              "text": "Texto, HTML, Markdown, e-mail e código", "other": "Outros"}


class Gone(DomainError):
    status = 410
    code = "removido"


LIST_SQL = """
  SELECT d.*, (SELECT count(*) FROM doc_chunk c WHERE c.document_id = d.id) AS parts,
         (p.document_id IS NOT NULL) AS purged,
         CASE WHEN d.agent_id IS NOT NULL THEN 'agente' ELSE 'conversa' END AS place,
         coalesce(d.agent_id, d.conversation_id) AS place_id,
         coalesce(a.name, c.name, ca.name, 'Conversa') AS place_name,
         (SELECT count(*) FROM document o WHERE o.sha256 = d.sha256 AND o.id <> d.id
             AND NOT EXISTS (SELECT 1 FROM document_purge op WHERE op.document_id = o.id)) AS duplicates
    FROM document d
    LEFT JOIN document_purge p ON p.document_id = d.id
    LEFT JOIN agent a ON a.id = d.agent_id
    LEFT JOIN conversation c ON c.id = d.conversation_id
    LEFT JOIN agent ca ON ca.id = c.agent_id
"""


async def _managed(conn: AsyncConnection, where: str = "TRUE", **params: Any) -> list[ManagedDocument]:
    ds = await rows(conn, f"{LIST_SQL} WHERE {where} ORDER BY d.created_at DESC LIMIT 1000", **params)
    if not ds:
        return []
    sheets = await rows(conn, "SELECT document_id, name, columns, stored_rows, total_rows FROM doc_sheet WHERE document_id = ANY(:ids) ORDER BY ord",
                        ids=[d["id"] for d in ds])
    out = []
    for d in ds:
        fields = {k: d[k] for k in ManagedDocument.model_fields if k in d and k != "sheets"}
        out.append(ManagedDocument(**fields, sheets=[SheetOut(name=s["name"], columns=list(s["columns"]), stored_rows=s["stored_rows"],
                                                              total_rows=s["total_rows"]) for s in sheets if s["document_id"] == d["id"]]))
    return out


@router.get("/documents", response_model=list[ManagedDocument])
async def list_documents(q: str | None = Query(default=None, max_length=120),
                         place: Literal["todos", "agente", "conversa"] = "todos",
                         origin: Literal["todos", "upload", "agent"] = "todos",
                         only: Literal["todos", "problemas", "duplicados", "removidos"] = "todos",
                         user: CurrentUser = User) -> list[ManagedDocument]:
    cond, params = ["TRUE"], {}
    if q:
        cond.append("f_unaccent(lower(d.filename)) LIKE '%' || f_unaccent(lower(:q)) || '%'")
        params["q"] = q
    if place == "agente":
        cond.append("d.agent_id IS NOT NULL")
    elif place == "conversa":
        cond.append("d.conversation_id IS NOT NULL")
    if origin != "todos":
        cond.append("d.origin = :origin")
        params["origin"] = origin
    if only == "problemas":
        cond.append("d.status IN ('failed','unreadable') AND p.document_id IS NULL")
    elif only == "removidos":
        cond.append("p.document_id IS NOT NULL")
    async with tx(user.id) as conn:
        docs = await _managed(conn, " AND ".join(cond), **params)
    if only == "duplicados":
        docs = [d for d in docs if d.duplicates > 0 and not d.purged]
    return docs


async def quota_bytes(conn: AsyncConnection) -> int | None:
    mb = await scalar(conn, "SELECT storage_quota_mb FROM app_config")
    return int(mb) * 1024 * 1024 if mb else None


async def used_bytes(conn: AsyncConnection) -> int:
    return int(await scalar(conn, """SELECT coalesce(sum(size_bytes), 0) FROM document d
                                      WHERE NOT EXISTS (SELECT 1 FROM document_purge p WHERE p.document_id = d.id)"""))


@router.get("/documents/stats", response_model=StorageStats)
async def stats(user: CurrentUser = User) -> StorageStats:
    async with tx(user.id) as conn:
        live = "NOT EXISTS (SELECT 1 FROM document_purge p WHERE p.document_id = d.id)"
        tot = await row(conn, f"SELECT count(*) AS n, coalesce(sum(size_bytes), 0) AS b FROM document d WHERE {live}")
        kinds = await rows(conn, f"SELECT kind AS k, count(*) AS n, sum(size_bytes) AS b FROM document d WHERE {live} GROUP BY 1 ORDER BY 3 DESC")
        places = await rows(conn, f"""SELECT CASE WHEN agent_id IS NOT NULL THEN 'agente' WHEN origin = 'agent' THEN 'gerado' ELSE 'conversa' END AS k,
                                             count(*) AS n, sum(size_bytes) AS b FROM document d WHERE {live} GROUP BY 1 ORDER BY 3 DESC""")
        problems = await scalar(conn, f"SELECT count(*) FROM document d WHERE {live} AND status IN ('failed','unreadable')")
        dup = await row(conn, f"""SELECT count(*) AS g, coalesce(sum(extra), 0) AS b FROM (
                                     SELECT sha256, (count(*) - 1) * max(size_bytes) AS extra FROM document d WHERE {live}
                                      GROUP BY sha256 HAVING count(*) > 1) x""")
        freed = await scalar(conn, "SELECT coalesce(sum(bytes_freed), 0) FROM document_purge")
        quota = await quota_bytes(conn)
    assert tot and dup
    place_label = {"agente": "Base dos agentes", "conversa": "Enviados nas conversas", "gerado": "Gerados pelos agentes"}
    return StorageStats(files=int(tot["n"]), bytes=int(tot["b"]), quota_bytes=quota, freed_bytes=int(freed),
                        by_kind=[StorageGroup(key=k["k"], label=KIND_LABEL.get(k["k"], k["k"]), files=int(k["n"]), bytes=int(k["b"])) for k in kinds],
                        by_place=[StorageGroup(key=k["k"], label=place_label[k["k"]], files=int(k["n"]), bytes=int(k["b"])) for k in places],
                        problems=int(problems), duplicate_groups=int(dup["g"]), duplicate_bytes=int(dup["b"]))


@router.get("/documents/{document_id}/file", response_class=Response, responses={200: {"content": {"application/octet-stream": {}}}})
async def download(document_id: UUID, user: CurrentUser = User) -> Response:
    async with tx(user.id) as conn:
        d = await row(conn, """SELECT d.filename, d.mime, d.storage_key, EXISTS (SELECT 1 FROM document_purge p WHERE p.document_id = d.id) AS purged
                                 FROM document d WHERE d.id = :d""", d=document_id)
    if not d:
        raise NotFound("Arquivo não encontrado.")
    if d["purged"]:
        raise Gone("Este arquivo foi removido para liberar espaço.")
    data = await storage.get(d["storage_key"])
    name = d["filename"].replace('"', "")
    # sempre como anexo e em sandbox: um HTML enviado por alguém nunca roda no domínio do app
    return Response(data, media_type=d["mime"], headers={
        "Content-Disposition": f"attachment; filename=\"{name}\"; filename*=UTF-8''{_quote(d['filename'])}",
        "Content-Security-Policy": "sandbox", "X-Content-Type-Options": "nosniff", "Cache-Control": "private, no-store"})


@router.get("/documents/{document_id}/preview", response_model=PreviewOut)
async def preview_document(document_id: UUID, theme: Literal["light", "dark"] = "light", user: CurrentUser = User) -> PreviewOut:
    """Página formatada de um arquivo do Papo (Markdown renderizado, Word/PDF por página, planilha como tabela)."""
    import asyncio

    from ..render import page, preview

    async with tx(user.id) as conn:
        d = await row(conn, """SELECT filename, storage_key, origin, EXISTS (SELECT 1 FROM document_purge p WHERE p.document_id = d.id) AS purged
                                 FROM document d WHERE d.id = :d""", d=document_id)
    if not d:
        raise NotFound("Arquivo não encontrado.")
    if d["purged"]:
        raise Gone("Este arquivo foi removido para liberar espaço.")
    data = await storage.get(d["storage_key"])
    name = d["filename"]
    if d["origin"] == "agent" and name.lower().endswith((".html", ".htm")):
        return PreviewOut(name=name, html=data.decode("utf-8", "replace"))      # página gerada pelo Papo: já vem formatada
    if name.lower().endswith((".html", ".htm")):
        from ..extract.office import html_to_text
        from ..render import paragraphs

        return PreviewOut(name=name, html=page(paragraphs(html_to_text(data.decode("utf-8", "replace"))), name, theme,
                                                "HTML enviado: mostrado como texto, sem scripts nem estilos do arquivo."))
    return PreviewOut(**await asyncio.to_thread(preview, data, name, theme))


def _quote(s: str) -> str:
    from urllib.parse import quote
    return quote(s, safe="")


async def _remove(conn: AsyncConnection, owner: UUID, document_id: UUID) -> tuple[str, int, str | None]:
    """Apaga (base do agente ou anexo nunca enviado) ou libera o espaço (anexo preso a mensagem). Devolve ação, bytes e chave a remover."""
    d = await row(conn, """SELECT d.id, d.agent_id, d.size_bytes, d.storage_key, d.status,
                                  EXISTS (SELECT 1 FROM document_purge p WHERE p.document_id = d.id) AS purged,
                                  EXISTS (SELECT 1 FROM message m WHERE m.document_id = d.id) AS in_message,
                                  EXISTS (SELECT 1 FROM agent_run r WHERE r.status IN ('queued','running')
                                           AND r.conversation_id = d.conversation_id) AS busy
                             FROM document d WHERE d.id = :d""", d=document_id)
    if not d:
        raise NotFound("Arquivo não encontrado.")
    if d["purged"]:
        return "já removido", 0, None
    if d["busy"] or d["status"] == "pending":
        raise DomainError("O arquivo está em uso agora (leitura ou resposta em andamento). Tente de novo em instantes.")
    if not d["in_message"]:
        await conn.execute(text("DELETE FROM document WHERE id = :d"), {"d": document_id})
        return "apagado", int(d["size_bytes"]), d["storage_key"]
    for t in ("doc_row", "doc_sheet", "doc_chunk"):
        await conn.execute(text(f"DELETE FROM {t} WHERE document_id = :d"), {"d": document_id})
    await conn.execute(text("INSERT INTO document_purge (document_id, owner_id, bytes_freed) VALUES (:d, :o, :b)"),
                       {"d": document_id, "o": owner, "b": d["size_bytes"]})
    return "espaço liberado", int(d["size_bytes"]), d["storage_key"]


@router.delete("/documents/{document_id}")
async def delete_document(document_id: UUID, user: CurrentUser = User) -> dict[str, Any]:
    async with tx(user.id) as conn:
        action, freed, key = await _remove(conn, user.id, document_id)
    if key:
        await storage.remove(key)
    return {"action": action, "bytes_freed": freed}


@router.post("/documents/cleanup")
async def cleanup(what: Literal["duplicados", "problemas"], user: CurrentUser = User) -> dict[str, Any]:
    async with tx(user.id) as conn:
        live = "NOT EXISTS (SELECT 1 FROM document_purge p WHERE p.document_id = d.id)"
        if what == "problemas":
            ids = [r["id"] for r in await rows(conn, f"SELECT id FROM document d WHERE {live} AND status IN ('failed','unreadable')")]
        else:      # mantém a cópia mais antiga de cada conteúdo; base de agente vence anexo de conversa
            ids = [r["id"] for r in await rows(conn, f"""
                SELECT id FROM (SELECT d.id, row_number() OVER (PARTITION BY sha256 ORDER BY (agent_id IS NULL), created_at) AS n
                                  FROM document d WHERE {live} AND status <> 'pending') x WHERE n > 1""")]
        done, keys, freed = 0, [], 0
        for i in ids:
            action, b, key = await _remove(conn, user.id, i)
            if action != "já removido":
                done += 1
                freed += b
            if key:
                keys.append(key)
    for k in keys:
        await storage.remove(k)
    return {"files": done, "bytes_freed": freed}


@router.put("/admin/storage", response_model=StorageQuotaIn)
async def put_quota(body: StorageQuotaIn, user: CurrentUser = Admin) -> StorageQuotaIn:
    async with tx(user.id) as conn:
        await conn.execute(text("UPDATE app_config SET storage_quota_mb = :q, updated_by = :u, updated_at = now()"),
                           {"q": body.storage_quota_mb, "u": user.id})
    return body


@router.get("/admin/storage", response_model=StorageQuotaIn)
async def get_quota(user: CurrentUser = Admin) -> StorageQuotaIn:
    async with tx(user.id) as conn:
        return StorageQuotaIn(storage_quota_mb=await scalar(conn, "SELECT storage_quota_mb FROM app_config"))
