"""Docs do hub: regras de leitura (nada de segredo, nada fora da raiz), gateway, leitor remoto, catálogo, API e agente."""
from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path
from typing import Any

import httpx
import pytest
from test_flow import FakeLLM, H, run_jobs

TOKEN = "gw-token-de-teste"


@pytest.fixture
def hubtree(tmp_path: Path) -> Path:
    opt = tmp_path / "opt"
    (opt / "peoples" / "docs").mkdir(parents=True)
    (opt / "peoples" / "docs" / "manual.md").write_text("# Manual do Peoples\n\nFérias são aprovadas pelo gestor em até 5 dias.")
    (opt / "peoples" / "README.md").write_text("Sistema de RH do hub.")
    (opt / "peoples" / ".env").write_text("SENHA=123")
    (opt / "peoples" / "segredos").mkdir()
    (opt / "peoples" / "segredos" / "chaves.md").write_text("não pode")
    (opt / "peoples" / "senhas-banco.md").write_text("não pode")
    (opt / "peoples" / "node_modules" / "x").mkdir(parents=True)
    (opt / "peoples" / "node_modules" / "x" / "README.md").write_text("lixo")
    (opt / "peoples" / ".git").mkdir()
    (opt / "peoples" / ".git" / "HEAD.md").write_text("lixo")
    (opt / "peoples" / "app.py").write_text("print('código não é documento')")
    (opt / "crm").mkdir()
    (opt / "crm" / "vendas.csv").write_text("regiao;valor\nSul;1300\nNorte;300\nSul;200\n")
    (opt / "crm" / "requirements.txt").write_text("fastapi")              # ruído de projeto
    (opt / "crm" / "LICENSE.md").write_text("MIT")
    (opt / "crm" / "pkg.egg-info").mkdir()
    (opt / "crm" / "pkg.egg-info" / "PKG-INFO.md").write_text("ruído")
    outside = tmp_path / "fora.md"
    outside.write_text("fora da raiz")
    os.symlink(outside, opt / "crm" / "atalho.md")
    return opt


@pytest.fixture
def gateway(hubtree: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    """Gateway de verdade (ASGI) no lugar do serviço hubgw; o cliente do Papo fala com ele."""
    from app import config
    from app.hub import client

    monkeypatch.setenv("HUBGW_TOKEN", TOKEN)
    monkeypatch.setenv("HUBGW_LOCAL_ROOTS", f"opt={hubtree}")
    config.get_settings.cache_clear()
    from app.hubgw import app as gw

    def fake_client(timeout: float = 120) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.ASGITransport(app=gw), base_url="http://hubgw", headers={"x-hubgw-token": TOKEN})

    monkeypatch.setattr(client, "_c", fake_client)
    yield gw
    config.get_settings.cache_clear()


def test_regras_bloqueiam_segredo_codigo_e_fuga(hubtree: Path) -> None:
    from app.hub import rules

    found = {p for p, _, _ in rules.walk(str(hubtree), set(rules.DEFAULT_EXT))}
    assert found == {"peoples/docs/manual.md", "peoples/README.md", "crm/vendas.csv"}
    for bad in ("../fora.md", "peoples/../../fora.md", "../../etc/passwd"):     # normalizado de volta para dentro da raiz
        assert rules.resolve(str(hubtree), bad).startswith(str(hubtree.resolve()) + os.sep)
    with pytest.raises(ValueError):
        rules.clean_rel("..")
    with pytest.raises(PermissionError):
        rules.resolve(str(hubtree), "crm/atalho.md")              # symlink apontando para fora
    assert not rules.allowed("peoples/.env", rules.DEFAULT_EXT) and not rules.allowed("a/segredos/x.md", rules.DEFAULT_EXT)


async def test_gateway_exige_token_e_so_le(gateway: Any, client: httpx.AsyncClient) -> None:
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=gateway), base_url="http://gw") as c:
        assert (await c.get("/s/00000000-0000-0000-0000-000000000000/scan")).status_code == 401
        assert (await c.post("/s/x/scan", headers={"x-hubgw-token": TOKEN})).status_code == 405
        assert (await c.get("/healthz")).status_code == 200


async def _source(client: httpx.AsyncClient, name: str) -> str:
    r = await client.post("/api/hub/sources", headers=H("admin"), json={"name": name, "label": "VPS teste", "kind": "local", "roots": ["opt"]})
    assert r.status_code == 201, r.text
    return str(r.json()["id"])


async def test_catalogo_previa_download_e_visibilidade(gateway: Any, client: httpx.AsyncClient) -> None:
    sid = await _source(client, "vps-cat")
    assert (await client.post(f"/api/hub/sources/{sid}/test", headers=H("admin"))).json()["ok"] is True
    r = await client.post(f"/api/hub/sources/{sid}/index", headers=H("admin"))
    assert r.json()["files"] == 3
    files = (await client.get("/api/hub/files", headers=H("admin"))).json()
    assert {f["path"] for f in files} == {"opt/peoples/docs/manual.md", "opt/peoples/README.md", "opt/crm/vendas.csv"}
    hits = (await client.get("/api/hub/files?q=peoples manual", headers=H("admin"))).json()      # busca por nome e pasta
    assert [f["path"] for f in hits] == ["opt/peoples/docs/manual.md"]
    st = (await client.get("/api/hub/stats", headers=H("admin"))).json()
    assert st["files"] == 3 and {e["key"] for e in st["by_ext"]} == {"md", "csv"}

    t = (await client.get("/api/hub/file/text", params={"source_id": sid, "path": "opt/peoples/docs/manual.md"}, headers=H("admin"))).json()
    assert "Férias são aprovadas" in t["text"]
    raw = await client.get("/api/hub/file/raw", params={"source_id": sid, "path": "opt/crm/vendas.csv"}, headers=H("admin"))
    assert raw.status_code == 200 and raw.content.startswith(b"regiao;valor") and raw.headers["content-security-policy"] == "sandbox"
    # fora do índice / segredo: nem a API nem o gateway entregam
    assert (await client.get("/api/hub/file/text", params={"source_id": sid, "path": "opt/peoples/.env"}, headers=H("admin"))).status_code == 404

    # usuário comum: não vê até o administrador liberar
    assert (await client.get("/api/hub/sources", headers=H("hub-u"))).json() == []
    assert (await client.get("/api/hub/files", headers=H("hub-u"))).json() == []
    assert (await client.post("/api/hub/sources", headers=H("hub-u"), json={"name": "x1", "label": "x", "kind": "local"})).status_code == 403
    await client.put(f"/api/hub/sources/{sid}", headers=H("admin"), json={"name": "vps-cat", "label": "VPS teste", "kind": "local",
                                                                          "roots": ["opt"], "visible_all": True})
    assert len((await client.get("/api/hub/files", headers=H("hub-u"))).json()) == 3
    await client.delete(f"/api/hub/sources/{sid}", headers=H("admin"))


async def test_nada_e_copiado_para_o_papo(gateway: Any, client: httpx.AsyncClient, memory_storage: dict[str, bytes], app_conn: Any) -> None:
    sid = await _source(client, "vps-copia")
    await client.post(f"/api/hub/sources/{sid}/index", headers=H("admin"))
    await client.get("/api/hub/file/text", params={"source_id": sid, "path": "opt/peoples/docs/manual.md"}, headers=H("admin"))
    assert memory_storage == {}                                      # nenhum byte no storage
    with app_conn() as c:
        cols = {r[0] for r in c.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'hub_file'")}
    assert cols == {"source_id", "path", "ext", "size_bytes", "mtime", "seen_at"}          # catálogo só tem metadados
    await client.delete(f"/api/hub/sources/{sid}", headers=H("admin"))


async def test_agente_le_o_hub_na_origem(gateway: Any, client: httpx.AsyncClient, jobs: list[Any]) -> None:
    sid = await _source(client, "vps-agente")
    await client.post(f"/api/hub/sources/{sid}/index", headers=H("admin"))
    a = (await client.post("/api/agents", json={"name": "RH"}, headers=H("admin"))).json()["id"]
    # só a pasta do Peoples
    r = await client.put(f"/api/hub/agents/{a}", headers=H("admin"), json={"links": [{"source_id": sid, "prefix": "opt/peoples"}]})
    assert r.status_code == 200 and r.json()["links"][0]["prefix"] == "opt/peoples"
    conv = (await client.post("/api/conversations", json={"kind": "dm", "agent_id": a}, headers=H("admin"))).json()["id"]
    await client.post(f"/api/conversations/{conv}/messages", json={"body": "como funcionam as férias?"}, headers=H("admin"))
    llm = FakeLLM([("tool", "hub_buscar", {"consulta": "manual"}),
                   ("tool", "hub_ler", {"fonte": "VPS teste", "caminho": "opt/peoples/docs/manual.md"}),
                   ("tool", "hub_ler", {"fonte": "VPS teste", "caminho": "opt/crm/vendas.csv", "operacao": "agrupar",
                                        "agrupar_por": ["regiao"], "metrica": {"coluna": "valor", "funcao": "soma"}}),
                   ("text", "Aprovadas pelo gestor em até 5 dias.")])
    await run_jobs(jobs, llm)
    assert "VPS teste · pasta opt/peoples" in llm.calls[0]["system"]
    assert {"hub_buscar", "hub_ler"} <= {t["name"] for t in llm.calls[0]["tools"]}
    found = llm.calls[1]["messages"][-1]["content"][0]["content"]
    assert "opt/peoples/docs/manual.md" in found and "vendas.csv" not in found
    read = llm.calls[2]["messages"][-1]["content"][0]["content"]
    assert "Férias são aprovadas" in read
    denied = llm.calls[3]["messages"][-1]["content"][0]
    assert denied["is_error"] and "não está nas fontes" in denied["content"]          # fora da pasta ligada ao agente
    await client.delete(f"/api/hub/sources/{sid}", headers=H("admin"))


async def test_leitor_remoto_token_ip_e_somente_leitura(hubtree: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HUBREADER_TOKEN", "r-token")
    monkeypatch.setenv("HUBREADER_ROOTS", f"opt={hubtree}")
    monkeypatch.setenv("HUBREADER_ALLOW_IPS", "127.0.0.1")
    hr = str(Path(__file__).resolve().parents[2] / "hubreader")
    sys.path.insert(0, hr)
    try:
        main = importlib.import_module("main")
        main = importlib.reload(main)
        t = httpx.ASGITransport(app=main.app, client=("127.0.0.1", 5000))
        async with httpx.AsyncClient(transport=t, base_url="https://hr") as c:
            assert (await c.get("/scan")).status_code == 401
            ok = {"Authorization": "Bearer r-token"}
            scan = (await c.get("/scan", headers=ok)).json()
            assert {p for p, _, _ in scan["opt"]} == {"peoples/docs/manual.md", "peoples/README.md", "crm/vendas.csv"}
            assert (await c.get("/file", params={"root": "opt", "path": "peoples/README.md"}, headers=ok)).text == "Sistema de RH do hub."
            assert (await c.get("/file", params={"root": "opt", "path": "peoples/.env"}, headers=ok)).status_code == 404
            assert (await c.get("/file", params={"root": "opt", "path": "../fora.md"}, headers=ok)).status_code in (403, 404)
            assert (await c.get("/file", params={"root": "opt", "path": "crm/atalho.md"}, headers=ok)).status_code in (403, 404)
        t2 = httpx.ASGITransport(app=main.app, client=("8.8.8.8", 5000))
        async with httpx.AsyncClient(transport=t2, base_url="https://hr") as c:
            assert (await c.get("/scan", headers={"Authorization": "Bearer r-token"})).status_code == 403
    finally:
        sys.path.remove(hr)
        sys.modules.pop("main", None)
        sys.modules.pop("rules", None)
