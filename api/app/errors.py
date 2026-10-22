"""Erros de domínio tipados → HTTP. Violação de invariante do banco vira 409/422 legível."""
from fastapi import Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import DBAPIError, IntegrityError


class DomainError(Exception):
    status = 400
    code = "erro"

    def __init__(self, message: str, *, hint: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint


class NotFound(DomainError):
    status = 404
    code = "nao_encontrado"


class Conflict(DomainError):
    status = 409
    code = "conflito"


class Invalid(DomainError):
    status = 422
    code = "invalido"


class TooMany(DomainError):
    status = 429
    code = "limite"


async def domain_handler(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, DomainError)
    return JSONResponse({"code": exc.code, "message": exc.message, "hint": exc.hint}, status_code=exc.status)


_FRIENDLY = {
    "agent_owner_name_uq": "Já existe um agente com esse nome.",
    "conversation_one_dm_uq": "Já existe uma conversa com esse agente.",
}


async def db_handler(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, DBAPIError)
    raw = str(getattr(exc, "orig", exc))
    for key, msg in _FRIENDLY.items():
        if key in raw:
            return JSONResponse({"code": "conflito", "message": msg}, status_code=409)
    if isinstance(exc, IntegrityError) or "INV-" in raw or "check_violation" in raw:
        inv = next((p for p in raw.replace(":", " ").split() if p.startswith("INV-")), None)
        return JSONResponse({"code": "invariante", "message": "Operação recusada pelo banco.", "hint": inv}, status_code=409)
    raise exc
