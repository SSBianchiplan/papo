"""Skills: upload (.md e .zip), versões, ativação por agente/conversa, uso pelo agente, compartilhamento e isolamento."""
from __future__ import annotations

import io
import zipfile
from typing import Any

import httpx
from test_flow import FakeLLM, H, run_jobs

SKILL_MD = """---
name: relatorio-executivo
description: Monta relatório executivo com resumo, números e próximos passos. Use quando pedirem relatório para diretoria.
---
# Relatório executivo
Sempre comece pelo resumo em 3 linhas. Depois a tabela de números.
"""


def pack(files: dict[str, str]) -> bytes:
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        for p, c in files.items():
            z.writestr(p, c)
    return b.getvalue()


async def up(client: httpx.AsyncClient, user: str, name: str, data: bytes) -> httpx.Response:
    return await client.post("/api/skills", headers=H(user), files={"file": (name, data, "application/octet-stream")})


async def test_upload_md_e_zip_com_varias_skills(client: httpx.AsyncClient) -> None:
    r = await up(client, "sk1", "SKILL.md", SKILL_MD.encode())
    assert r.status_code == 201 and r.json()["created"] == ["relatorio-executivo"] and len(r.json()["ids"]) == 1

    z = pack({
        "minhas/glx-dba/SKILL.md": "---\nname: glx-dba-hard\ndescription: DBA PostgreSQL\n---\nUse EXPLAIN.",
        "minhas/glx-dba/references/vacuum.md": "VACUUM detalhado",
        "minhas/glx-dba/scripts/check.sql": "SELECT 1;",
        "minhas/glx-dba/imagem.png": "binario",
        "minhas/pcp/SKILL.md": "# PCP\n\nPlanejamento e controle da produção, sem cabeçalho.",
        "../fora/SKILL.md": "---\nname: invasora\ndescription: x\n---\ncorpo",
        "__MACOSX/minhas/._SKILL.md": "lixo",
    })
    r = await up(client, "sk1", "pacote.skill", z)          # .skill é zip: mesmo leitor
    assert r.status_code == 201, r.text
    assert sorted(r.json()["created"]) == ["glx-dba-hard", "pcp"]

    lst = {s["name"]: s for s in (await client.get("/api/skills", headers=H("sk1"))).json()}
    assert set(lst) == {"relatorio-executivo", "glx-dba-hard", "pcp"}
    assert lst["glx-dba-hard"]["files"] == 2 and lst["pcp"]["description"].startswith("Planejamento")
    det = (await client.get(f"/api/skills/{lst['glx-dba-hard']['id']}", headers=H("sk1"))).json()
    assert det["body"] == "Use EXPLAIN." and det["file_paths"] == ["references/vacuum.md", "scripts/check.sql"]

    # mesmo nome de novo: nova versão, não duplica
    r = await up(client, "sk1", "SKILL.md", SKILL_MD.replace("3 linhas", "2 linhas").encode())
    assert r.json()["created"] == [] and r.json()["updated"] == ["relatorio-executivo"]
    v = next(s for s in (await client.get("/api/skills", headers=H("sk1"))).json() if s["name"] == "relatorio-executivo")
    assert v["version"] == 2

    assert (await up(client, "sk1", "nada.zip", pack({"leia.txt": "x"}))).status_code == 422
    assert (await up(client, "sk1", "x.exe", b"MZ")).status_code == 422
    assert (await up(client, "sk1", "ruim.zip", b"nao e zip")).status_code == 422


async def test_agente_usa_skill_ativa_sob_demanda(client: httpx.AsyncClient, jobs: list[Any]) -> None:
    await up(client, "sk2", "SKILL.md", SKILL_MD.encode())
    sid = (await client.get("/api/skills", headers=H("sk2"))).json()[0]["id"]
    a = (await client.post("/api/agents", json={"name": "Diretoria"}, headers=H("sk2"))).json()["id"]
    conv = (await client.post("/api/conversations", json={"kind": "dm", "agent_id": a}, headers=H("sk2"))).json()["id"]

    # sem ativar: a skill não aparece para o agente
    await client.post(f"/api/conversations/{conv}/messages", json={"body": "oi"}, headers=H("sk2"))
    llm = FakeLLM([("text", "Olá")])
    await run_jobs(jobs, llm)
    assert "relatorio-executivo" not in llm.calls[0]["system"] and "usar_skill" not in {t["name"] for t in llm.calls[0]["tools"]}

    assert (await client.put(f"/api/agents/{a}/skills", json={"skill_ids": [sid]}, headers=H("sk2"))).json()["skill_ids"] == [sid]
    await client.post(f"/api/conversations/{conv}/messages", json={"body": "faça o relatório da diretoria"}, headers=H("sk2"))
    llm = FakeLLM([("tool", "usar_skill", {"nome": "relatorio-executivo"}), ("text", "Resumo: ...")])
    await run_jobs(jobs, llm)
    assert "relatorio-executivo: Monta relatório executivo" in llm.calls[0]["system"]
    result = llm.calls[1]["messages"][-1]["content"][0]["content"]
    assert "Sempre comece pelo resumo em 3 linhas" in result
    last = (await client.get(f"/api/conversations/{conv}/messages", headers=H("sk2"))).json()[-1]
    assert any("Usou a skill relatorio-executivo" in st["text"] for st in last["steps"])

    # desativada na biblioteca: some do agente
    await client.patch(f"/api/skills/{sid}", json={"enabled": False}, headers=H("sk2"))
    await client.post(f"/api/conversations/{conv}/messages", json={"body": "de novo"}, headers=H("sk2"))
    llm = FakeLLM([("text", "ok")])
    await run_jobs(jobs, llm)
    assert "relatorio-executivo" not in llm.calls[0]["system"]


async def test_skill_por_conversa(client: httpx.AsyncClient, jobs: list[Any]) -> None:
    await up(client, "sk3", "SKILL.md", SKILL_MD.encode())
    sid = (await client.get("/api/skills", headers=H("sk3"))).json()[0]["id"]
    a = (await client.post("/api/agents", json={"name": "Geral"}, headers=H("sk3"))).json()["id"]
    conv = (await client.post("/api/conversations", json={"kind": "dm", "agent_id": a}, headers=H("sk3"))).json()["id"]
    assert (await client.put(f"/api/conversations/{conv}/skills", json={"skill_ids": [sid]}, headers=H("sk3"))).status_code == 200
    await client.post(f"/api/conversations/{conv}/messages", json={"body": "oi"}, headers=H("sk3"))
    llm = FakeLLM([("text", "Olá")])
    await run_jobs(jobs, llm)
    assert "relatorio-executivo" in llm.calls[0]["system"]


async def test_compartilhar_e_isolamento(client: httpx.AsyncClient) -> None:
    await up(client, "sk4", "SKILL.md", SKILL_MD.encode())
    sid = (await client.get("/api/skills", headers=H("sk4"))).json()[0]["id"]
    assert (await client.get("/api/skills", headers=H("sk5"))).json() == []                     # privada
    assert (await client.get(f"/api/skills/{sid}", headers=H("sk5"))).status_code == 404
    a5 = (await client.post("/api/agents", json={"name": "X"}, headers=H("sk5"))).json()["id"]
    assert (await client.put(f"/api/agents/{a5}/skills", json={"skill_ids": [sid]}, headers=H("sk5"))).status_code == 404
    assert (await client.patch(f"/api/skills/{sid}", json={"shared": True}, headers=H("sk4"))).status_code == 403   # só admin

    await up(client, "admin", "SKILL.md", SKILL_MD.replace("relatorio-executivo", "padrao-casa").encode())
    shared = next(s for s in (await client.get("/api/skills", headers=H("admin"))).json() if s["name"] == "padrao-casa")
    assert (await client.patch(f"/api/skills/{shared['id']}", json={"shared": True}, headers=H("admin"))).json()["shared"] is True
    seen = (await client.get("/api/skills", headers=H("sk5"))).json()
    assert [s["name"] for s in seen] == ["padrao-casa"] and seen[0]["mine"] is False
    assert (await client.put(f"/api/agents/{a5}/skills", json={"skill_ids": [shared["id"]]}, headers=H("sk5"))).status_code == 200
    assert (await client.delete(f"/api/skills/{shared['id']}", headers=H("sk5"))).status_code == 403
    assert (await client.patch(f"/api/skills/{shared['id']}", json={"enabled": False}, headers=H("sk5"))).status_code == 403
    await client.patch(f"/api/skills/{shared['id']}", json={"shared": False}, headers=H("admin"))


async def test_skill_que_entrou_como_arquivo_vira_skill(client: httpx.AsyncClient, jobs: list[Any], app_conn: Any) -> None:
    a = (await client.post("/api/agents", json={"name": "KPI"}, headers=H("sk6"))).json()["id"]
    pacote = pack({"kpi/SKILL.md": SKILL_MD.replace("relatorio-executivo", "kpi-mega-library")})
    # upload novo de .skill como documento é recusado com instrução
    r = await client.post(f"/api/agents/{a}/documents", headers=H("sk6"), files={"file": ("kpi.skill", pacote, "application/octet-stream")})
    assert r.status_code == 422 and "Skills" in r.json()["hint"]
    # o que já entrou antes (como no print) é convertido: importa, ativa no agente e sai da base
    r = await client.post(f"/api/agents/{a}/documents", headers=H("sk6"), files={"file": ("kpi.zip", pacote, "application/zip")})
    did = r.json()["id"]
    await run_jobs(jobs)
    r = await client.post(f"/api/documents/{did}/as-skill", headers=H("sk6"))
    assert r.status_code == 200 and r.json()["created"] == ["kpi-mega-library"]
    assert (await client.get(f"/api/agents/{a}/skills", headers=H("sk6"))).json()["skill_ids"] == r.json()["ids"]
    assert (await client.get(f"/api/agents/{a}/documents", headers=H("sk6"))).json() == []
    assert (await client.post(f"/api/documents/{did}/as-skill", headers=H("sk7"))).status_code == 404
