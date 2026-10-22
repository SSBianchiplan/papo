"""Fluxo completo pela API: agente, base de arquivos, mensagem, ferramentas, resposta, recibos, trilha e isolamento."""
from __future__ import annotations

import io
from typing import Any

import httpx
import pytest

from app import bus
from app.agent.llm import OnText, ToolUse, TurnResult
from app.extract.service import process_document
from app.worker import job_document, job_respond


class FakeLLM:
    """Roteiro de turnos. Cada item: ('tool', nome, args) ou ('text', texto)."""

    def __init__(self, script: list[tuple[Any, ...]], cancel_conv: str | None = None) -> None:
        self.script = list(script)
        self.calls: list[dict[str, Any]] = []
        self.cancel_conv = cancel_conv

    async def turn(self, *, model: str, system: list[dict[str, Any]], messages: list[dict[str, Any]],
                   tools: list[dict[str, Any]] | None, tool_choice: dict[str, Any] | None, max_tokens: int, on_text: OnText) -> TurnResult:
        self.calls.append({"model": model, "system": system[0]["text"], "messages": list(messages), "tools": tools})
        step = self.script.pop(0)
        if step[0] == "tool":
            return TurnResult(content=[{"type": "tool_use", "id": f"t{len(self.calls)}", "name": step[1], "input": step[2]}],
                              stop_reason="tool_use", text="", tool_uses=[ToolUse(f"t{len(self.calls)}", step[1], step[2])],
                              input_tokens=100, output_tokens=10)
        text = step[1]
        for i in range(0, len(text), 8):
            if self.cancel_conv and i >= 16:
                await bus.request_cancel(self.cancel_conv)
            await on_text(text[i:i + 8])
        return TurnResult(content=[{"type": "text", "text": text}], stop_reason="end_turn", text=text, input_tokens=200, output_tokens=40)

    async def complete(self, *, model: str, prompt: str, max_tokens: int = 200) -> tuple[str, int, int]:
        return "[]", 5, 2


def H(user: str) -> dict[str, str]:
    return {"x-dev-user": user}


def xlsx() -> bytes:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "Vendas"
    ws.append(["Região", "Valor"])
    for r in (["Sul", 1200.5], ["Norte", 300], ["Sul", 99.5], ["Sudeste", 2000]):
        ws.append(r)
    b = io.BytesIO()
    wb.save(b)
    return b.getvalue()


async def run_jobs(jobs: list[tuple[str, tuple[Any, ...]]], llm: FakeLLM | None = None) -> None:
    while jobs:
        name, args = jobs.pop(0)
        if name == "job_document":
            await job_document({}, *args)  # type: ignore[arg-type]
        else:
            await job_respond({"llm": llm}, *args)  # type: ignore[arg-type]


async def setup_agent_with_sheet(client: httpx.AsyncClient, jobs: list[Any], user: str) -> tuple[str, str]:
    r = await client.post("/api/agents", json={"name": "Analista", "persona": "Lê planilhas."}, headers=H(user))
    assert r.status_code == 201, r.text
    agent = r.json()["id"]
    r = await client.post(f"/api/agents/{agent}/documents", headers=H(user),
                          files={"file": ("vendas.xlsx", xlsx(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    assert r.status_code == 201 and r.json()["status"] == "pending"
    await run_jobs(jobs)
    docs = (await client.get(f"/api/agents/{agent}/documents", headers=H(user))).json()
    assert docs[0]["status"] == "ready" and docs[0]["sheets"][0]["columns"] == ["Região", "Valor"]
    r = await client.post("/api/conversations", json={"kind": "dm", "agent_id": agent}, headers=H(user))
    assert r.status_code == 201
    return agent, r.json()["id"]


async def test_fluxo_completo_com_ferramentas(client: httpx.AsyncClient, jobs: list[Any]) -> None:
    agent, conv = await setup_agent_with_sheet(client, jobs, "ana")
    r = await client.post(f"/api/conversations/{conv}/messages", json={"body": "Qual o total por região?"}, headers=H("ana"))
    assert r.status_code == 201 and r.json()["status"] == "sent"

    # INV-RUN-005 na API: segunda mensagem com resposta pendente é recusada
    r2 = await client.post(f"/api/conversations/{conv}/messages", json={"body": "e agora?"}, headers=H("ana"))
    assert r2.status_code == 409

    llm = FakeLLM([("tool", "analisar_planilha", {"documento": "vendas", "operacao": "agrupar", "agrupar_por": ["regiao"],
                                                   "metrica": {"coluna": "valor", "funcao": "soma"}}),
                   ("text", "O total é *3.600*: Sudeste 2.000, Sul 1.300 e Norte 300.\n⟦fontes: vendas.xlsx aba Vendas⟧")])
    await run_jobs(jobs, llm)

    # a ferramenta calculou com os dados reais e o resultado voltou para o modelo
    tool_result = llm.calls[1]["messages"][-1]["content"][0]
    assert tool_result["type"] == "tool_result" and '"total_geral": 3600.0' in tool_result["content"]
    assert "vendas.xlsx" in llm.calls[0]["system"] and llm.calls[0]["tools"]

    msgs = (await client.get(f"/api/conversations/{conv}/messages", headers=H("ana"))).json()
    user_msg, answer = msgs[-2], msgs[-1]
    assert user_msg["status"] == "read"
    assert answer["author"] == "agent" and answer["body"].startswith("O total é *3.600*")
    assert "⟦" not in answer["body"] and answer["sources"] == ["vendas.xlsx aba Vendas"]
    assert answer["steps"][0]["icon"] == "📊" and "soma de Valor por Região" in answer["steps"][0]["text"]

    runs = (await client.get("/api/runs", headers=H("ana"))).json()
    assert runs[0]["status"] == "done" and runs[0]["tool_calls"] == 1 and runs[0]["chain_ok"] is True
    assert [e["kind"] for e in runs[0]["events"]] == ["started", "context", "tool_call", "tool_result", "answer"]
    assert runs[0]["input_tokens"] == 300

    me = (await client.get("/api/me", headers=H("ana"))).json()
    assert me["usage_today"] == 350

    # a conversa foi liberada
    r3 = await client.post(f"/api/conversations/{conv}/messages", json={"body": "obrigado"}, headers=H("ana"))
    assert r3.status_code == 201
    await run_jobs(jobs, FakeLLM([("text", "De nada!")]))


async def test_isolamento_entre_usuarios_pela_api(client: httpx.AsyncClient, jobs: list[Any]) -> None:
    _, conv = await setup_agent_with_sheet(client, jobs, "carla")
    assert (await client.get("/api/conversations", headers=H("davi"))).json() == []
    assert (await client.get(f"/api/conversations/{conv}/messages", headers=H("davi"))).json() == []
    r = await client.post(f"/api/conversations/{conv}/messages", json={"body": "invadindo"}, headers=H("davi"))
    assert r.status_code == 404
    await bus.redis().delete(f"papo:busy:{conv}")
    assert (await client.delete(f"/api/conversations/{conv}", headers=H("davi"))).status_code == 404


async def test_cancelamento_no_meio(client: httpx.AsyncClient, jobs: list[Any]) -> None:
    _, conv = await setup_agent_with_sheet(client, jobs, "edu")
    await client.post(f"/api/conversations/{conv}/messages", json={"body": "fale bastante"}, headers=H("edu"))
    await run_jobs(jobs, FakeLLM([("text", "Começando uma resposta bem longa que será interrompida no meio.")], cancel_conv=conv))
    last = (await client.get(f"/api/conversations/{conv}/messages", headers=H("edu"))).json()[-1]
    assert last["error"] == "Resposta interrompida." and last["body"].startswith("Começando")
    runs = (await client.get("/api/runs", headers=H("edu"))).json()
    assert runs[0]["status"] == "cancelled" and runs[0]["events"][-1]["kind"] == "cancelled"


async def test_grupo_com_mencao_responde_so_o_mencionado(client: httpx.AsyncClient, jobs: list[Any]) -> None:
    ids = []
    for n in ("Fiscal", "Comercial"):
        ids.append((await client.post("/api/agents", json={"name": n}, headers=H("fabi"))).json()["id"])
    g = (await client.post("/api/conversations", json={"kind": "group", "name": "Comitê", "members": ids}, headers=H("fabi"))).json()
    assert g["members"] and len(g["members"]) == 2
    await client.post(f"/api/conversations/{g['id']}/messages", json={"body": "@Comercial qual a meta?"}, headers=H("fabi"))
    llm = FakeLLM([("text", "A meta é dobrar.")])
    await run_jobs(jobs, llm)
    msgs = (await client.get(f"/api/conversations/{g['id']}/messages", headers=H("fabi"))).json()
    assert msgs[-1]["agent_name"] == "Comercial" and len(llm.calls) == 1
    assert "[Usuário]: @Comercial" in llm.calls[0]["messages"][-1]["content"]


async def test_imagem_normalizada_e_privada(client: httpx.AsyncClient, jobs: list[Any], memory_storage: dict[str, bytes]) -> None:
    from PIL import Image

    agent = (await client.post("/api/agents", json={"name": "Visão"}, headers=H("gabi"))).json()["id"]
    conv = (await client.post("/api/conversations", json={"kind": "dm", "agent_id": agent}, headers=H("gabi"))).json()["id"]
    png = io.BytesIO()
    Image.new("RGB", (3000, 2000), "red").save(png, "PNG")
    up = (await client.post(f"/api/conversations/{conv}/attachments", headers=H("gabi"),
                            files={"file": ("foto.png", png.getvalue(), "image/png")})).json()
    assert up["kind"] == "image"
    stored = Image.open(io.BytesIO(memory_storage[up["image_key"]]))
    assert stored.format == "JPEG" and max(stored.size) == 1600
    await client.post(f"/api/conversations/{conv}/messages", json={"body": "o que é?", "image_key": up["image_key"]}, headers=H("gabi"))
    llm = FakeLLM([("text", "Uma imagem vermelha.")])
    await run_jobs(jobs, llm)
    assert llm.calls[0]["messages"][-1]["content"][0]["type"] == "image"
    assert (await client.get(f"/api/images/{up['image_key']}", headers=H("gabi"))).status_code == 200
    assert (await client.get(f"/api/images/{up['image_key']}", headers=H("hugo"))).status_code == 404


async def test_preferencias_validadas(client: httpx.AsyncClient) -> None:
    assert (await client.put("/api/settings", json={"tier": "turbo"}, headers=H("ivo"))).status_code == 422
    ok = await client.put("/api/settings", json={"tier": "quick", "groupMax": 3}, headers=H("ivo"))
    assert ok.status_code == 200
    assert (await client.get("/api/me", headers=H("ivo"))).json()["settings"]["tier"] == "quick"


async def test_sem_autenticacao(client: httpx.AsyncClient) -> None:
    assert (await client.get("/api/agents")).status_code == 401


async def test_arquivo_corrompido_vira_failed(client: httpx.AsyncClient, jobs: list[Any]) -> None:
    agent = (await client.post("/api/agents", json={"name": "Leitor"}, headers=H("jo"))).json()["id"]
    await client.post(f"/api/agents/{agent}/documents", headers=H("jo"), files={"file": ("ruim.pdf", b"%PDF-1.4 lixo", "application/pdf")})
    await run_jobs(jobs)
    d = (await client.get(f"/api/agents/{agent}/documents", headers=H("jo"))).json()[0]
    assert d["status"] == "failed" and d["note"]


async def test_exclusao_de_conta(client: httpx.AsyncClient, jobs: list[Any], memory_storage: dict[str, bytes]) -> None:
    await setup_agent_with_sheet(client, jobs, "lia")
    me = (await client.get("/api/me", headers=H("lia"))).json()
    assert any(k.startswith(me["id"]) for k in memory_storage)
    assert (await client.delete("/api/me", headers=H("lia"))).status_code == 204
    assert not any(k.startswith(me["id"]) for k in memory_storage)
    assert (await client.get("/api/agents", headers=H("lia"))).json() == []


pytestmark = pytest.mark.usefixtures("database")
_ = process_document


def pdf_bytes() -> bytes:
    from reportlab.pdfgen import canvas

    b = io.BytesIO()
    c = canvas.Canvas(b)
    for t in ("Objeto: fornecimento de paineis eletricos.", "O prazo de entrega e de 90 dias apos a assinatura.", "Multa de 2% ao mes."):
        c.drawString(72, 750, t)
        c.showPage()
    c.save()
    return b.getvalue()


async def _pdf_conversation(client: httpx.AsyncClient, jobs: list[Any], user: str) -> tuple[str, str]:
    agent = (await client.post("/api/agents", json={"name": "Jurídico"}, headers=H(user))).json()["id"]
    conv = (await client.post("/api/conversations", json={"kind": "dm", "agent_id": agent}, headers=H(user))).json()["id"]
    up = (await client.post(f"/api/conversations/{conv}/attachments", headers=H(user),
                            files={"file": ("contrato.pdf", pdf_bytes(), "application/pdf")})).json()
    assert up["kind"] == "document"
    # arquivo ainda em leitura: envio recusado com explicação
    early = await client.post(f"/api/conversations/{conv}/messages", json={"body": "prazo?", "document_id": up["document"]["id"]}, headers=H(user))
    assert early.status_code == 409
    await bus.redis().delete(f"papo:busy:{conv}")
    await run_jobs(jobs)
    return conv, up["document"]["id"]


async def test_pdf_anexado_busca_e_leitura_por_pagina(client: httpx.AsyncClient, jobs: list[Any]) -> None:
    conv, doc = await _pdf_conversation(client, jobs, "mara")
    await client.post(f"/api/conversations/{conv}/messages", json={"body": "Qual o prazo de entrega?", "document_id": doc}, headers=H("mara"))
    llm = FakeLLM([("tool", "listar_documentos", {}),
                   ("tool", "buscar_nos_documentos", {"consulta": "prazo de entrega"}),
                   ("tool", "ler_documento", {"documento": "contrato", "de": 2, "ate": 3}),
                   ("tool", "ler_documento", {"documento": "inexistente"}),
                   ("text", "O prazo é de 90 dias após a assinatura.\n⟦fontes: contrato.pdf p. 2⟧")])
    await run_jobs(jobs, llm)
    busca = llm.calls[2]["messages"][-1]["content"][0]["content"]
    assert '"local": "p. 2"' in busca and "90 dias" in busca
    leitura = llm.calls[3]["messages"][-1]["content"][0]["content"]
    assert '"p. 2"' in leitura and '"p. 3"' in leitura
    erro = llm.calls[4]["messages"][-1]["content"][0]
    assert erro["is_error"] and "listar_documentos" in erro["content"]
    last = (await client.get(f"/api/conversations/{conv}/messages", headers=H("mara"))).json()[-1]
    assert last["sources"] == ["contrato.pdf p. 2"] and len(last["steps"]) == 4
    assert "[arquivo anexado: contrato.pdf — disponível para leitura]" in llm.calls[0]["messages"][-1]["content"]


async def test_modo_direto_envia_conteudo_sem_ferramentas(client: httpx.AsyncClient, jobs: list[Any]) -> None:
    await client.put("/api/settings", json={"readMode": "direct", "tier": "complex"}, headers=H("nina"))
    conv, doc = await _pdf_conversation(client, jobs, "nina")
    await client.post(f"/api/conversations/{conv}/messages", json={"body": "multa?"}, headers=H("nina"))
    llm = FakeLLM([("text", "Multa de 2% ao mês.")])
    await run_jobs(jobs, llm)
    # modo direto: conteúdo no prompt, sem ferramentas de documento (só gerar arquivo e buscar no histórico)
    assert {t["name"] for t in llm.calls[0]["tools"]} == {"gerar_arquivo", "buscar_na_conversa"} and "Multa de 2%" in llm.calls[0]["system"]
    assert llm.calls[0]["model"] == "claude-opus-5-5"


async def test_grupo_roteamento_automatico(client: httpx.AsyncClient, jobs: list[Any]) -> None:
    ids = [(await client.post("/api/agents", json={"name": n}, headers=H("otto"))).json()["id"] for n in ("Fiscal", "RH")]
    g = (await client.post("/api/conversations", json={"kind": "group", "name": "Diretoria", "members": ids}, headers=H("otto"))).json()

    class Router(FakeLLM):
        async def complete(self, *, model: str, prompt: str, max_tokens: int = 200) -> tuple[str, int, int]:
            assert "Fiscal" in prompt and "RH" in prompt
            return f'["{ids[1]}"]', 20, 5

    await client.post(f"/api/conversations/{g['id']}/messages", json={"body": "como fica a férias?"}, headers=H("otto"))
    await run_jobs(jobs, Router([("text", "Férias em 30 dias.")]))
    msgs = (await client.get(f"/api/conversations/{g['id']}/messages", headers=H("otto"))).json()
    assert msgs[-1]["agent_name"] == "RH"
    runs = (await client.get("/api/runs", headers=H("otto"))).json()
    assert runs[0]["events"][1]["kind"] == "routed" and "RH" in runs[0]["events"][1]["payload"]["motivo"]


async def test_limite_diario(client: httpx.AsyncClient, jobs: list[Any], monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import get_settings

    _, conv = await setup_agent_with_sheet(client, jobs, "pia")
    monkeypatch.setattr(get_settings(), "daily_token_limit", 1)
    await client.post(f"/api/conversations/{conv}/messages", json={"body": "oi"}, headers=H("pia"))
    await client.post(f"/api/conversations/{conv}/messages", json={"body": "oi"}, headers=H("pia"))   # recusada: ocupada
    await run_jobs(jobs, FakeLLM([("text", "Oi!")]))
    await client.post(f"/api/conversations/{conv}/messages", json={"body": "de novo"}, headers=H("pia"))
    await run_jobs(jobs, FakeLLM([]))
    last = (await client.get(f"/api/conversations/{conv}/messages", headers=H("pia"))).json()[-1]
    assert last["author"] == "system" and "Limite diário" in last["body"]


async def test_planilha_busca_por_linha_aba_e_erros(client: httpx.AsyncClient, jobs: list[Any]) -> None:
    _, conv = await setup_agent_with_sheet(client, jobs, "quim")
    await client.post(f"/api/conversations/{conv}/messages", json={"body": "e o sudeste?"}, headers=H("quim"))
    llm = FakeLLM([("tool", "buscar_nos_documentos", {"consulta": "sudeste"}),
                   ("tool", "analisar_planilha", {"documento": "vendas", "aba": "Inexistente", "operacao": "descrever"}),
                   ("tool", "analisar_planilha", {"documento": "vendas", "aba": "vend", "operacao": "filtrar",
                                                  "filtros": [{"coluna": "Região", "op": "=", "valor": "Sudeste"}]}),
                   ("tool", "analisar_planilha", {"documento": "vendas", "operacao": "descrever"}),
                   ("tool", "ler_documento", {"documento": "vendas"}),
                   ("tool", "analisar_planilha", {"operacao": "agrupar"}),
                   ("tool", "ferramenta_que_nao_existe", {}),
                   ("text", "Sudeste vendeu 2.000.")])
    await run_jobs(jobs, llm)
    res = [c["messages"][-1]["content"][0] for c in llm.calls[1:]]
    assert '"Sudeste"' in res[0]["content"] and '"aba Vendas"' in res[0]["content"]
    assert res[1]["is_error"] and "Abas: Vendas" in res[1]["content"]
    assert '"total_encontrado": 1' in res[2]["content"]
    assert '"tipo": "numérico"' in res[3]["content"]
    assert res[4]["is_error"] and "analisar_planilha" in res[4]["content"]
    assert res[5]["is_error"] and "argumentos inválidos" in res[5]["content"]
    assert res[6]["is_error"] and "não está liberada na ficha" in res[6]["content"]      # lista fechada (C6.1), registrada como T8


async def test_modo_direto_com_planilha(client: httpx.AsyncClient, jobs: list[Any]) -> None:
    await client.put("/api/settings", json={"readMode": "direct"}, headers=H("rui"))
    _, conv = await setup_agent_with_sheet(client, jobs, "rui")
    await client.post(f"/api/conversations/{conv}/messages", json={"body": "resumo"}, headers=H("rui"))
    llm = FakeLLM([("text", "Resumo.")])
    await run_jobs(jobs, llm)
    assert "[aba Vendas]" in llm.calls[0]["system"] and "Sudeste;2000" in llm.calls[0]["system"]
