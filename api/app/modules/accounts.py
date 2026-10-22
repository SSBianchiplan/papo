"""Gestão de contas (multiusuário): administradores listam, criam, ativam/desativam, trocam a senha e excluem contas.

Regras: só o master promove ou rebaixa administradores; ninguém desativa, rebaixa ou exclui o master nem a si mesmo;
excluir um administrador também é só do master. Cada conta continua isolada pelo RLS: a lista mostra só contagens.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException
from sqlalchemy import text

from .. import costs, kcadmin, storage
from ..auth import Admin, CurrentUser
from ..config import get_settings
from ..db import rows, scalar, tx
from ..schemas import AccountIn, AccountOut, AccountPatch, AccountSecret

router = APIRouter(prefix="/api/admin/accounts", tags=["contas"])
log = logging.getLogger("papo.accounts")


def _deny(msg: str) -> HTTPException:
    return HTTPException(403, msg)


async def _papo_stats(user: CurrentUser) -> tuple[dict[str, dict[str, Any]], dict[UUID, float]]:
    async with tx(user.id) as conn:
        stats = {r["sub"]: r for r in await rows(conn, "SELECT * FROM papo_user_stats()")}
        prices = await costs.load_prices(conn)
        month: dict[UUID, float] = {}
        for r in await costs.rollup(conn, costs.month_start()):
            month[r["user_id"]] = month.get(r["user_id"], 0.0) + costs.cost_usd(r["model"], int(r["input_tokens"]), int(r["output_tokens"]), prices)
    return stats, month


def _out(u: dict[str, Any], roles: set[str], st: dict[str, Any] | None, month: dict[UUID, float]) -> AccountOut:
    s = get_settings()
    is_master = s.master_role in roles
    name = " ".join(x for x in (u.get("firstName"), u.get("lastName")) if x) or (st or {}).get("display_name") or u["username"]
    created = datetime.fromtimestamp(u["createdTimestamp"] / 1000) if u.get("createdTimestamp") else None
    pid = st["user_id"] if st else None
    return AccountOut(id=u["id"], username=u["username"], email=u.get("email"), name=name, enabled=bool(u.get("enabled")),
                      is_admin=is_master or s.admin_role in roles, is_master=is_master, created_at=created, papo_id=pid,
                      conversations=int(st["conversations"]) if st else 0, agents=int(st["agents"]) if st else 0,
                      documents=int(st["documents"]) if st else 0, bytes=int(st["bytes"]) if st else 0,
                      month_cost_usd=round(month.get(pid, 0.0), 4) if pid else 0.0, last_activity=st["last_activity"] if st else None,
                      must_change_password="UPDATE_PASSWORD" in (u.get("requiredActions") or []))


async def _one(user: CurrentUser, kid: str) -> tuple[AccountOut, dict[str, Any]]:
    u = await kcadmin.user(kid)
    stats, month = await _papo_stats(user)
    acc = _out(u, await kcadmin.roles(kid), stats.get(kid), month)
    return acc, u


@router.get("", response_model=list[AccountOut])
async def list_accounts(user: CurrentUser = Admin) -> list[AccountOut]:
    us = [u for u in await kcadmin.users() if not u.get("serviceAccountClientLink") and not u["username"].startswith("service-account-")]
    rs = await kcadmin.roles_of([u["id"] for u in us])
    stats, month = await _papo_stats(user)
    out = [_out(u, rs[u["id"]], stats.get(u["id"]), month) for u in us]
    return sorted(out, key=lambda a: (not a.is_master, not a.is_admin, a.name.lower()))


@router.post("", response_model=AccountSecret, status_code=201)
async def create_account(body: AccountIn, user: CurrentUser = Admin) -> AccountSecret:
    if body.is_admin and not user.is_master:
        raise _deny("Só o administrador master cria administradores.")
    kid = await kcadmin.create(body.email, body.name)
    pw = await kcadmin.reset_password(kid)
    if body.is_admin:
        await kcadmin.set_role(kid, get_settings().admin_role, True)
    log.info("conta criada por %s (admin=%s)", user.sub, body.is_admin)
    acc, _ = await _one(user, kid)
    return AccountSecret(account=acc, temp_password=pw)


@router.patch("/{kid}", response_model=AccountOut)
async def patch_account(kid: str, body: AccountPatch, user: CurrentUser = Admin) -> AccountOut:
    acc, _ = await _one(user, kid)
    if acc.is_master and kid != user.sub:
        raise _deny("A conta master só é alterada pelo próprio master.")
    if body.is_admin is not None and body.is_admin != acc.is_admin:
        if not user.is_master:
            raise _deny("Só o administrador master promove ou rebaixa administradores.")
        if acc.is_master:
            raise _deny("O master é sempre administrador.")
        await kcadmin.set_role(kid, get_settings().admin_role, body.is_admin)
    if body.enabled is not None and body.enabled != acc.enabled:
        if kid == user.sub or acc.is_master:
            raise _deny("Você não pode desativar a sua própria conta nem a do master.")
        if acc.is_admin and not user.is_master:
            raise _deny("Só o master desativa administradores.")
        await kcadmin.update(kid, enabled=body.enabled)
        if not body.enabled:
            await kcadmin.logout(kid)           # encerra as sessões abertas; o token em uso expira em minutos
    if body.name:
        first, _, last = body.name.strip().partition(" ")
        await kcadmin.update(kid, firstName=first, lastName=last)
    return (await _one(user, kid))[0]


@router.post("/{kid}/password", response_model=AccountSecret)
async def reset_password(kid: str, user: CurrentUser = Admin) -> AccountSecret:
    acc, _ = await _one(user, kid)
    if (acc.is_master and kid != user.sub) or (acc.is_admin and not user.is_master and kid != user.sub):
        raise _deny("Só o master troca a senha de administradores.")
    pw = await kcadmin.reset_password(kid)
    await kcadmin.update(kid, requiredActions=["UPDATE_PASSWORD"])
    await kcadmin.logout(kid)
    return AccountSecret(account=(await _one(user, kid))[0], temp_password=pw)


@router.delete("/{kid}", status_code=204, response_model=None)
async def delete_account(kid: str, user: CurrentUser = Admin) -> None:
    acc, _ = await _one(user, kid)
    if kid == user.sub or acc.is_master:
        raise _deny("Você não pode excluir a sua própria conta nem a do master.")
    if acc.is_admin and not user.is_master:
        raise _deny("Só o master exclui administradores.")
    await kcadmin.logout(kid)
    if acc.papo_id:                              # dados do Papo: apaga como o próprio dono (RLS) e os arquivos dele no storage
        async with tx(acc.papo_id) as conn:
            await conn.execute(text("DELETE FROM app_user WHERE id = :u"), {"u": acc.papo_id})
            assert await scalar(conn, "SELECT count(*) FROM app_user WHERE id = :u", u=acc.papo_id) == 0
        await storage.remove_prefix(f"{acc.papo_id}/")
    await kcadmin.delete(kid)
    log.info("conta excluída por %s", user.sub)
