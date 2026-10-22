"""Recebimento de arquivos: limite de tamanho, hash, imagem normalizada (sem EXIF), envio ao storage."""
from __future__ import annotations

import asyncio
import hashlib
import io
from uuid import UUID

from fastapi import UploadFile
from PIL import Image, UnidentifiedImageError

from .. import bus, storage
from ..config import get_settings
from ..db import row, tx
from ..errors import Invalid
from ..extract.parsers import kind_of
from ..schemas import Document

IMAGE_MIMES = {"image/jpeg", "image/png", "image/webp", "image/gif"}


async def read_limited(f: UploadFile) -> bytes:
    limit = get_settings().max_upload_mb * 1024 * 1024
    buf = bytearray()
    while chunk := await f.read(1024 * 1024):
        buf += chunk
        if len(buf) > limit:
            raise Invalid(f"Arquivo maior que {get_settings().max_upload_mb} MB.")
    if not buf:
        raise Invalid("Arquivo vazio.")
    return bytes(buf)


def _normalize_image(data: bytes) -> bytes:
    try:
        src = Image.open(io.BytesIO(data))
        src.load()
    except (UnidentifiedImageError, OSError) as e:
        raise Invalid("Imagem inválida. Envie JPG, PNG, WebP ou GIF.") from e
    if src.width * src.height > 64_000_000:
        raise Invalid("Imagem grande demais.")
    im = src.convert("RGB")
    im.thumbnail((1600, 1600))
    out = io.BytesIO()
    im.save(out, "JPEG", quality=82, optimize=True)      # recodificar remove EXIF/GPS
    return out.getvalue()


async def store_image(owner: UUID, conversation_id: UUID, f: UploadFile) -> str:
    data = await read_limited(f)
    jpg = await asyncio.to_thread(_normalize_image, data)
    key = storage.new_key(owner, f"img/{conversation_id}", "jpg")
    await storage.put(key, jpg, "image/jpeg")
    return key


async def store_document(owner: UUID, f: UploadFile, *, agent_id: UUID | None = None, conversation_id: UUID | None = None) -> Document:
    from .common import documents_by_id
    from .documents import quota_bytes, used_bytes

    if (f.filename or "").lower().endswith(".skill"):
        raise Invalid("Arquivos .skill são skills, não documentos.", hint="Envie em Configuração → Skills, ou anexe pelo app, que importa e ativa sozinho.")
    data = await read_limited(f)
    async with tx(owner) as conn:
        quota = await quota_bytes(conn)
        if quota is not None and await used_bytes(conn) + len(data) > quota:
            raise Invalid(f"Seu espaço de arquivos está cheio (cota de {quota // 1048576} MB).",
                          hint="Abra Arquivos e libere espaço removendo duplicados ou o que não usa mais.")
    name = (f.filename or "arquivo").replace("/", "_").replace("\\", "_")[:255]
    mime = (f.content_type or "application/octet-stream")[:255]
    ext = name.rsplit(".", 1)[-1] if "." in name else ""
    key = storage.new_key(owner, "doc", ext)
    await storage.put(key, data, mime)
    async with tx(owner) as conn:
        d = await row(conn, """INSERT INTO document (owner_id, agent_id, conversation_id, filename, mime, size_bytes, sha256, storage_key, kind)
                               VALUES (:o, :a, :c, :f, :m, :s, :h, :k, :kind) RETURNING id""",
                      o=owner, a=agent_id, c=conversation_id, f=name, m=mime, s=len(data),
                      h=hashlib.sha256(data).hexdigest(), k=key, kind=kind_of(name, mime))
        assert d is not None
        doc = (await documents_by_id(conn, [d["id"]]))[d["id"]]
    await bus.enqueue("job_document", str(owner), str(doc.id))
    return doc
