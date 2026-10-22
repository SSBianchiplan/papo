"""Arquivos gerados pelo agente, memória da conversa e gerenciador de arquivos."""
from __future__ import annotations

from typing import Any

import httpx
import pytest
from test_flow import FakeLLM, H, run_jobs, setup_agent_with_sheet


async def _dm(client: httpx.AsyncClient, user: str, name: str = "Redator") -> str:
    a = (await client.post("/api/agents", json={"name": name}, headers=H(user))).json()
    return str((await client.post("/api/conversations", json={"kind": "dm", "agent_id": a["id"]}, headers=H(user))).json()["id"])


async def _say(client: httpx.AsyncClient, jobs: list[Any], user: str, conv: str, text: str, script: list[tuple[Any, ...]]) -> FakeLLM:
    r = await client.post(f"/api/conversations/{conv}/messages", json={"body": text}, headers=H(user))
    assert r.status_code == 201, r.text
    llm = FakeLLM(script)
    await run_jobs(jobs, llm)
    return llm


async def test_agente_gera_html_no_design_system_e_vira_contexto(client: httpx.AsyncClient, jobs: list[Any]) -> None:
    conv = await _dm(client, "gabi")
    conteudo = "## Resumo\n\n| Região | Total |\n|---|---|\n| Sul | 1.300 |\n\n<script>alert(1)</script> [x](javascript:alert(2))"
    await _say(client, jobs, "gabi", conv, "Faça um relatório em HTML", [
        ("tool", "gerar_arquivo", {"formato": "html", "nome": "relatorio-vendas", "titulo": "Relatório de vendas", "conteudo": conteudo,
                                   "tema": {"primaria": "#E4572E"}, "fonte": "Inter"}),
        ("text", "Pronto: o relatório traz o total por região."),
    ])
    msgs = (await client.get(f"/api/conversations/{conv}/messages", headers=H("gabi"))).json()
    file_msg, answer = msgs[-2], msgs[-1]
    assert file_msg["author"] == "agent" and file_msg["document"]["filename"] == "relatorio-vendas.html"
    assert file_msg["document"]["origin"] == "agent" and file_msg["document"]["status"] == "ready"
    assert answer["body"].startswith("Pronto")

    r = await client.get(f"/api/documents/{file_msg['document']['id']}/file", headers=H("gabi"))
    assert r.status_code == 200 and r.headers["content-security-policy"] == "sandbox" and "attachment" in r.headers["content-disposition"]
    page = r.text
    assert "<table>" in page and "--accent:#E4572E" in page and '"Inter"' in page and "Gerado por Redator" in page
    assert "<script>" not in page and "&lt;script&gt;" in page and "javascript:" not in page     # HTML do modelo não executa

    # na próxima pergunta o arquivo gerado já é contexto que o agente consegue ler
    llm = await _say(client, jobs, "gabi", conv, "o que tinha no relatório?", [("text", "Tinha o total do Sul.")])
    assert "relatorio-vendas.html" in llm.calls[0]["system"]
    assert any("relatorio-vendas.html" in str(m["content"]) for m in llm.calls[0]["messages"])

    # e o outro usuário não baixa
    assert (await client.get(f"/api/documents/{file_msg['document']['id']}/file", headers=H("hugo"))).status_code == 404


async def test_agente_gera_markdown(client: httpx.AsyncClient, jobs: list[Any]) -> None:
    conv = await _dm(client, "iara")
    await _say(client, jobs, "iara", conv, "me dá em .md", [
        ("tool", "gerar_arquivo", {"formato": "md", "nome": "ata", "titulo": "Ata da reunião", "conteudo": "# Ata da reunião\n\n- item 1"}),
        ("tool", "gerar_arquivo", {"formato": "md", "nome": "ata.md", "titulo": "Ata 2", "conteudo": "- item 2"}),
        ("text", "Seguem as atas."),
    ])
    docs = [m["document"] for m in (await client.get(f"/api/conversations/{conv}/messages", headers=H("iara"))).json() if m["document"]]
    assert [d["filename"] for d in docs] == ["ata.md", "ata.md"]
    text = (await client.get(f"/api/documents/{docs[0]['id']}/file", headers=H("iara"))).text
    assert text.startswith("# Ata da reunião\n\n_Gerado por Redator") and text.count("# Ata da reunião") == 1


async def test_busca_no_historico_antigo(client: httpx.AsyncClient, jobs: list[Any]) -> None:
    conv = await _dm(client, "joao")
    await _say(client, jobs, "joao", conv, "O código do contrato é XPTO-778, guarde.", [("text", "Anotado.")])
    llm = await _say(client, jobs, "joao", conv, "qual era o código?", [
        ("tool", "buscar_na_conversa", {"consulta": "codigo contrato"}),
        ("text", "Era XPTO-778."),
    ])
    result = llm.calls[1]["messages"][-1]["content"][0]["content"]
    assert "XPTO-778" in result and '"autor": "usuário"' in result


async def test_gerenciador_lista_libera_espaco_e_limpa(client: httpx.AsyncClient, jobs: list[Any]) -> None:
    agent, conv = await setup_agent_with_sheet(client, jobs, "kai")
    up = (await client.post(f"/api/conversations/{conv}/attachments", headers=H("kai"),
                            files={"file": ("nota.txt", b"texto de teste para o gerenciador", "text/plain")})).json()["document"]
    await run_jobs(jobs)
    await _say(client, jobs, "kai", conv, "veja a nota", [("text", "Vi.")])
    msgs = (await client.get(f"/api/conversations/{conv}/messages", headers=H("kai"))).json()
    sent = await client.post(f"/api/conversations/{conv}/messages", json={"body": "anexo", "document_id": up["id"]}, headers=H("kai"))
    assert sent.status_code == 201, sent.text
    await run_jobs(jobs, FakeLLM([("text", "ok")]))
    # uma cópia idêntica na base do agente
    dup = (await client.post(f"/api/agents/{agent}/documents", headers=H("kai"),
                             files={"file": ("nota-copia.txt", b"texto de teste para o gerenciador", "text/plain")})).json()
    await run_jobs(jobs)

    lst = (await client.get("/api/documents", headers=H("kai"))).json()
    assert {d["filename"] for d in lst} >= {"vendas.xlsx", "nota.txt", "nota-copia.txt"}
    nota = next(d for d in lst if d["filename"] == "nota.txt")
    assert nota["place"] == "conversa" and nota["duplicates"] == 1
    st = (await client.get("/api/documents/stats", headers=H("kai"))).json()
    assert st["files"] == len(lst) and st["duplicate_groups"] == 1 and st["duplicate_bytes"] == len(b"texto de teste para o gerenciador")

    # anexo preso a mensagem: libera espaço, a mensagem fica e o download responde 410
    r = await client.delete(f"/api/documents/{nota['id']}", headers=H("kai"))
    assert r.json()["action"] == "espaço liberado"
    assert (await client.get(f"/api/documents/{nota['id']}/file", headers=H("kai"))).status_code == 410
    msg = next(m for m in (await client.get(f"/api/conversations/{conv}/messages", headers=H("kai"))).json() if m["document"])
    assert msg["document"]["purged"] is True
    removed = (await client.get("/api/documents?only=removidos", headers=H("kai"))).json()
    assert [d["filename"] for d in removed] == ["nota.txt"]

    # base do agente: apaga de vez
    r = await client.delete(f"/api/documents/{dup['id']}", headers=H("kai"))
    assert r.json()["action"] == "apagado"
    assert not any(d["id"] == dup["id"] for d in (await client.get("/api/documents", headers=H("kai"))).json())
    assert (await client.get("/api/documents/stats", headers=H("kai"))).json()["freed_bytes"] > 0
    assert len(msgs) > 0

    # outro usuário não apaga
    sheet = next(d for d in lst if d["filename"] == "vendas.xlsx")
    assert (await client.delete(f"/api/documents/{sheet['id']}", headers=H("lia"))).status_code == 404


async def test_limpeza_de_duplicados_mantem_o_mais_antigo(client: httpx.AsyncClient, jobs: list[Any]) -> None:
    a = (await client.post("/api/agents", json={"name": "Base"}, headers=H("lu"))).json()["id"]
    for n in ("a.txt", "b.txt", "c.txt"):
        await client.post(f"/api/agents/{a}/documents", headers=H("lu"), files={"file": (n, b"mesmo conteudo", "text/plain")})
    await run_jobs(jobs)
    r = (await client.post("/api/documents/cleanup?what=duplicados", headers=H("lu"))).json()
    assert r["files"] == 2
    assert [d["filename"] for d in (await client.get("/api/documents", headers=H("lu"))).json()] == ["a.txt"]


async def test_cota_de_armazenamento(client: httpx.AsyncClient, jobs: list[Any]) -> None:
    a = (await client.post("/api/agents", json={"name": "Cota"}, headers=H("max"))).json()["id"]
    assert (await client.put("/api/admin/storage", json={"storage_quota_mb": 1}, headers=H("admin"))).status_code == 200
    assert (await client.put("/api/admin/storage", json={"storage_quota_mb": 1}, headers=H("max"))).status_code == 403
    try:
        r = await client.post(f"/api/agents/{a}/documents", headers=H("max"), files={"file": ("grande.txt", b"x" * (1024 * 1024 + 10), "text/plain")})
        assert r.status_code == 422 and "cota" in r.json()["message"]
        assert (await client.get("/api/documents/stats", headers=H("max"))).json()["quota_bytes"] == 1024 * 1024
    finally:
        await client.put("/api/admin/storage", json={"storage_quota_mb": None}, headers=H("admin"))


@pytest.mark.parametrize("author", ["user", "system"])
async def test_red_team_anexo_gerado_so_em_mensagem_de_agente(client: httpx.AsyncClient, jobs: list[Any], app_conn: Any, author: str) -> None:
    conv = await _dm(client, f"rt-{author}")
    await _say(client, jobs, f"rt-{author}", conv, "gera", [
        ("tool", "gerar_arquivo", {"formato": "md", "nome": "x", "titulo": "X", "conteudo": "x"}), ("text", "ok")])
    did = next(m["document"]["id"] for m in (await client.get(f"/api/conversations/{conv}/messages", headers=H(f"rt-{author}"))).json() if m["document"])
    import psycopg

    uid = (await client.get("/api/me", headers=H(f"rt-{author}"))).json()["id"]
    with app_conn() as c, pytest.raises(psycopg.errors.Error):
        c.execute("SELECT set_config('papo.uid', %s, false)", (uid,))
        c.execute("INSERT INTO message (conversation_id, author, body, document_id) VALUES (%s, %s, 'x', %s)", (conv, author, did))
