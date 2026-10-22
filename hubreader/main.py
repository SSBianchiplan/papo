"""Leitor do hub (somente leitura). Roda em cada VPS que não é a do Papo: lista documentos e entrega os bytes.

Nada é gravado, nada é alterado: as pastas entram no contêiner como volumes :ro. Acesso só com token, só do IP
do Papo, e por TLS com certificado próprio (o Papo fixa esse certificado).
"""
from __future__ import annotations

import hmac
import os

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse

import rules

TOKEN = os.environ["HUBREADER_TOKEN"]
ALLOW = {ip.strip() for ip in os.environ.get("HUBREADER_ALLOW_IPS", "").split(",") if ip.strip()}
ROOTS = dict(item.split("=", 1) for item in os.environ["HUBREADER_ROOTS"].split(",") if "=" in item)   # nome=/caminho
EXTS = set(os.environ.get("HUBREADER_EXTS", ",".join(rules.DEFAULT_EXT)).split(","))

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)


@app.middleware("http")
async def guard(request: Request, call_next):  # type: ignore[no-untyped-def]
    ip = request.client.host if request.client else ""
    if ALLOW and ip not in ALLOW:
        return JSONResponse({"error": "origem não autorizada"}, status_code=403)
    if not hmac.compare_digest(request.headers.get("authorization", ""), f"Bearer {TOKEN}"):
        return JSONResponse({"error": "token inválido"}, status_code=401)
    if request.method != "GET":
        return JSONResponse({"error": "somente leitura"}, status_code=405)
    return await call_next(request)


@app.get("/health")
def health() -> dict[str, object]:
    return {"ok": True, "roots": sorted(ROOTS)}


@app.get("/scan")
def scan() -> dict[str, list[list[object]]]:
    return {name: [[rel, size, mtime] for rel, size, mtime in rules.walk(path, EXTS)] for name, path in ROOTS.items()}


@app.get("/file")
def file(root: str = Query(...), path: str = Query(..., max_length=1024)) -> FileResponse:
    if root not in ROOTS:
        raise HTTPException(404, "raiz desconhecida")
    try:
        rel = rules.clean_rel(path)
        full = rules.resolve(ROOTS[root], rel)
    except (ValueError, PermissionError) as e:
        raise HTTPException(403, str(e)) from e
    if not rules.allowed(rel, EXTS) or not os.path.isfile(full) or os.path.getsize(full) > rules.MAX_FILE:
        raise HTTPException(404, "arquivo não disponível")
    return FileResponse(full, media_type="application/octet-stream")
