"""Multiusuário: gestão de contas (Keycloak falso em memória) e regras de master/administrador."""
from __future__ import annotations

import uuid
from typing import Any

import httpx
import pytest
from test_flow import H


@pytest.fixture
def kc(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    from app import kcadmin

    db: dict[str, Any] = {"users": {}, "roles": {"papo-admin": set(), "papo-master": set()}, "logouts": []}
    for sub, roles in (("master", {"papo-master"}), ("admin", {"papo-admin"}), ("comum", set())):
        db["users"][sub] = {"id": sub, "username": sub, "email": f"{sub}@x.io", "firstName": sub.title(), "enabled": True}
        for r in roles:
            db["roles"][r].add(sub)

    async def users() -> list[dict[str, Any]]:
        return list(db["users"].values())

    async def user(uid: str) -> dict[str, Any]:
        from app.errors import NotFound
        if uid not in db["users"]:
            raise NotFound("Conta não encontrada.")
        return db["users"][uid]

    async def roles(uid: str) -> set[str]:
        return {r for r, m in db["roles"].items() if uid in m}

    async def roles_of(uids: list[str]) -> dict[str, set[str]]:
        return {u: await roles(u) for u in uids}

    async def set_role(uid: str, role: str, on: bool) -> None:
        (db["roles"][role].add if on else db["roles"][role].discard)(uid)

    async def create(email: str, name: str) -> str:
        uid = uuid.uuid4().hex
        db["users"][uid] = {"id": uid, "username": email, "email": email, "firstName": name, "enabled": True, "requiredActions": ["UPDATE_PASSWORD"]}
        return uid

    async def reset_password(uid: str) -> str:
        return "Temp-Senha-123!"

    async def update(uid: str, **f: Any) -> None:
        db["users"][uid].update(f)

    async def logout(uid: str) -> None:
        db["logouts"].append(uid)

    async def delete(uid: str) -> None:
        db["users"].pop(uid)

    for n, f in dict(users=users, user=user, roles=roles, roles_of=roles_of, set_role=set_role, create=create, reset_password=reset_password,
                     update=update, logout=logout, delete=delete).items():
        monkeypatch.setattr(kcadmin, n, f)
    return db


async def test_lista_so_para_admin_e_me_mostra_master(client: httpx.AsyncClient, kc: dict[str, Any]) -> None:
    assert (await client.get("/api/admin/accounts", headers=H("comum"))).status_code == 403
    me = (await client.get("/api/me", headers=H("master"))).json()
    assert me["is_master"] and me["is_admin"]
    await client.post("/api/agents", json={"name": "Ana"}, headers=H("comum"))
    accs = (await client.get("/api/admin/accounts", headers=H("admin"))).json()
    assert accs[0]["username"] == "master" and accs[0]["is_master"]
    comum = next(a for a in accs if a["username"] == "comum")
    assert comum["agents"] == 1 and not comum["is_admin"]


async def test_so_master_cria_e_promove_admin(client: httpx.AsyncClient, kc: dict[str, Any]) -> None:
    r = await client.post("/api/admin/accounts", json={"email": "novo@x.io", "name": "Novo Admin", "is_admin": True}, headers=H("admin"))
    assert r.status_code == 403
    r = await client.post("/api/admin/accounts", json={"email": "novo@x.io", "name": "Nova Pessoa"}, headers=H("admin"))
    assert r.status_code == 201 and r.json()["temp_password"] and r.json()["account"]["must_change_password"]
    kid = r.json()["account"]["id"]
    assert (await client.patch(f"/api/admin/accounts/{kid}", json={"is_admin": True}, headers=H("admin"))).status_code == 403
    assert (await client.patch(f"/api/admin/accounts/{kid}", json={"is_admin": True}, headers=H("master"))).json()["is_admin"]
    assert (await client.post("/api/admin/accounts", json={"email": "ruim", "name": "x"}, headers=H("master"))).status_code == 422


async def test_ninguem_mexe_no_master_nem_em_si(client: httpx.AsyncClient, kc: dict[str, Any]) -> None:
    for body in ({"enabled": False}, {"is_admin": False}):
        assert (await client.patch("/api/admin/accounts/master", json=body, headers=H("admin"))).status_code == 403
    assert (await client.delete("/api/admin/accounts/master", headers=H("admin"))).status_code == 403
    assert (await client.patch("/api/admin/accounts/admin", json={"enabled": False}, headers=H("admin"))).status_code == 403
    assert (await client.delete("/api/admin/accounts/master", headers=H("master"))).status_code == 403
    assert (await client.delete("/api/admin/accounts/admin", headers=H("admin"))).status_code == 403   # a si mesmo
    assert (await client.post("/api/admin/accounts/admin/password", headers=H("comum"))).status_code == 403


async def test_desativar_e_excluir_apagam_sessao_e_dados(client: httpx.AsyncClient, kc: dict[str, Any], memory_storage: dict[str, bytes]) -> None:
    await client.post("/api/agents", json={"name": "Beto"}, headers=H("comum"))
    uid = (await client.get("/api/me", headers=H("comum"))).json()["id"]
    memory_storage[f"{uid}/doc/x.pdf"] = b"%PDF"
    r = await client.patch("/api/admin/accounts/comum", json={"enabled": False}, headers=H("admin"))
    assert r.json()["enabled"] is False and "comum" in kc["logouts"]
    assert (await client.delete("/api/admin/accounts/comum", headers=H("admin"))).status_code == 204
    assert "comum" not in kc["users"] and not any(k.startswith(f"{uid}/") for k in memory_storage)
    accs = (await client.get("/api/admin/accounts", headers=H("master"))).json()
    assert all(a["username"] != "comum" for a in accs)
