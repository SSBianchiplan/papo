"""Ambiente de teste: banco real (PostgreSQL 16) com o schema migrado, Redis real, storage em memória e modelo falso."""
from __future__ import annotations

import os
import subprocess
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

PG_ADMIN = os.environ.get("TEST_PG_ADMIN", "postgresql://postgres@127.0.0.1:5433/postgres")
PG_HOST = os.environ.get("TEST_PG_HOST", "127.0.0.1:5433")
DB = f"papo_test_{uuid.uuid4().hex[:6]}"

os.environ.update({
    "ENV": "test",
    "AUTH_DEV_MODE": "true",
    "DATABASE_URL": f"postgresql+asyncpg://papo_app:app@{PG_HOST}/{DB}",
    "REDIS_URL": os.environ.get("TEST_REDIS_URL", "redis://127.0.0.1:6380/9"),
    "DAILY_TOKEN_LIMIT": "0",
    "SECRETS_KEY": "chave-de-teste-nao-usar-em-producao",
})
API = Path(__file__).resolve().parents[1]


def _psql(sql: str, db: str = "postgres") -> None:
    import psycopg

    with psycopg.connect(PG_ADMIN.rsplit("/", 1)[0] + "/" + db, autocommit=True) as c:
        c.execute(sql)


@pytest.fixture(scope="session", autouse=True)
def database() -> object:
    _psql(f'CREATE DATABASE "{DB}" OWNER papo_owner')
    _psql("CREATE EXTENSION IF NOT EXISTS pgcrypto; CREATE EXTENSION IF NOT EXISTS unaccent;", DB)
    env = {**os.environ, "MIGRATION_DATABASE_URL": f"postgresql+psycopg://papo_owner:owner@{PG_HOST}/{DB}"}
    subprocess.run(["alembic", "upgrade", "head"], cwd=API, env=env, check=True, capture_output=True)
    yield
    subprocess.run(["alembic", "downgrade", "base"], cwd=API, env=env, check=True, capture_output=True)   # BUILD: reverte limpo
    _psql(f'DROP DATABASE "{DB}" WITH (FORCE)')


@pytest.fixture(autouse=True)
def memory_storage(monkeypatch: pytest.MonkeyPatch) -> dict[str, bytes]:
    from app import storage

    mem: dict[str, bytes] = {}

    async def put(key: str, data: bytes, ct: str) -> None:
        mem[key] = data

    async def get(key: str) -> bytes:
        return mem[key]

    async def remove(key: str) -> None:
        mem.pop(key, None)

    async def remove_prefix(prefix: str) -> None:
        for k in [k for k in mem if k.startswith(prefix)]:
            mem.pop(k)

    monkeypatch.setattr(storage, "put", put)
    monkeypatch.setattr(storage, "get", get)
    monkeypatch.setattr(storage, "remove", remove)
    monkeypatch.setattr(storage, "remove_prefix", remove_prefix)
    return mem


@pytest.fixture
def jobs(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, tuple[object, ...]]]:
    """Captura os jobs em vez de enfileirar; o teste executa quando quiser."""
    from app import bus

    captured: list[tuple[str, tuple[object, ...]]] = []

    async def enqueue(job: str, *args: object) -> None:
        captured.append((job, args))

    monkeypatch.setattr(bus, "enqueue", enqueue)
    return captured


@pytest.fixture
async def client() -> AsyncIterator[object]:
    import httpx

    from app import db
    from app.main import app

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        yield c
    await db.dispose()


@pytest.fixture
def owner_conn() -> object:
    """Conexão como dono do schema — usada pelo RED-TEAM para provar que nem o caminho direto passa."""
    import psycopg

    return lambda: psycopg.connect(f"postgresql://papo_owner:owner@{PG_HOST}/{DB}", autocommit=True)


@pytest.fixture
def app_conn() -> object:
    import psycopg

    return lambda: psycopg.connect(f"postgresql://papo_app:app@{PG_HOST}/{DB}", autocommit=True)
