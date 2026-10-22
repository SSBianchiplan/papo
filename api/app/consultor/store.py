"""Acesso ao banco do Consultor de IA: execução, mensagens tipadas, estados vigentes, selagem do parecer e PDF.

Tudo sob o RLS do dono. Estados, respostas, evidências e pareceres só recebem INSERT (I2); o banco recusa ATENDE sem
evidência validada (I1) e encadeia os pareceres por hash (I3).
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import uuid
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from .. import bus, storage
from ..costs import TZ
from ..db import row, rows, scalar, tx
from ..extract.parsers import _chunk
from . import pdf, rubrica

TIER = "default"


async def load_rubrica(conn: AsyncConnection, versao: str | None = None) -> dict[str, Any]:
    q = "SELECT definicao FROM rubrica_versao WHERE " + ("versao = :v" if versao else "ativa")
    r = await row(conn, q, v=versao) if versao else await row(conn, q)
    if not r:
        raise LookupError("rubrica não encontrada")
    return dict(r["definicao"])


async def avaliacao_atual(conn: AsyncConnection, conversation_id: UUID) -> dict[str, Any] | None:
    return await row(conn, "SELECT * FROM consultor_avaliacao WHERE conversation_id = :c ORDER BY criado_em DESC LIMIT 1", c=conversation_id)


async def nova_avaliacao(conn: AsyncConnection, owner: UUID, conversation_id: UUID, documento_id: UUID | None, titulo: str | None) -> dict[str, Any]:
    versao = await scalar(conn, "SELECT versao FROM rubrica_versao WHERE ativa")
    r = await row(conn, """INSERT INTO consultor_avaliacao (owner_id, conversation_id, rubrica_versao, estado, documento_id, titulo)
                           VALUES (:o, :c, :v, :e, :d, :t) RETURNING *""",
                  o=owner, c=conversation_id, v=versao, e="lendo" if documento_id else "aguardando_documento", d=documento_id, t=titulo)
    assert r
    return r


async def mudar(conn: AsyncConnection, avaliacao_id: UUID, **campos: Any) -> None:
    sets = ", ".join(f"{k} = :{k}" for k in campos)
    await conn.execute(text(f"UPDATE consultor_avaliacao SET {sets}, atualizado_em = now() WHERE id = :id"), {**campos, "id": avaliacao_id})


async def estados(conn: AsyncConnection, avaliacao_id: UUID) -> dict[str, str]:
    return {r["criterio_id"]: r["estado"] for r in await rows(conn, "SELECT criterio_id, estado FROM consultor_estado_vigente WHERE avaliacao_id = :a",
                                                              a=avaliacao_id)}


async def respostas(conn: AsyncConnection, avaliacao_id: UUID) -> list[dict[str, Any]]:
    return await rows(conn, "SELECT criterio_id, indice, resposta FROM consultor_resposta WHERE avaliacao_id = :a ORDER BY id", a=avaliacao_id)


async def gravar_estado(conn: AsyncConnection, owner: UUID, avaliacao_id: UUID, criterio_id: str, estado: str, origem: str, *,
                        evidencia_id: int | None = None, justificativa: str | None = None, trace_id: UUID | None = None) -> None:
    await conn.execute(text("""INSERT INTO consultor_criterio_estado
                                   (avaliacao_id, owner_id, criterio_id, estado, origem, evidencia_id, justificativa, trace_id)
                               VALUES (:a, :o, :c, :e, :g, :ev, :j, :t)"""),
                       {"a": avaliacao_id, "o": owner, "c": criterio_id, "e": estado, "g": origem, "ev": evidencia_id,
                        "j": (justificativa or "")[:500] or None, "t": trace_id or uuid.uuid4()})


async def pagina(conn: AsyncConnection, documento_id: UUID, n: int) -> str | None:
    body = await scalar(conn, "SELECT body FROM doc_chunk WHERE document_id = :d AND ord = :n", d=documento_id, n=n)
    return str(body) if body is not None else None


# ----------------------------------------------------------------- execução e mensagens do consultor
async def abrir_run(conn: AsyncConnection, conversation_id: UUID, trigger_id: UUID, agent: dict[str, Any], model: str) -> UUID:
    run_id = await scalar(conn, """INSERT INTO agent_run (conversation_id, trigger_message_id, agent_id, agent_name, tier, read_mode, model)
                                   VALUES (:c, :m, :a, :n, :t, 'agent', :mo) RETURNING id""",
                          c=conversation_id, m=trigger_id, a=agent["id"], n=agent["name"], t=TIER, mo=model)
    await conn.execute(text("UPDATE agent_run SET status = 'running', started_at = now() WHERE id = :r"), {"r": run_id})
    return UUID(str(run_id))


async def fechar_run(conn: AsyncConnection, run_id: UUID, status: str = "done", error: str | None = None, *, tok_in: int = 0, tok_out: int = 0,
                     calls: int = 0) -> None:
    await conn.execute(text("""UPDATE agent_run SET status = :s, error = :e, input_tokens = :i, output_tokens = :o, tool_calls = :c,
                                      finished_at = now() WHERE id = :r"""),
                       {"s": status, "e": error, "i": tok_in, "o": tok_out, "c": min(calls, 64), "r": run_id})


async def dizer(conn: AsyncConnection, owner: UUID, conversation_id: UUID, agent: dict[str, Any], run_id: UUID, body: str = "", *,
                card: dict[str, Any] | None = None, document_id: UUID | None = None) -> UUID:
    m = await scalar(conn, """INSERT INTO message (conversation_id, author, agent_id, agent_name, body, run_id, card, document_id)
                              VALUES (:c, 'agent', :a, :n, :b, :r, CAST(:card AS jsonb), :d) RETURNING id""",
                     c=conversation_id, a=agent["id"], n=agent["name"], b=body[:20000], r=run_id,
                     card=json.dumps(card, ensure_ascii=False) if card else None, d=document_id)
    return UUID(str(m))


async def publicar(owner: UUID, conversation_id: UUID) -> None:
    await bus.publish(owner, "message.created", {"conversation_id": conversation_id})


async def mensagem_usuario(conn: AsyncConnection, conversation_id: UUID, body: str) -> UUID:
    return UUID(str(await scalar(conn, "INSERT INTO message (conversation_id, author, body) VALUES (:c, 'user', :b) RETURNING id",
                                 c=conversation_id, b=body[:20000])))


def cartao_pergunta(av: dict[str, Any], c: dict[str, Any], restantes: int) -> dict[str, Any]:
    return {"tipo": "pergunta_rapida", "avaliacao_id": str(av["id"]), "criterio_id": c["id"], "critico": c["critico"],
            "pergunta": c["pergunta"], "opcoes": list(c["respostas_rapidas"]), "restantes": restantes}


# ----------------------------------------------------------------- parecer selado
async def selar(conn: AsyncConnection, owner: UUID, av: dict[str, Any]) -> dict[str, Any]:
    """Calcula (função pura), grava o parecer encadeado e gera o PDF a partir do registro selado."""
    defn = await load_rubrica(conn, av["rubrica_versao"])
    est = await estados(conn, av["id"])
    resp = await respostas(conn, av["id"])
    res = rubrica.calcular(defn, camada_real=av["camada_real"], camadas_usadas=list(av["camadas_usadas"] or []),
                           camada_declarada=av["camada_declarada"], camada_minima=av["camada_minima"], estados=est, respostas=resp,
                           desvio_justificativa=av["desvio_justificativa"])
    prev = await row(conn, "SELECT versao, hash FROM consultor_parecer WHERE avaliacao_id = :a ORDER BY versao DESC LIMIT 1", a=av["id"])
    versao = (prev["versao"] + 1) if prev else 1
    par = await row(conn, """INSERT INTO consultor_parecer (avaliacao_id, owner_id, versao, rubrica_versao, resultado, nota_geral, veredito, risco,
                                                           hash_entrada, hash_anterior)
                             VALUES (:a, :o, :v, :rv, CAST(:res AS jsonb), :n, :ve, :ri, :h, :ha) RETURNING id, hash, versao""",
                    a=av["id"], o=owner, v=versao, rv=av["rubrica_versao"], res=json.dumps(res, ensure_ascii=False, sort_keys=True),
                    n=res["nota_geral"], ve=res["veredito"], ri=res["risco"], h=res["hash_entrada"], ha=prev["hash"] if prev else None)
    assert par
    evs = {r["criterio_id"]: r for r in await rows(conn, """SELECT DISTINCT ON (e.criterio_id) e.criterio_id, e.pagina, e.trecho
                                                              FROM consultor_estado_vigente v JOIN consultor_evidencia e ON e.id = v.evidencia_id
                                                             WHERE v.avaliacao_id = :a AND v.estado = 'ATENDE'""", a=av["id"])}
    resp_txt = {r["criterio_id"]: r["resposta"] for r in resp}
    titulo = av["titulo"] or "Proposta de IA"
    data = await asyncio.to_thread(pdf.render, res, titulo=titulo, versao=versao, hash_parecer=par["hash"], evidencias=evs, respostas=resp_txt,
                                   emitido=datetime.now(TZ).strftime("%d/%m/%Y %H:%M"))
    name = f"parecer-ia-v{versao}.pdf"
    key = storage.new_key(owner, "doc", "pdf")
    await storage.put(key, data, "application/pdf")
    sha = hashlib.sha256(data).hexdigest()
    run = await scalar(conn, "SELECT id FROM agent_run WHERE conversation_id = :c ORDER BY queued_at DESC LIMIT 1", c=av["conversation_id"])
    doc = await scalar(conn, """INSERT INTO document (owner_id, conversation_id, filename, mime, size_bytes, sha256, storage_key, kind, origin, run_id)
                                VALUES (:o, :c, :f, 'application/pdf', :s, :h, :k, 'pdf', 'agent', :r) RETURNING id""",
                       o=owner, c=av["conversation_id"], f=name, s=len(data), h=sha, k=key, r=run)
    resumo = (f"Parecer v{versao} · {titulo}\n\nNota {res['nota_geral']} · {rubrica.VEREDITO_TXT[res['veredito']]} · risco {res['risco'].lower()}\n\n"
              + "\n".join(res["condicoes"]))
    for i, (lab, body) in enumerate(_chunk(resumo), start=1):
        await conn.execute(text("INSERT INTO doc_chunk (document_id, ord, label, body) VALUES (:d, :o, :l, :b)"), {"d": doc, "o": i, "l": lab, "b": body})
    await conn.execute(text("UPDATE document SET status = 'ready', pages = 1, note = 'Parecer selado do Consultor de IA', processed_at = now() WHERE id = :d"),
                       {"d": doc})
    await conn.execute(text("UPDATE consultor_parecer SET pdf_document_id = :d, pdf_sha256 = :h WHERE id = :p"), {"d": doc, "h": sha, "p": par["id"]})
    return {"parecer_id": par["id"], "versao": versao, "hash": par["hash"], "resultado": res, "pdf_document_id": doc, "titulo": titulo}


def cartao_parecer(av: dict[str, Any], selado: dict[str, Any]) -> dict[str, Any]:
    r = selado["resultado"]
    return {"tipo": "cartao_parecer", "avaliacao_id": str(av["id"]), "parecer_id": str(selado["parecer_id"]), "versao": selado["versao"],
            "rubrica": r["rubrica"],
            "titulo": selado["titulo"], "camada_declarada": r["camada_declarada"], "camada_real": r["camada_real"],
            "camada_minima": r["camada_minima"], "nota_geral": r["nota_geral"], "notas_bloco": r["notas_bloco"], "veredito": r["veredito"],
            "risco": r["risco"], "condicoes": r["condicoes"], "perguntas_ao_fornecedor": r["perguntas_ao_fornecedor"],
            "criterios": [{"id": c["id"], "texto": c["texto"], "estado": c["estado"], "critico": c["critico"]} for c in r["criterios"]],
            "pdf_document_id": str(selado["pdf_document_id"]), "hash_entrada": "sha256:" + r["hash_entrada"], "hash_parecer": selado["hash"]}


__all__ = ["tx"]
