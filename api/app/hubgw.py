"""Gateway de leitura do hub. Único serviço do Papo que alcança as fontes (redes data + egress).

A API e o worker pedem aqui a lista e os bytes de um arquivo; nada é gravado em disco ou no storage —
os bytes passam em memória e são descartados depois da leitura. Só GET, só com token interno.
"""
from __future__ import annotations

import hmac
import logging
from collections.abc import Awaitable, Callable
from uuid import UUID

from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse

from .config import get_settings
from .hub import sources
from .hub.backends import Sftp

log = logging.getLogger("papo.hubgw")
app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)


@app.middleware("http")
async def guard(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
    if request.url.path == "/healthz":
        return await call_next(request)
    token = get_settings().hubgw_token
    if not token or not hmac.compare_digest(request.headers.get("x-hubgw-token", ""), token):
        return JSONResponse({"error": "token inválido"}, status_code=401)
    if request.method != "GET":
        return JSONResponse({"error": "somente leitura"}, status_code=405)
    return await call_next(request)


@app.get("/healthz")
def healthz() -> dict[str, bool]:
    return {"ok": True}


async def _load(source_id: UUID):  # type: ignore[no-untyped-def]
    try:
        return await sources.load(source_id)
    except LookupError as e:
        raise HTTPException(404, str(e)) from e


@app.get("/s/{source_id}/health")
async def health(source_id: UUID) -> dict[str, object]:
    _, b = await _load(source_id)
    try:
        r = await b.health()
    except Exception as e:  # noqa: BLE001 — diagnóstico vai para o administrador
        return {"ok": False, "error": str(e)[:400]}
    if isinstance(b, Sftp) and b.host_key:
        await sources.remember_host_key(source_id, b.host_key)
    return {"ok": True, **r}


@app.get("/s/{source_id}/scan")
async def scan(source_id: UUID) -> dict[str, object]:
    _, b = await _load(source_id)
    try:
        items = await b.scan()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"fonte indisponível: {str(e)[:300]}") from e
    if isinstance(b, Sftp) and b.host_key:
        await sources.remember_host_key(source_id, b.host_key)
    return {"files": [[p, s, m] for p, s, m in items]}


@app.get("/s/{source_id}/file")
async def file(source_id: UUID, path: str = Query(..., max_length=1024)) -> Response:
    _, b = await _load(source_id)
    try:
        data = await b.read(path)
    except (PermissionError, ValueError) as e:
        raise HTTPException(403, str(e)) from e
    except FileNotFoundError as e:
        raise HTTPException(404, "arquivo não existe mais na origem") from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"fonte indisponível: {str(e)[:300]}") from e
    return Response(data, media_type="application/octet-stream", headers={"Cache-Control": "no-store"})
