"""Cliente do gateway de leitura (usado pela API e pelo worker). Os bytes ficam só em memória."""
from __future__ import annotations

from typing import Any
from uuid import UUID

import httpx

from ..config import get_settings
from ..errors import DomainError


class HubError(DomainError):
    status = 502
    code = "hub"


def _c(timeout: float = 120) -> httpx.AsyncClient:
    s = get_settings()
    return httpx.AsyncClient(base_url=s.hubgw_url, timeout=httpx.Timeout(timeout, connect=5), headers={"x-hubgw-token": s.hubgw_token})


async def _get(url: str, **params: Any) -> httpx.Response:
    try:
        async with _c() as c:
            r = await c.get(url, params=params or None)
    except httpx.HTTPError as e:
        raise HubError("O leitor do hub não respondeu.", hint=str(e)[:200]) from e
    if r.status_code != 200:
        msg = r.json().get("detail", r.text[:200]) if r.headers.get("content-type", "").startswith("application/json") else r.text[:200]
        raise HubError(f"Leitura no hub falhou: {msg}")
    return r


async def health(source_id: UUID) -> dict[str, Any]:
    return dict((await _get(f"/s/{source_id}/health")).json())


async def scan(source_id: UUID) -> list[tuple[str, int, float]]:
    return [(str(p), int(s), float(m)) for p, s, m in (await _get(f"/s/{source_id}/scan")).json()["files"]]


async def read(source_id: UUID, path: str) -> bytes:
    return (await _get(f"/s/{source_id}/file", path=path)).content
