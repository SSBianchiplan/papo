"""Armazenamento de arquivos no MinIO. Chave sempre prefixada pelo dono (INV-DOC-003)."""
import asyncio
import io
from pathlib import Path
from uuid import UUID, uuid4

from minio import Minio

from .config import get_settings

_client: Minio | None = None


def client() -> Minio:
    global _client
    if _client is None:
        s = get_settings()
        _client = Minio(s.s3_endpoint, access_key=s.s3_access_key, secret_key=s.s3_secret_key, secure=s.s3_secure)
    return _client


def new_key(owner: UUID, kind: str, ext: str) -> str:
    ext = "".join(c for c in ext.lower() if c.isalnum())[:8]
    return f"{owner}/{kind}/{uuid4()}{'.' + ext if ext else ''}"


def _fs(key: str) -> Path:
    base = Path(get_settings().storage_dir).resolve()
    p = (base / key).resolve()
    if base not in p.parents:
        raise ValueError("chave fora do diretório de armazenamento")
    return p


async def ensure_bucket() -> None:
    if get_settings().storage_dir:
        return
    b = get_settings().s3_bucket
    if not await asyncio.to_thread(client().bucket_exists, b):
        await asyncio.to_thread(client().make_bucket, b)


async def put(key: str, data: bytes, content_type: str) -> None:
    if get_settings().storage_dir:
        p = _fs(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        return
    await asyncio.to_thread(client().put_object, get_settings().s3_bucket, key, io.BytesIO(data), len(data), content_type=content_type)


async def get(key: str) -> bytes:
    if get_settings().storage_dir:
        return _fs(key).read_bytes()
    def _get() -> bytes:
        r = client().get_object(get_settings().s3_bucket, key)
        try:
            return r.read()
        finally:
            r.close()
            r.release_conn()
    return await asyncio.to_thread(_get)


async def remove_prefix(prefix: str) -> None:
    if get_settings().storage_dir:
        import shutil

        shutil.rmtree(_fs(prefix.rstrip("/")), ignore_errors=True)
        return
    def _rm() -> None:
        b = get_settings().s3_bucket
        for o in client().list_objects(b, prefix=prefix, recursive=True):
            if o.object_name:
                client().remove_object(b, o.object_name)
    await asyncio.to_thread(_rm)


async def remove(key: str) -> None:
    if get_settings().storage_dir:
        _fs(key).unlink(missing_ok=True)
        return
    await asyncio.to_thread(client().remove_object, get_settings().s3_bucket, key)
