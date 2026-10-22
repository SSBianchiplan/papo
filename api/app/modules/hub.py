"""Docs do hub: fontes de leitura, catálogo (só metadados), pré-visualização e download direto da origem, vínculo com agentes.

Administrador cria, testa, indexa e libera as fontes. Usuário comum só vê fontes marcadas como visíveis para todos.
Nenhum arquivo é guardado no Papo: pré-visualização e download leem da origem na hora, via gateway.
"""
from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import text

from .. import secretbox
from ..auth import Admin, CurrentUser, User
from ..db import row, rows, scalar, tx
from ..errors import DomainError, Invalid, NotFound
from ..extract.parsers import parse
from ..hub import client, rules
from ..schemas import PreviewOut

router = APIRouter(prefix="/api/hub", tags=["docs do hub"])


class Forbidden(DomainError):
    status = 403
    code = "proibido"


class SourceIn(BaseModel):
    name: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,39}$")
    label: str = Field(min_length=1, max_length=80)
    kind: Literal["local", "remote", "sftp"]
    roots: list[str] = Field(default_factory=list, max_length=10)          # local
    url: str | None = Field(default=None, pattern=r"^https://[A-Za-z0-9.:-]+(/.*)?$", max_length=200)   # remote
    cert_pem: str | None = Field(default=None, max_length=10_000)
    host: str | None = Field(default=None, pattern=r"^[A-Za-z0-9.-]{3,120}$")    # sftp
    port: int = Field(default=22, ge=1, le=65535)
    user: str | None = Field(default=None, max_length=120)
    root: str = Field(default=".", max_length=300)
    secret: str | None = Field(default=None, max_length=500)                # token (remote) ou senha (sftp); None = mantém
    extensions: list[str] = Field(default_factory=lambda: list(rules.DEFAULT_EXT), min_length=1, max_length=40)
    enabled: bool = True
    visible_all: bool = False


class SourceOut(BaseModel):
    id: UUID
    name: str
    label: str
    kind: Literal["local", "remote", "sftp"]
    config: dict[str, Any]
    has_secret: bool
    extensions: list[str]
    enabled: bool
    visible_all: bool
    status: str
    last_error: str | None
    last_scan_at: datetime | None
    file_count: int
    total_bytes: int


class HubFile(BaseModel):
    source_id: UUID
    source: str
    path: str
    ext: str
    size_bytes: int
    mtime: datetime


class StatRow(BaseModel):
    key: str
    files: int
    bytes: int


class HubStats(BaseModel):
    files: int
    bytes: int
    by_ext: list[StatRow]
    by_source: list[StatRow]
    by_folder: list[StatRow]
    recent: list[HubFile]


class AgentHubLink(BaseModel):
    source_id: UUID
    prefix: str = Field(default="", max_length=512)


class AgentHubIn(BaseModel):
    links: list[AgentHubLink] = Field(default_factory=list, max_length=50)


def _out(r: dict[str, Any]) -> SourceOut:
    cfg = {k: v for k, v in dict(r["config"] or {}).items() if k != "cert_pem"}
    if r["config"] and r["config"].get("cert_pem"):
        cfg["cert"] = "fixado"
    return SourceOut(**{k: r[k] for k in SourceOut.model_fields if k in r and k not in ("config", "has_secret")}, config=cfg,
                     has_secret=r["secret_enc"] is not None)


async def _visible_ids(conn: Any, user: CurrentUser) -> list[UUID]:
    q = "SELECT id FROM hub_source WHERE enabled" + ("" if user.is_admin else " AND visible_all")
    return [r["id"] for r in await rows(conn, q)]


# ------------------------------------------------------------------ fontes (admin)
@router.get("/sources", response_model=list[SourceOut])
async def list_sources(user: CurrentUser = User) -> list[SourceOut]:
    async with tx(user.id) as conn:
        q = "SELECT * FROM hub_source" + ("" if user.is_admin else " WHERE enabled AND visible_all") + " ORDER BY label"
        return [_out(r) for r in await rows(conn, q)]


def _config(body: SourceIn, old: dict[str, Any] | None) -> dict[str, Any]:
    if body.kind == "local":
        return {"roots": body.roots}
    if body.kind == "remote":
        pem = body.cert_pem or (old or {}).get("cert_pem")
        if not body.url or not pem or "BEGIN CERTIFICATE" not in pem:
            raise Invalid("Fonte remota precisa do endereço https e do certificado (cert.pem) do leitor.")
        return {"url": body.url, "cert_pem": pem.strip()}
    if not body.host or not body.user:
        raise Invalid("SFTP precisa de servidor e usuário.")
    keep = (old or {}).get("host_key", "") if old and old.get("host") == body.host and int(old.get("port", 22)) == body.port else ""
    return {"host": body.host, "port": body.port, "user": body.user, "root": body.root or ".", "host_key": keep}


@router.post("/sources", response_model=SourceOut, status_code=201)
async def create_source(body: SourceIn, user: CurrentUser = Admin) -> SourceOut:
    exts = sorted({e.lower().lstrip(".") for e in body.extensions if e.strip()})
    if body.kind in ("remote", "sftp") and not body.secret:
        raise Invalid("Informe o token (leitor remoto) ou a senha (SFTP).")
    async with tx(user.id) as conn:
        r = await row(conn, """INSERT INTO hub_source (name, label, kind, config, secret_enc, extensions, enabled, visible_all)
                               VALUES (:n, :l, :k, CAST(:c AS jsonb), :s, :e, :en, :v) RETURNING *""",
                      n=body.name, l=body.label, k=body.kind, c=json.dumps(_config(body, None)),
                      s=secretbox.seal(body.secret) if body.secret else None, e=exts, en=body.enabled, v=body.visible_all)
    assert r
    return _out(r)


@router.put("/sources/{source_id}", response_model=SourceOut)
async def update_source(source_id: UUID, body: SourceIn, user: CurrentUser = Admin) -> SourceOut:
    async with tx(user.id) as conn:
        old = await row(conn, "SELECT * FROM hub_source WHERE id = :i", i=source_id)
        if not old:
            raise NotFound("Fonte não encontrada.")
        cfg = _config(body, dict(old["config"] or {}))
        r = await row(conn, """UPDATE hub_source SET name = :n, label = :l, kind = :k, config = CAST(:c AS jsonb),
                                      secret_enc = coalesce(:s, secret_enc), extensions = :e, enabled = :en, visible_all = :v
                                WHERE id = :i RETURNING *""",
                      n=body.name, l=body.label, k=body.kind, c=json.dumps(cfg), s=secretbox.seal(body.secret) if body.secret else None,
                      e=sorted({e.lower().lstrip(".") for e in body.extensions}), en=body.enabled, v=body.visible_all, i=source_id)
    assert r
    return _out(r)


@router.delete("/sources/{source_id}", status_code=204, response_model=None)
async def delete_source(source_id: UUID, user: CurrentUser = Admin) -> None:
    async with tx(user.id) as conn:
        await conn.execute(text("DELETE FROM hub_source WHERE id = :i"), {"i": source_id})


@router.post("/sources/{source_id}/test")
async def test_source(source_id: UUID, user: CurrentUser = Admin) -> dict[str, Any]:
    r = await client.health(source_id)
    async with tx(user.id) as conn:
        await conn.execute(text("UPDATE hub_source SET status = :s, last_error = :e WHERE id = :i"),
                           {"s": "ok" if r.get("ok") else "erro", "e": None if r.get("ok") else str(r.get("error"))[:500], "i": source_id})
    return r


async def index_source(source_id: UUID) -> dict[str, int]:
    """Relê a lista na origem e atualiza o catálogo (inclui, atualiza e tira o que sumiu). Só metadados."""
    try:
        items = await client.scan(source_id)
    except DomainError as e:
        async with tx(None) as conn:
            await conn.execute(text("UPDATE hub_source SET status = 'erro', last_error = :e WHERE id = :i"), {"e": e.message[:500], "i": source_id})
        raise
    now = datetime.now(UTC)
    async with tx(None) as conn:
        before = int(await scalar(conn, "SELECT count(*) FROM hub_file WHERE source_id = :i", i=source_id))
        for i in range(0, len(items), 500):
            await conn.execute(text("""INSERT INTO hub_file (source_id, path, ext, size_bytes, mtime, seen_at) VALUES (:s, :p, :e, :b, :m, :n)
                                       ON CONFLICT (source_id, path) DO UPDATE SET size_bytes = EXCLUDED.size_bytes, mtime = EXCLUDED.mtime,
                                           ext = EXCLUDED.ext, seen_at = EXCLUDED.seen_at"""),
                               [{"s": source_id, "p": p, "e": rules.ext_of(p), "b": size, "m": datetime.fromtimestamp(mt, UTC), "n": now}
                                for p, size, mt in items[i:i + 500]])
        gone = (await conn.execute(text("DELETE FROM hub_file WHERE source_id = :i AND seen_at < :n"), {"i": source_id, "n": now})).rowcount
        await conn.execute(text("""UPDATE hub_source SET status = 'ok', last_error = NULL, last_scan_at = :n,
                                          file_count = (SELECT count(*) FROM hub_file WHERE source_id = :i),
                                          total_bytes = (SELECT coalesce(sum(size_bytes), 0) FROM hub_file WHERE source_id = :i)
                                    WHERE id = :i"""), {"n": now, "i": source_id})
    return {"files": len(items), "before": before, "removed": int(gone or 0)}


@router.post("/sources/{source_id}/index")
async def reindex(source_id: UUID, user: CurrentUser = Admin) -> dict[str, int]:
    return await index_source(source_id)


# ------------------------------------------------------------------ catálogo
FILE_SQL = """SELECT f.source_id, s.label AS source, f.path, f.ext, f.size_bytes, f.mtime
                FROM hub_file f JOIN hub_source s ON s.id = f.source_id WHERE f.source_id = ANY(:ids)"""


@router.get("/files", response_model=list[HubFile])
async def list_files(q: str | None = Query(default=None, max_length=200), source: UUID | None = None,
                     ext: str | None = Query(default=None, max_length=12), folder: str | None = Query(default=None, max_length=512),
                     sort: Literal["recentes", "nome", "tamanho"] = "recentes", limit: int = Query(default=200, ge=1, le=1000),
                     user: CurrentUser = User) -> list[HubFile]:
    async with tx(user.id) as conn:
        ids = await _visible_ids(conn, user)
        if source:
            ids = [i for i in ids if i == source]
        cond, params = [], {"ids": ids, "n": limit}
        if q:
            for i, w in enumerate(q.split()[:6]):
                cond.append(f"f_unaccent(lower(f.path)) LIKE '%' || f_unaccent(lower(:w{i})) || '%'")
                params[f"w{i}"] = w
        if ext:
            cond.append("f.ext = :ext")
            params["ext"] = ext.lower()
        if folder:
            cond.append("f.path LIKE :folder || '%'")
            params["folder"] = folder.rstrip("/") + "/"
        order = {"recentes": "f.mtime DESC", "nome": "lower(f.path)", "tamanho": "f.size_bytes DESC"}[sort]
        rs = await rows(conn, FILE_SQL + "".join(f" AND {c}" for c in cond) + f" ORDER BY {order} LIMIT :n", **params)
    return [HubFile(**r) for r in rs]


@router.get("/stats", response_model=HubStats)
async def stats(user: CurrentUser = User) -> HubStats:
    async with tx(user.id) as conn:
        ids = await _visible_ids(conn, user)
        tot = await row(conn, "SELECT count(*) AS n, coalesce(sum(size_bytes), 0) AS b FROM hub_file WHERE source_id = ANY(:ids)", ids=ids)
        by_ext = await rows(conn, """SELECT ext AS key, count(*) AS files, sum(size_bytes) AS bytes FROM hub_file WHERE source_id = ANY(:ids)
                                      GROUP BY ext ORDER BY 2 DESC""", ids=ids)
        by_src = await rows(conn, """SELECT s.label AS key, count(f.path) AS files, coalesce(sum(f.size_bytes), 0) AS bytes FROM hub_source s
                                      LEFT JOIN hub_file f ON f.source_id = s.id WHERE s.id = ANY(:ids) GROUP BY s.label ORDER BY 2 DESC""", ids=ids)
        by_folder = await rows(conn, """SELECT s.label || ' · ' || split_part(f.path, '/', 1) || '/' || split_part(f.path, '/', 2) AS key,
                                               count(*) AS files, sum(f.size_bytes) AS bytes
                                          FROM hub_file f JOIN hub_source s ON s.id = f.source_id WHERE f.source_id = ANY(:ids)
                                         GROUP BY 1 ORDER BY 2 DESC LIMIT 15""", ids=ids)
        recent = await rows(conn, FILE_SQL + " ORDER BY f.mtime DESC LIMIT 8", ids=ids)
    assert tot
    def num(rs: list[dict[str, Any]]) -> list[StatRow]:
        return [StatRow(key=str(r["key"]), files=int(r["files"]), bytes=int(r["bytes"] or 0)) for r in rs]

    return HubStats(files=int(tot["n"]), bytes=int(tot["b"]), by_ext=num(by_ext), by_source=num(by_src), by_folder=num(by_folder),
                    recent=[HubFile(**r) for r in recent])


async def _can_read(user: CurrentUser, source_id: UUID, path: str) -> dict[str, Any]:
    async with tx(user.id) as conn:
        if source_id not in await _visible_ids(conn, user):
            raise NotFound("Fonte não encontrada.")
        f = await row(conn, FILE_SQL + " AND f.path = :p", ids=[source_id], p=path)
    if not f:
        raise NotFound("Arquivo não está no índice. Reindexe a fonte.")
    return f


@router.get("/file/text")
async def file_text(source_id: UUID, path: str = Query(..., max_length=1024), user: CurrentUser = User) -> dict[str, Any]:
    """Pré-visualização: lê na origem, extrai em memória e devolve o texto. Nada é guardado."""
    await _can_read(user, source_id, path)
    data = await client.read(source_id, path)
    name = path.rsplit("/", 1)[-1]
    ex = await asyncio.to_thread(parse, data, name, "")
    sheets = [{"name": s.name, "columns": s.columns, "rows": s.rows[:50], "total": s.total} for s in ex.sheets]
    body = "\n\n".join(f"── {lab}\n{txt}" for lab, txt in ex.parts)
    return {"name": name, "size": len(data), "kind": ex.kind, "pages": ex.pages, "note": ex.note, "text": body[:400_000],
            "cut": len(body) > 400_000, "sheets": sheets}


@router.get("/file/preview", response_model=PreviewOut)
async def file_preview(source_id: UUID, path: str = Query(..., max_length=1024), theme: Literal["light", "dark"] = "light",
                       user: CurrentUser = User) -> PreviewOut:
    """Página formatada para ver o arquivo (lido agora na origem, montada em memória)."""
    from ..render import preview

    await _can_read(user, source_id, path)
    data = await client.read(source_id, path)
    return PreviewOut(**await asyncio.to_thread(preview, data, path.rsplit("/", 1)[-1], theme))


@router.get("/file/raw", response_class=Response, responses={200: {"content": {"application/octet-stream": {}}}})
async def file_raw(source_id: UUID, path: str = Query(..., max_length=1024), user: CurrentUser = User) -> Response:
    """Download direto da origem (passa pelo gateway em memória; não fica cópia)."""
    await _can_read(user, source_id, path)
    data = await client.read(source_id, path)
    from urllib.parse import quote

    name = path.rsplit("/", 1)[-1]
    return Response(data, media_type="application/octet-stream", headers={
        "Content-Disposition": f"attachment; filename*=UTF-8''{quote(name, safe='')}", "Content-Security-Policy": "sandbox",
        "X-Content-Type-Options": "nosniff", "Cache-Control": "no-store"})


# ------------------------------------------------------------------ agentes
@router.get("/agents/{agent_id}", response_model=AgentHubIn)
async def agent_links(agent_id: UUID, user: CurrentUser = User) -> AgentHubIn:
    async with tx(user.id) as conn:
        return AgentHubIn(links=[AgentHubLink(**r) for r in await rows(conn, "SELECT source_id, prefix FROM agent_hub WHERE agent_id = :a", a=agent_id)])


@router.put("/agents/{agent_id}", response_model=AgentHubIn)
async def put_agent_links(agent_id: UUID, body: AgentHubIn, user: CurrentUser = User) -> AgentHubIn:
    async with tx(user.id) as conn:
        if not await scalar(conn, "SELECT 1 FROM agent WHERE id = :a", a=agent_id):
            raise NotFound("Agente não encontrado.")
        visible = set(await _visible_ids(conn, user))
        for link in body.links:
            if link.source_id not in visible:
                raise Forbidden("Fonte do hub não disponível para você.")
        await conn.execute(text("DELETE FROM agent_hub WHERE agent_id = :a"), {"a": agent_id})
        seen = set()
        for link in body.links:
            prefix = rules.clean_rel(link.prefix).rstrip("/") if link.prefix.strip("/ ") else ""
            if (link.source_id, prefix) in seen:
                continue
            seen.add((link.source_id, prefix))
            await conn.execute(text("INSERT INTO agent_hub (owner_id, agent_id, source_id, prefix) VALUES (:o, :a, :s, :p)"),
                               {"o": user.id, "a": agent_id, "s": link.source_id, "p": prefix})
        return AgentHubIn(links=[AgentHubLink(**r) for r in await rows(conn, "SELECT source_id, prefix FROM agent_hub WHERE agent_id = :a", a=agent_id)])
