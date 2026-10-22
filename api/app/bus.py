"""Redis: eventos em tempo real (pub/sub por usuário), fila (arq), cancelamento e limites."""
import json
from typing import Any
from uuid import UUID

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings
from redis.asyncio import Redis

from .config import get_settings

_redis: Redis | None = None
_arq: ArqRedis | None = None


def redis() -> Redis:
    global _redis
    if _redis is None:
        _redis = Redis.from_url(get_settings().redis_url, decode_responses=True)
    return _redis


def arq_settings() -> RedisSettings:
    return RedisSettings.from_dsn(get_settings().redis_url)


async def queue() -> ArqRedis:
    global _arq
    if _arq is None:
        _arq = await create_pool(arq_settings())
    return _arq


def channel(uid: UUID | str) -> str:
    return f"papo:u:{uid}"


async def publish(uid: UUID | str, event: str, data: dict[str, Any]) -> None:
    await redis().publish(channel(uid), json.dumps({"type": event, "data": data}, default=str, ensure_ascii=False))


async def enqueue(job: str, *args: Any) -> None:
    await (await queue()).enqueue_job(job, *args)


def cancel_key(conversation_id: UUID | str) -> str:
    return f"papo:cancel:{conversation_id}"


async def request_cancel(conversation_id: UUID | str) -> None:
    await redis().set(cancel_key(conversation_id), "1", ex=600)


async def clear_cancel(conversation_id: UUID | str) -> None:
    await redis().delete(cancel_key(conversation_id))


async def cancelled(conversation_id: UUID | str) -> bool:
    return bool(await redis().exists(cancel_key(conversation_id)))


async def rate_ok(uid: UUID, bucket: str, limit: int, window_s: int = 60) -> bool:
    key = f"papo:rl:{bucket}:{uid}"
    n = await redis().incr(key)
    if n == 1:
        await redis().expire(key, window_s)
    return int(n) <= limit
