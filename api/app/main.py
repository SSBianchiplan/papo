"""Aplicação FastAPI."""
from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import DBAPIError

from . import bus, db, storage
from .config import get_settings
from .errors import DomainError, db_handler, domain_handler
from .modules import accounts, admin, agents, conversations, documents, governanca_api, hub, me, runs, skills_api, system, usage
from .ws import router as ws_router

logging.basicConfig(level=logging.INFO, format='{"t":"%(asctime)s","lvl":"%(levelname)s","log":"%(name)s","msg":"%(message)s"}')


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    if get_settings().env != "test":
        await storage.ensure_bucket()
    yield
    await db.dispose()


app = FastAPI(title="Papo API", version="1.0.0", lifespan=lifespan,
              docs_url="/api/docs" if get_settings().env != "production" else None, openapi_url="/api/openapi.json")
app.add_exception_handler(DomainError, domain_handler)
app.add_exception_handler(DBAPIError, db_handler)
if get_settings().cors_origins:
    app.add_middleware(CORSMiddleware, allow_origins=get_settings().cors_origins, allow_methods=["*"], allow_headers=["*"])

for r in (me.router, accounts.router, agents.router, conversations.router, runs.router, usage.router, admin.router, documents.router, skills_api.router,
          hub.router, system.router, governanca_api.router, ws_router):
    app.include_router(r)


@app.get("/healthz", include_in_schema=False)
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/readyz", include_in_schema=False)
async def readyz() -> JSONResponse:
    problems = []
    try:
        async with db.tx(None) as conn:
            await db.scalar(conn, "SELECT 1")
    except Exception as e:  # noqa: BLE001
        problems.append(f"postgres: {type(e).__name__}")
    try:
        await bus.redis().ping()
    except Exception as e:  # noqa: BLE001
        problems.append(f"redis: {type(e).__name__}")
    return JSONResponse({"status": "ok" if not problems else "degraded", "problems": problems}, status_code=200 if not problems else 503)
