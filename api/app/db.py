"""Acesso ao banco. Toda transação de negócio roda com papo.uid definido (RLS)."""
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

from .config import get_settings

_engine: AsyncEngine | None = None


def engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        _engine = create_async_engine(get_settings().database_url, pool_size=10, max_overflow=10, pool_pre_ping=True)
    return _engine


async def dispose() -> None:
    global _engine
    if _engine is not None:
        await _engine.dispose()
        _engine = None


@asynccontextmanager
async def tx(uid: UUID | None) -> AsyncIterator[AsyncConnection]:
    """Transação com o usuário fixado para as políticas de RLS."""
    async with engine().begin() as conn:
        await conn.execute(text("SELECT set_config('papo.uid', :u, true)"), {"u": str(uid) if uid else ""})
        yield conn


async def rows(conn: AsyncConnection, sql: str, **params: Any) -> list[dict[str, Any]]:
    res = await conn.execute(text(sql), params)
    return [dict(r._mapping) for r in res]


async def row(conn: AsyncConnection, sql: str, **params: Any) -> dict[str, Any] | None:
    res = await conn.execute(text(sql), params)
    r = res.first()
    return dict(r._mapping) if r else None


async def scalar(conn: AsyncConnection, sql: str, **params: Any) -> Any:
    res = await conn.execute(text(sql), params)
    return res.scalar()
