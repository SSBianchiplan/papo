"""Gestão de contas no Keycloak pela Admin REST API, com o service account de um cliente confidencial do realm.

O cliente só tem view-users, query-users e manage-users do realm-management: lista, cria, ativa/desativa, troca senha
e mapeia os papéis papo-admin e papo-master. Nunca vê nem altera configuração do realm.
"""
from __future__ import annotations

import asyncio
import secrets
import string
import time
from typing import Any

import httpx

from .config import get_settings
from .errors import Conflict, DomainError, NotFound

_token: tuple[str, float] | None = None


class KcError(DomainError):
    status = 502
    code = "keycloak"


def configured() -> bool:
    return bool(get_settings().kc_admin_client_secret)


async def _access_token(c: httpx.AsyncClient) -> str:
    global _token
    if _token and _token[1] > time.time() + 20:
        return _token[0]
    s = get_settings()
    r = await c.post(f"{s.kc_internal_url}/realms/{s.kc_realm}/protocol/openid-connect/token",
                     data={"grant_type": "client_credentials", "client_id": s.kc_admin_client_id, "client_secret": s.kc_admin_client_secret})
    if r.status_code != 200:
        raise KcError("O Papo não conseguiu falar com o Keycloak para gerenciar contas.", hint="Confira KC_ADMIN_CLIENT_SECRET no servidor.")
    j = r.json()
    _token = (j["access_token"], time.time() + int(j.get("expires_in", 60)))
    return _token[0]


async def call(method: str, path: str, *, json: Any = None, params: dict[str, Any] | None = None) -> Any:
    if not configured():
        raise KcError("A gestão de contas ainda não está ligada neste servidor.", hint="Falta KC_ADMIN_CLIENT_SECRET no .env.")
    s = get_settings()
    async with httpx.AsyncClient(timeout=15) as c:
        tok = await _access_token(c)
        r = await c.request(method, f"{s.kc_internal_url}/admin/realms/{s.kc_realm}{path}", json=json, params=params,
                            headers={"Authorization": f"Bearer {tok}"})
    if r.status_code == 409:
        raise Conflict("Já existe uma conta com este e-mail.")
    if r.status_code == 404:
        raise NotFound("Conta não encontrada.")
    if r.status_code >= 400:
        raise KcError(f"O Keycloak recusou a operação ({r.status_code}).")
    if r.status_code == 201:
        return r.headers.get("location", "").rsplit("/", 1)[-1]
    return r.json() if r.content else None


async def users() -> list[dict[str, Any]]:
    return list(await call("GET", "/users", params={"max": 1000, "briefRepresentation": "false"}))


async def user(uid: str) -> dict[str, Any]:
    return dict(await call("GET", f"/users/{uid}"))


async def roles(uid: str) -> set[str]:
    """Papéis do realm mapeados direto na conta (não exige view-realm, só view-users)."""
    return {r["name"] for r in await call("GET", f"/users/{uid}/role-mappings/realm")}


async def roles_of(uids: list[str]) -> dict[str, set[str]]:
    res = await asyncio.gather(*(roles(u) for u in uids))
    return dict(zip(uids, res, strict=True))


async def set_role(uid: str, role: str, on: bool) -> None:
    pool = await call("GET", f"/users/{uid}/role-mappings/realm" + ("/available" if on else ""))
    r = next((x for x in pool if x["name"] == role), None)
    if r is None:
        if on:
            raise NotFound(f"O papel {role} não existe no realm.")
        return
    await call("POST" if on else "DELETE", f"/users/{uid}/role-mappings/realm", json=[{"id": r["id"], "name": r["name"]}])


def temp_password() -> str:
    """16 caracteres com maiúscula, minúscula, número e símbolo (passa em qualquer política razoável do realm)."""
    alpha = string.ascii_letters + string.digits
    while True:
        p = "".join(secrets.choice(alpha) for _ in range(14)) + secrets.choice("!@#$%&*") + secrets.choice(string.digits)
        if any(ch.islower() for ch in p) and any(ch.isupper() for ch in p):
            return p


async def reset_password(uid: str) -> str:
    pw = temp_password()
    await call("PUT", f"/users/{uid}/reset-password", json={"type": "password", "value": pw, "temporary": True})
    return pw


async def create(email: str, name: str) -> str:
    first, _, last = name.strip().partition(" ")
    return str(await call("POST", "/users", json={"username": email.lower(), "email": email.lower(), "emailVerified": True, "enabled": True,
                                                  "firstName": first, "lastName": last or "", "requiredActions": ["UPDATE_PASSWORD"]}))


async def update(uid: str, **fields: Any) -> None:
    cur = await user(uid)
    await call("PUT", f"/users/{uid}", json={**{k: cur.get(k) for k in ("username", "email", "firstName", "lastName", "enabled", "emailVerified")}, **fields})


async def logout(uid: str) -> None:
    await call("POST", f"/users/{uid}/logout")


async def delete(uid: str) -> None:
    await call("DELETE", f"/users/{uid}")
