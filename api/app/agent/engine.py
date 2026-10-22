"""Motor de resposta. Roda no worker: roteia, executa o loop de ferramentas, transmite e registra.

Tudo que é fato (mensagem, recibo, evento da execução, consumo) é INSERT. O único UPDATE é o
estado da execução, cujas transições o banco valida (INV-RUN-001).
"""
from __future__ import annotations

import base64
import json
import logging
import re
import time
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncConnection

from .. import bus, costs, governanca, storage
from ..config import get_settings
from ..db import row, rows, scalar, tx
from ..schemas import UserConfig
from .llm import LLM, TurnResult
from .prompts import router_prompt, system_prompt
from .tools import DocInfo, Output, Toolbox, docs_as_text, load_docs, tool_specs

log = logging.getLogger("papo.engine")
HISTORY = 40                     # mensagens recentes enviadas ao modelo; o resto ele acha com buscar_na_conversa
SOURCES_RE = re.compile(r"⟦\s*fontes?\s*:\s*([^⟧]*)⟧?\s*$", re.IGNORECASE)


class Cancelled(Exception):
    pass


@dataclass
class AgentRow:
    id: UUID
    name: str
    persona: str


def split_sources(text: str) -> tuple[str, list[str]]:
    m = SOURCES_RE.search(text)
    if not m:
        return text.strip(), []
    return text[: m.start()].strip(), [s.strip() for s in m.group(1).split(";") if s.strip()][:6]


def visible(text: str) -> str:
    return re.sub(r"⟦[^⟧]*⟧?\s*$", "", text).strip()


async def load_config(conn: AsyncConnection, uid: UUID) -> UserConfig:
    data = await scalar(conn, "SELECT data FROM user_settings WHERE user_id = :u", u=uid)
    return UserConfig.model_validate({**(data or {})}) if data else UserConfig()


async def usage_today(conn: AsyncConnection, uid: UUID) -> int:
    return int(await scalar(conn, """SELECT coalesce(sum(input_tokens + output_tokens), 0) FROM usage_event
                                      WHERE user_id = :u AND at >= :d""", u=uid, d=costs.days_ago(1)))   # dia de Brasília


async def system_message(owner: UUID, conversation_id: UUID, text: str) -> None:
    async with tx(owner) as conn:
        m = await row(conn, """INSERT INTO message (conversation_id, author, body) VALUES (:c, 'system', :b)
                               RETURNING id, seq, created_at""", c=conversation_id, b=text)
    await bus.publish(owner, "message.created", {"conversation_id": conversation_id, "message_id": m["id"] if m else None})


async def receipt(owner: UUID, message_id: UUID, conversation_id: UUID, state: str) -> None:
    async with tx(owner) as conn:
        await conn.execute(_t("INSERT INTO message_receipt (message_id, state) VALUES (:m, :s) ON CONFLICT DO NOTHING"),
                           {"m": message_id, "s": state})
    await bus.publish(owner, "receipt", {"message_id": message_id, "conversation_id": conversation_id, "state": state})


def _t(sql: str) -> Any:
    from sqlalchemy import text
    return text(sql)


# ----------------------------------------------------------------- roteamento
async def pick_responders(llm: LLM, cfg: UserConfig, members: list[AgentRow], body: str, recent: str,
                          router_model: str | None = None) -> tuple[list[AgentRow], str, int, int]:
    low = body.lower()
    mentioned = [a for a in members if f"@{a.name.lower()}" in low or f"@{a.name.lower().split()[0]}" in low]
    if mentioned:
        return mentioned, "menção", 0, 0
    if len(members) == 1:
        return members, "único membro", 0, 0
    if cfg.groupMode == "todos" or re.search(r"\b(todos|pessoal|galera|vocês|voces)\b", low):
        return members, "todos", 0, 0
    s = get_settings()
    try:
        text, i, o = await llm.complete(model=router_model or s.model_router,
                                        prompt=router_prompt([(str(a.id), a.name, a.persona) for a in members], recent, cfg.groupMax))
        m = re.search(r"\[.*\]", text, re.S)
        ids = [str(x) for x in json.loads(m.group(0))] if m else []
        chosen = [a for a in members if str(a.id) in ids][: cfg.groupMax]
        return (chosen or members[:1]), "assunto", i, o
    except Exception:  # noqa: BLE001 — roteador falhou: degrada para o primeiro membro, nunca derruba a resposta
        log.exception("roteador falhou")
        return members[:1], "padrão", 0, 0


# ----------------------------------------------------------------- histórico
async def build_history(conn: AsyncConnection, conversation_id: UUID, agent: AgentRow, is_group: bool,
                        trigger_id: UUID) -> tuple[list[dict[str, Any]], str | None]:
    msgs = await rows(conn, """
        SELECT m.id, m.author, m.agent_id, m.agent_name, m.body, m.image_key, d.filename, d.status
          FROM message m LEFT JOIN document d ON d.id = m.document_id
         WHERE m.conversation_id = :c AND m.author <> 'system'
         ORDER BY m.seq DESC LIMIT :n""", c=conversation_id, n=HISTORY)
    msgs.reverse()
    out: list[dict[str, Any]] = []
    image_key: str | None = None
    for m in msgs:
        body = m["body"] or ""
        if m["image_key"]:
            if m["id"] == trigger_id:
                image_key = m["image_key"]
            body = "[imagem enviada]" + (f" {body}" if body else "")
        if m["filename"]:
            ok = "disponível para leitura" if m["status"] == "ready" else "não legível"
            body = f"[arquivo anexado: {m['filename']} — {ok}]" + (f"\n{body}" if body else "")
        body = body[:16000] or "(vazio)"
        if m["author"] == "user":
            role, content = "user", ("[Usuário]: " + body if is_group else body)
        elif m["agent_id"] == agent.id:
            role, content = "assistant", body
        else:
            role, content = "user", f"[{m['agent_name']}]: {body}"
        if out and out[-1]["role"] == role:
            out[-1]["content"] += "\n\n" + content
        else:
            out.append({"role": role, "content": content})
    while out and out[0]["role"] != "user":
        out.pop(0)
    if not out or out[-1]["role"] != "user":
        out.append({"role": "user", "content": "(continue)"})
    return out, image_key


# ----------------------------------------------------------------- execução de um agente
class RunCtx:
    def __init__(self, owner: UUID, conversation_id: UUID, run_id: UUID) -> None:
        self.owner, self.conversation_id, self.run_id = owner, conversation_id, run_id
        self.steps: list[dict[str, str]] = []
        self.full = ""          # texto do turno corrente
        self.cut = 0            # início do texto visível (depois da última ferramenta)
        self.last_pub = 0.0
        self.last_cancel_check = 0.0
        self.read_sent = False

    async def event(self, kind: str, payload: dict[str, Any]) -> None:
        async with tx(self.owner) as conn:
            await conn.execute(_t("INSERT INTO agent_run_event (run_id, kind, payload, hash) VALUES (:r, :k, CAST(:p AS jsonb), :h)"),
                               {"r": self.run_id, "k": kind, "p": json.dumps(payload, ensure_ascii=False, default=str), "h": "0" * 64})

    async def check_cancel(self, force: bool = False) -> None:
        now = time.monotonic()
        if force or now - self.last_cancel_check > 0.3:
            self.last_cancel_check = now
            if await bus.cancelled(self.conversation_id):
                raise Cancelled()

    async def publish_text(self, force: bool = False) -> None:
        now = time.monotonic()
        if force or now - self.last_pub > 0.15:
            self.last_pub = now
            await bus.publish(self.owner, "run.delta", {"run_id": self.run_id, "conversation_id": self.conversation_id,
                                                        "text": visible(self.full[self.cut:])})


async def run_agent(llm: LLM, owner: UUID, conv: dict[str, Any], agent: AgentRow, members: list[AgentRow],
                    trigger_id: UUID, cfg: UserConfig, route_note: str | None) -> None:
    s = get_settings()
    is_group = conv["kind"] == "group"
    async with tx(owner) as conn:
        docs: list[DocInfo] = await load_docs(conn, conv["id"], [agent.id])
        read_mode = "none" if not docs else cfg.readMode
        model = costs.model_for(await costs.load_ai_config(conn), cfg.tier)      # escolha do painel, senão o .env
        run_id = await scalar(conn, """INSERT INTO agent_run (conversation_id, trigger_message_id, agent_id, agent_name, tier, read_mode, model)
                                       VALUES (:c, :m, :a, :n, :t, :r, :mo) RETURNING id""",
                              c=conv["id"], m=trigger_id, a=agent.id, n=agent.name, t=cfg.tier, r=read_mode, mo=model)
        await conn.execute(_t("UPDATE agent_run SET status = 'running', started_at = now() WHERE id = :r"), {"r": run_id})
        history, image_key = await build_history(conn, conv["id"], agent, is_group, trigger_id)
        skills = await rows(conn, """SELECT s.id, s.name, s.description FROM skill s
                                      WHERE s.enabled AND (EXISTS (SELECT 1 FROM agent_skill a WHERE a.skill_id = s.id AND a.agent_id = :a)
                                         OR EXISTS (SELECT 1 FROM conversation_skill c WHERE c.skill_id = s.id AND c.conversation_id = :c))
                                      ORDER BY lower(s.name) LIMIT 60""", a=agent.id, c=conv["id"])
        hub = await rows(conn, """SELECT h.source_id, s.label, h.prefix FROM agent_hub h JOIN hub_source s ON s.id = h.source_id
                                   WHERE h.agent_id = :a AND s.enabled
                                     AND (s.visible_all OR (SELECT is_admin FROM app_user WHERE id = :o))
                                   ORDER BY s.label, h.prefix""", a=agent.id, o=owner)
        direct = await docs_as_text(conn, docs) if read_mode == "direct" else None
        ficha = await governanca.load_ficha(conn, agent.id)
        feats = await governanca.conversation_features(conn, conv["id"])
        spent = await governanca.conversation_cost_usd(conn, conv["id"])
        prices = await costs.load_prices(conn)
    ctx = RunCtx(owner, conv["id"], run_id)
    await ctx.event("started", {"agente": agent.name, "modelo": model, "modo": read_mode, "moderacao": ficha.nivel,
                                "ficha_versao": ficha.versao, "camada": ficha.camada_real})
    if route_note:
        await ctx.event("routed", {"motivo": route_note})
    if docs:
        await ctx.event("context", {"arquivos": [d.name for d in docs], "modo": read_mode})
    await bus.publish(owner, "run.started", {"run_id": run_id, "conversation_id": conv["id"], "agent_id": agent.id, "agent_name": agent.name})

    system = [{"type": "text", "cache_control": {"type": "ephemeral"},
               "text": system_prompt(agent_name=agent.name, persona=agent.persona, length=cfg.length,
                                     group_name=conv["name"] if is_group else None,
                                     others=[m.name for m in members if m.id != agent.id],
                                     docs=docs, read_mode=read_mode, direct_text=direct,
                                     skills=[(k["name"], k["description"]) for k in skills],
                                     hub=[(h["label"], h["prefix"]) for h in hub],
                                     camadas=ficha.camadas_no_contexto or feats["camadas"], nivel=ficha.nivel)}]
    messages = history
    if image_key:
        try:
            img = await storage.get(image_key)
            last = messages[-1]
            messages[-1] = {"role": "user", "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": base64.b64encode(img).decode()}},
                {"type": "text", "text": last["content"]}]}
        except Exception:  # noqa: BLE001 — imagem ausente não impede a resposta em texto
            log.exception("imagem indisponível: %s", image_key)

    tools = [t for t in tool_specs(with_docs=read_mode == "agent", with_skills=bool(skills), with_hub=bool(hub))
             if ficha.allows(t["name"])]                   # lista fechada da ficha (C6.1); M0 não recebe escrita
    max_turns = min(ficha.max_iteracoes, s.max_tool_turns)
    started = time.monotonic()
    out = Output(owner, conv["id"], run_id, agent.name, skills={k["name"]: k["id"] for k in skills},
                 hub=[(h["source_id"], h["label"], h["prefix"]) for h in hub])
    tok_in = tok_out = calls = 0

    async def on_text(delta: str) -> None:
        ctx.full += delta
        if not ctx.read_sent and ctx.full.strip():
            ctx.read_sent = True
            await receipt(owner, trigger_id, conv["id"], "read")
        await ctx.check_cancel()
        await ctx.publish_text()

    async def tool_log(icon: str, text: str) -> None:
        ctx.steps.append({"icon": icon, "text": text})
        ctx.cut = len(ctx.full)
        await bus.publish(owner, "run.step", {"run_id": run_id, "conversation_id": conv["id"], "icon": icon, "text": text})

    final_text = ""
    status, error = "done", None
    try:
        for turn in range(max_turns):
            await ctx.check_cancel(force=True)
            stop = None
            if spent + costs.cost_usd(model, tok_in, tok_out, prices) >= ficha.max_custo_conversa_usd:
                stop = ("T7", f"teto de custo da conversa (US$ {ficha.max_custo_conversa_usd:.2f}) atingido")
            elif time.monotonic() - started > ficha.max_segundos_turno:
                stop = ("PARADA", f"tempo máximo do turno ({ficha.max_segundos_turno} s) atingido")
            if stop:
                async with tx(owner) as conn:
                    await governanca.disparar(conn, owner, ficha, stop[0], stop[1], conversation_id=conv["id"], run_id=run_id)
                await ctx.event("governanca", {"codigo": stop[0], "detalhe": stop[1]})
                final_text = (ctx.full[ctx.cut:] + "\n\n" if ctx.full else "") + f"Parei aqui: {stop[1]}. Envie de novo se quiser continuar."
                break
            ctx.full, ctx.cut = "", 0
            last_turn = turn == max_turns - 1
            res: TurnResult = await llm.turn(model=model, system=system, messages=messages, tools=tools or None,
                                             tool_choice={"type": "none"} if (tools and last_turn) else None,
                                             max_tokens=s.max_output_tokens, on_text=on_text)
            tok_in += res.input_tokens
            tok_out += res.output_tokens
            await ctx.check_cancel(force=True)      # pedido de parar que chegou no fim do turno ainda vale
            messages.append({"role": "assistant", "content": res.content})
            if res.stop_reason != "tool_use" or not res.tool_uses:
                final_text = res.text
                break
            results = []
            for tu in res.tool_uses:
                calls += 1
                await ctx.event("tool_call", {"ferramenta": tu.name, "argumentos": tu.input})
                async with tx(owner) as conn:
                    if not ficha.allows(tu.name):
                        await governanca.disparar(conn, owner, ficha, "T8", f"ferramenta fora da ficha: {tu.name}",
                                                  conversation_id=conv["id"], run_id=run_id)
                        res_tool = {"ok": False, "error": f"ferramenta {tu.name} não está liberada na ficha deste agente"}
                    else:
                        res_tool = await Toolbox(conn, docs, tool_log, out).run(tu.name, tu.input)
                await ctx.event("tool_result", {"ferramenta": tu.name, "ok": res_tool.get("ok"), "erro": res_tool.get("error")})
                payload = json.dumps(res_tool, ensure_ascii=False, default=str)
                if len(payload) > 30_000:
                    payload = payload[:30_000] + "…(cortado)"
                results.append({"type": "tool_result", "tool_use_id": tu.id, "content": payload, "is_error": not res_tool.get("ok")})
            messages.append({"role": "user", "content": results})
            await ctx.check_cancel(force=True)
    except Cancelled:
        status, error = "cancelled", "Resposta interrompida."
        final_text = ctx.full[ctx.cut:]
    except Exception as e:  # noqa: BLE001 — qualquer falha do provedor vira mensagem legível e execução 'failed'
        log.exception("execução falhou")
        status = "failed"
        error = friendly_error(e)
        final_text = ctx.full[ctx.cut:]

    body, sources = split_sources(final_text)
    if status == "done" and not body and not out.files:      # só arquivo, sem texto, também é resposta
        status, error = "failed", "O agente não produziu resposta. Envie de novo."
    async with tx(owner) as conn:
        await conn.execute(_t("""UPDATE agent_run SET status = :st, input_tokens = :i, output_tokens = :o, tool_calls = :c,
                                         error = :e, finished_at = now() WHERE id = :r"""),
                           {"st": status, "i": tok_in, "o": tok_out, "c": min(calls, 64), "e": error, "r": run_id})
        if tok_in or tok_out:
            await conn.execute(_t("INSERT INTO usage_event (user_id, run_id, model, input_tokens, output_tokens) VALUES (:u, :r, :m, :i, :o)"),
                               {"u": owner, "r": run_id, "m": model, "i": tok_in, "o": tok_out})
        for fid in out.files:                    # cada arquivo gerado chega como anexo, antes do texto da resposta
            await conn.execute(_t("""INSERT INTO message (conversation_id, author, agent_id, agent_name, body, run_id, document_id)
                                     VALUES (:c, 'agent', :a, :n, '', :r, :d)"""),
                               {"c": conv["id"], "a": agent.id, "n": agent.name, "r": run_id, "d": fid})
        if body or error:
            await conn.execute(_t("""INSERT INTO message (conversation_id, author, agent_id, agent_name, body, run_id, sources, steps, error)
                                     VALUES (:c, 'agent', :a, :n, :b, :r, CAST(:s AS jsonb), CAST(:st AS jsonb), :e)"""),
                               {"c": conv["id"], "a": agent.id, "n": agent.name, "b": body[:20000], "r": run_id,
                                "s": json.dumps(sources, ensure_ascii=False), "st": json.dumps(ctx.steps, ensure_ascii=False), "e": error})
    kind = {"done": "answer", "cancelled": "cancelled"}.get(status, "error")
    await ctx.event(kind, {"fontes": sources, "tokens": tok_in + tok_out, **({"erro": error} if error else {})})
    await bus.publish(owner, "run.finished", {"run_id": run_id, "conversation_id": conv["id"], "status": status})
    if status == "cancelled":
        raise Cancelled()


def friendly_error(e: Exception) -> str:
    name = type(e).__name__
    if name == "LLMNotConfigured":
        return "O serviço de IA ainda não foi configurado neste servidor. Avise o administrador."
    if "RateLimit" in name:
        return "O serviço de IA está sobrecarregado. Tente de novo em instantes."
    low = str(e).lower()
    if "BadRequest" in name and "valid workspace id" in low:
        return "O ID do workspace não é válido. Use o ID que começa com wrkspc_ (não o nome do workspace)."
    if "BadRequest" in name and "workspace" in low:
        return "A chave da IA precisa do ID do workspace. O administrador configura em Configuração → Administração."
    if "credit balance" in low or "billing" in low:
        return "A conta da Anthropic está sem créditos. Avise o administrador."
    if "Authentication" in name or "PermissionDenied" in name:
        return "Falha de credencial com o serviço de IA. Avise o administrador."
    if "BadRequest" in name and "too long" in str(e).lower():
        return "A conversa ou os arquivos ficaram grandes demais. Comece uma conversa nova."
    if "Timeout" in name or "Connection" in name:
        return "O serviço de IA não respondeu. Envie de novo."
    return "A resposta falhou. Envie a mensagem de novo."


# ----------------------------------------------------------------- job
async def _inactive(owner: UUID, conversation_id: UUID, agent: dict[str, Any], ficha: governanca.Ficha) -> None:
    async with tx(owner) as conn:
        await governanca.evento(conn, owner, "INATIVO", f"{agent['name']} chamado com a ficha inativa", agent_id=agent["id"],
                                conversation_id=conversation_id, antes=ficha.nivel, depois=ficha.nivel)
    await system_message(owner, conversation_id, f"{agent['name']} está desativado na governança de IA (ficha "
                                                 f"{'incompleta' if not ficha.dono else 'inativa'}). Ative em Configuração → Governança de IA.")


async def respond(llm: LLM, owner: UUID, conversation_id: UUID, message_id: UUID) -> None:
    async with tx(owner) as conn:
        conv = await row(conn, "SELECT id, kind, agent_id, name FROM conversation WHERE id = :c", c=conversation_id)
        msg = await row(conn, "SELECT id, body FROM message WHERE id = :m AND conversation_id = :c AND author = 'user'",
                        m=message_id, c=conversation_id)
        if not conv or not msg:
            return
        cfg = await load_config(conn, owner)
        used = await usage_today(conn, owner)
        ai = await costs.load_ai_config(conn)
        daily_limit = costs.effective_daily_limit(ai)
        over_budget = False
        if ai.monthly_budget_usd is not None:
            over_budget = await costs.month_cost(conn, await costs.load_prices(conn)) >= ai.monthly_budget_usd
        if conv["kind"] == "dm":
            members_raw = await rows(conn, "SELECT id, name, persona FROM agent WHERE id = :a", a=conv["agent_id"])
        else:
            members_raw = await rows(conn, """SELECT a.id, a.name, a.persona FROM conversation_member m JOIN agent a ON a.id = m.agent_id
                                              WHERE m.conversation_id = :c ORDER BY a.name""", c=conversation_id)
        recent_rows = await rows(conn, """SELECT author, agent_name, body FROM message WHERE conversation_id = :c AND author <> 'system'
                                          ORDER BY seq DESC LIMIT 8""", c=conversation_id)
    await receipt(owner, message_id, conversation_id, "delivered")
    async with tx(owner) as conn:
        kinds = {r["id"]: r["kind"] for r in await rows(conn, "SELECT id, kind FROM agent WHERE id = ANY(:ids)", ids=[m["id"] for m in members_raw])}
        fichas = {m["id"]: await governanca.load_ficha(conn, m["id"]) for m in members_raw}
        feats = await governanca.conversation_features(conn, conversation_id)
    if conv["kind"] == "dm" and members_raw and kinds.get(members_raw[0]["id"]) == "consultor":
        from ..consultor.engine import respond as consultor_respond  # máquina de estados própria (CIA-001 §6)

        if not fichas[members_raw[0]["id"]].ativo:
            await _inactive(owner, conversation_id, members_raw[0], fichas[members_raw[0]["id"]])
            return
        await consultor_respond(llm, owner, conversation_id, message_id)
        return
    low_body = (msg["body"] or "").lower()
    allowed = []
    for m in members_raw:
        f = fichas[m["id"]]
        if not f.ativo:                                           # I4: só agente ativo, com ficha completa, responde
            if conv["kind"] == "dm":
                await _inactive(owner, conversation_id, m, f)
                return
            continue
        if conv["kind"] == "group":
            mentioned = f"@{m['name'].lower()}" in low_body or f"@{m['name'].lower().split()[0]}" in low_body
            if kinds.get(m["id"]) == "consultor" and not (feats["consultor"] and mentioned):
                continue                                          # consultor em grupo: só ligado na conversa e quando mencionado
            if "grupo" not in f.canais and not ("mencao" in f.canais and mentioned):
                continue
        allowed.append(m)
    members = [AgentRow(m["id"], m["name"], m["persona"]) for m in allowed]
    if not members:
        await system_message(owner, conversation_id, "Nenhum agente desta conversa está liberado para responder aqui (ficha de "
                                                     "governança: ativo e canais). Ajuste em Configuração → Governança de IA.")
        return
    if over_budget:
        await system_message(owner, conversation_id, "O orçamento mensal de IA foi atingido. Os agentes voltam a responder "
                                                     "quando o administrador ampliar o teto ou no próximo mês.")
        return
    if daily_limit and used >= daily_limit:
        await system_message(owner, conversation_id, "Limite diário de uso atingido. Os agentes voltam a responder amanhã.")
        return
    recent = "\n".join(f"{'Usuário' if r['author'] == 'user' else r['agent_name']}: {(r['body'] or '')[:400]}" for r in reversed(recent_rows))
    responders, why, ri, ro = await pick_responders(llm, cfg, members, msg["body"] or "", recent, costs.model_for(ai, "router")) if conv["kind"] == "group" \
        else (members, None, 0, 0)
    if ri or ro:
        async with tx(owner) as conn:
            await conn.execute(_t("INSERT INTO usage_event (user_id, model, input_tokens, output_tokens) VALUES (:u, :m, :i, :o)"),
                               {"u": owner, "m": costs.model_for(ai, "router"), "i": ri, "o": ro})
    note = f"{why}: {', '.join(a.name for a in responders)}" if why else None
    try:
        for a in responders:
            await run_agent(llm, owner, conv, a, members, message_id, cfg, note)
    except Cancelled:
        pass
    finally:
        await bus.clear_cancel(conversation_id)
