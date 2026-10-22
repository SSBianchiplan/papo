"""Worker arq: leitura de arquivos e respostas dos agentes, fora do processo da API."""
from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from arq import cron
from sqlalchemy import text

from . import costs, secretbox
from .agent.engine import respond
from .agent.llm import LLM, AnthropicLLM, EchoLLM, UnconfiguredLLM
from .bus import arq_settings, redis
from .config import get_settings
from .extract.service import process_document

logging.basicConfig(level=logging.INFO, format='{"t":"%(asctime)s","lvl":"%(levelname)s","log":"%(name)s","msg":"%(message)s"}')


async def startup(ctx: dict[str, Any]) -> None:
    await reap(ctx)                              # limpa o que ficou da queda anterior
    ctx["llm_cache"] = {}


async def current_llm(ctx: dict[str, Any]) -> LLM:
    """Cliente da IA com a chave em uso agora (painel > .env). Trocar a chave no painel vale no próximo job, sem reiniciar."""
    from .db import tx

    s = get_settings()
    if s.llm_provider == "echo":
        return EchoLLM()
    if "llm" in ctx:                             # testes injetam um modelo falso
        return ctx["llm"]  # type: ignore[no-any-return]
    async with tx(None) as conn:
        key, ws, _ = costs.credentials(await costs.load_ai_config(conn))
    if not key:
        return UnconfiguredLLM()
    cache: dict[str, LLM] = ctx.setdefault("llm_cache", {})
    fp = secretbox.fingerprint(key, ws)
    if fp not in cache:
        cache.clear()
        cache[fp] = AnthropicLLM(key, ws)
    return cache[fp]


async def job_test_key(ctx: dict[str, Any]) -> dict[str, Any]:
    """Testa a chave em uso. Devolve só o diagnóstico; a chave nunca sai do worker."""
    from .agent.engine import friendly_error

    llm = await current_llm(ctx)
    if not isinstance(llm, AnthropicLLM):
        return {"ok": False, "message": "Nenhuma chave configurada."}
    try:
        r = await llm.check(get_settings().model_quick)
    except Exception as e:  # noqa: BLE001 — o diagnóstico vira mensagem para o administrador
        detail = getattr(e, "message", None) or str(e)
        return {"ok": False, "message": friendly_error(e), "detail": str(detail)[:300]}
    from .db import tx

    async with tx(None) as conn:          # lembra o que a conta enxerga: o painel marca o catálogo com isso
        await conn.execute(text("UPDATE app_config SET models_available = :m, models_checked_at = now()"), {"m": r["models"]})
    return {"ok": True, "message": f"Chave válida. {len(r['models'])} modelos disponíveis.", **r}


async def job_document(ctx: dict[str, Any], owner: str, document_id: str) -> None:
    await process_document(UUID(owner), UUID(document_id))


async def job_respond(ctx: dict[str, Any], owner: str, conversation_id: str, message_id: str) -> None:
    try:
        await respond(await current_llm(ctx), UUID(owner), UUID(conversation_id), UUID(message_id))
    finally:
        await redis().delete(f"papo:busy:{conversation_id}")     # libera a conversa para a próxima mensagem


async def reap(ctx: dict[str, Any]) -> int:
    """Marca como falha execuções presas há mais que o timeout do job (worker caiu no meio)."""
    from .db import scalar, tx

    async with tx(None) as conn:
        n = int(await scalar(conn, "SELECT papo_reap_runs(make_interval(secs => :s))", s=WorkerSettings.job_timeout + 60))
    if n:
        logging.getLogger("papo.reaper").warning("execuções órfãs encerradas: %s", n)
    return n


async def hub_reindex(ctx: dict[str, Any]) -> int:
    """Atualiza o índice (só metadados) das fontes do hub que estão ligadas. Uma fonte fora do ar não trava as outras."""
    from .db import rows, tx
    from .errors import DomainError
    from .modules.hub import index_source

    async with tx(None) as conn:
        ids = [r["id"] for r in await rows(conn, "SELECT id FROM hub_source WHERE enabled")]
    done = 0
    for sid in ids:
        try:
            await index_source(sid)
            done += 1
        except DomainError as e:
            logging.getLogger("papo.hub").warning("índice do hub falhou em %s: %s", sid, e.message)
    return done


class WorkerSettings:
    functions = [job_document, job_respond, job_test_key]
    cron_jobs = [cron(reap, second=0),          # a cada minuto
                 cron(hub_reindex, minute={7, 37}, second=30, timeout=900)]   # índice do hub a cada 30 min
    on_startup = startup
    redis_settings = arq_settings()
    max_jobs = 8
    job_timeout = 900
    max_tries = 1          # resposta não é idempotente: não reexecutar sozinho
    keep_result = 60
    health_check_interval = 60
