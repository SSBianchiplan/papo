"""Autenticação: access token do Keycloak (RS256) validado por JWKS. Dev mode só em development/test."""
import asyncio
from dataclasses import dataclass
from uuid import UUID

import jwt
from fastapi import Depends, HTTPException, Request
from jwt import PyJWKClient
from sqlalchemy import text

from .config import get_settings
from .db import scalar, tx

_jwks: PyJWKClient | None = None


@dataclass(frozen=True)
class CurrentUser:
    id: UUID
    sub: str
    is_admin: bool = False
    is_master: bool = False


def _client() -> PyJWKClient:
    global _jwks
    if _jwks is None:
        _jwks = PyJWKClient(get_settings().jwks_url, cache_keys=True, lifespan=3600)
    return _jwks


async def verify_token(token: str) -> dict[str, object]:
    s = get_settings()
    try:
        key = await asyncio.to_thread(_client().get_signing_key_from_jwt, token)
        claims: dict[str, object] = jwt.decode(
            token, key.key, algorithms=["RS256"], audience=s.oidc_audience, issuer=s.oidc_issuer,
            options={"require": ["exp", "iat", "sub"]}, leeway=30,
        )
    except jwt.PyJWTError as e:
        raise HTTPException(401, "token inválido ou expirado") from e
    return claims


async def login(claims: dict[str, object]) -> CurrentUser:
    sub = str(claims["sub"])
    name = str(claims.get("name") or claims.get("preferred_username") or "")
    email = claims.get("email")
    async with tx(None) as conn:
        uid = await scalar(conn, "SELECT papo_login(:s, :e, :n)", s=sub, e=str(email) if email else None, n=name)
    master = _has_role(claims, get_settings().master_role)
    admin = master or _has_role(claims, get_settings().admin_role)          # master é sempre administrador
    async with tx(uid) as conn:            # registra os papéis para o worker e a gestão de contas (só escreve quando muda)
        await conn.execute(text("UPDATE app_user SET is_admin = :a, is_master = :m WHERE id = :u AND (is_admin, is_master) <> (:a, :m)"),
                           {"a": admin, "m": master, "u": uid})
    return CurrentUser(id=uid, sub=sub, is_admin=admin, is_master=master)


def _has_role(claims: dict[str, object], role: str) -> bool:
    s = get_settings()
    if s.auth_dev_mode and claims.get("_dev"):        # marca interna do modo dev; token real nunca chega aqui com ela valendo
        sub = str(claims["sub"])
        return sub in s.dev_masters if role == s.master_role else sub in s.dev_admins
    realm = claims.get("realm_access")
    roles = realm.get("roles", []) if isinstance(realm, dict) else []
    return isinstance(roles, list) and role in roles


async def user_from_token(token: str) -> CurrentUser:
    s = get_settings()
    if s.auth_dev_mode and token.startswith("dev:"):
        return await login({"sub": token[4:], "name": token[4:], "_dev": True})
    return await login(await verify_token(token))


async def current_user(request: Request) -> CurrentUser:
    s = get_settings()
    if s.auth_dev_mode and (dev := request.headers.get("x-dev-user")):
        return await login({"sub": dev, "name": dev, "_dev": True})
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        raise HTTPException(401, "autenticação necessária")
    return await user_from_token(auth[7:].strip())


async def admin_user(request: Request) -> CurrentUser:
    user = await current_user(request)
    if not user.is_admin:
        raise HTTPException(403, "área restrita a administradores")
    return user


async def master_user(request: Request) -> CurrentUser:
    user = await current_user(request)
    if not user.is_master:
        raise HTTPException(403, "só o administrador master pode fazer isto")
    return user


User = Depends(current_user)
Admin = Depends(admin_user)
Master = Depends(master_user)
