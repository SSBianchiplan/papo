"""RED-TEAM. Cada teste tenta violar uma invariante pelo banco, sem passar pela API.
Se algum INSERT/UPDATE passar, a invariante não existe — só a intenção dela."""
from __future__ import annotations

import os
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

import psycopg
import pytest

Conn = Callable[[], psycopg.Connection[Any]]


@contextmanager
def as_user(app_conn: Conn, uid: str) -> Iterator[psycopg.Cursor[Any]]:
    with app_conn() as c:
        c.execute("BEGIN")
        c.execute("SELECT set_config('papo.uid', %s, true)", (uid,))
        cur = c.cursor()
        try:
            yield cur
            c.execute("COMMIT")
        except Exception:
            c.execute("ROLLBACK")
            raise


def login(app_conn: Conn, name: str) -> str:
    with app_conn() as c:
        return str(c.execute("SELECT papo_login(%s, NULL, %s)", (f"{name}-{uuid.uuid4()}", name)).fetchone()[0])  # type: ignore[index]


def mk_agent(app_conn: Conn, uid: str, name: str = "Ana") -> str:
    with as_user(app_conn, uid) as cur:
        return str(cur.execute("INSERT INTO agent (owner_id, name) VALUES (%s, %s) RETURNING id", (uid, name)).fetchone()[0])  # type: ignore[index]


def mk_dm(app_conn: Conn, uid: str, agent: str) -> str:
    with as_user(app_conn, uid) as cur:
        return str(cur.execute("INSERT INTO conversation (owner_id, kind, agent_id) VALUES (%s, 'dm', %s) RETURNING id",
                               (uid, agent)).fetchone()[0])  # type: ignore[index]


def mk_msg(app_conn: Conn, uid: str, conv: str, body: str = "oi") -> str:
    with as_user(app_conn, uid) as cur:
        return str(cur.execute("INSERT INTO message (conversation_id, author, body) VALUES (%s, 'user', %s) RETURNING id",
                               (conv, body)).fetchone()[0])  # type: ignore[index]


def mk_run(app_conn: Conn, uid: str, conv: str, msg: str, agent: str) -> str:
    with as_user(app_conn, uid) as cur:
        return str(cur.execute("""INSERT INTO agent_run (conversation_id, trigger_message_id, agent_id, agent_name, tier, read_mode, model)
                                  VALUES (%s, %s, %s, 'Ana', 'default', 'none', 'm') RETURNING id""",
                               (conv, msg, agent)).fetchone()[0])  # type: ignore[index]


@pytest.fixture
def world(app_conn: Conn) -> dict[str, str]:
    a = login(app_conn, "alice")
    b = login(app_conn, "bruno")
    ag = mk_agent(app_conn, a)
    conv = mk_dm(app_conn, a, ag)
    return {"a": a, "b": b, "agent": ag, "conv": conv, "agent_b": mk_agent(app_conn, b, "Beto")}


REJECT = (psycopg.errors.CheckViolation, psycopg.errors.InsufficientPrivilege, psycopg.errors.ForeignKeyViolation,
          psycopg.errors.UniqueViolation, psycopg.errors.RaiseException, psycopg.errors.NotNullViolation)


# ------------------------------------------------------------------ conversas
def test_inv_cnv_001_dm_com_nome_recusada(app_conn: Conn, world: dict[str, str]) -> None:
    ag = mk_agent(app_conn, world["a"], "Outro")
    with pytest.raises(psycopg.errors.CheckViolation), as_user(app_conn, world["a"]) as cur:
        cur.execute("INSERT INTO conversation (owner_id, kind, agent_id, name) VALUES (%s, 'dm', %s, 'x')", (world["a"], ag))


def test_inv_cnv_001_grupo_sem_nome_recusado(app_conn: Conn, world: dict[str, str]) -> None:
    with pytest.raises(psycopg.errors.CheckViolation), as_user(app_conn, world["a"]) as cur:
        cur.execute("INSERT INTO conversation (owner_id, kind, name) VALUES (%s, 'group', '   ')", (world["a"],))


def test_inv_cnv_002_agente_de_outro_usuario_recusado(app_conn: Conn, world: dict[str, str]) -> None:
    with pytest.raises(REJECT), as_user(app_conn, world["a"]) as cur:
        cur.execute("INSERT INTO conversation (owner_id, kind, agent_id) VALUES (%s, 'dm', %s)", (world["a"], world["agent_b"]))


def test_inv_cnv_003_segunda_dm_com_mesmo_agente_recusada(app_conn: Conn, world: dict[str, str]) -> None:
    with pytest.raises(psycopg.errors.UniqueViolation), as_user(app_conn, world["a"]) as cur:
        cur.execute("INSERT INTO conversation (owner_id, kind, agent_id) VALUES (%s, 'dm', %s)", (world["a"], world["agent"]))


def test_inv_cnv_005_membro_em_dm_recusado(app_conn: Conn, world: dict[str, str]) -> None:
    with pytest.raises(psycopg.errors.CheckViolation), as_user(app_conn, world["a"]) as cur:
        cur.execute("INSERT INTO conversation_member (conversation_id, owner_id, agent_id) VALUES (%s, %s, %s)",
                    (world["conv"], world["a"], world["agent"]))


# ------------------------------------------------------------------ isolamento
def test_inv_sec_001_rls_nao_vaza_entre_usuarios(app_conn: Conn, world: dict[str, str]) -> None:
    mk_msg(app_conn, world["a"], world["conv"], "segredo da alice")
    with as_user(app_conn, world["b"]) as cur:
        assert cur.execute("SELECT count(*) FROM conversation WHERE owner_id = %s", (world["a"],)).fetchone()[0] == 0  # type: ignore[index]
        assert cur.execute("SELECT count(*) FROM message WHERE body LIKE 'segredo%%'").fetchone()[0] == 0  # type: ignore[index]
        assert cur.execute("SELECT count(*) FROM agent WHERE id = %s", (world["agent"],)).fetchone()[0] == 0  # type: ignore[index]


def test_inv_sec_001_rls_recusa_escrever_em_nome_de_outro(app_conn: Conn, world: dict[str, str]) -> None:
    with pytest.raises(psycopg.errors.InsufficientPrivilege), as_user(app_conn, world["b"]) as cur:
        cur.execute("INSERT INTO agent (owner_id, name) VALUES (%s, 'Intruso')", (world["a"],))


def test_inv_sec_001_sem_usuario_nao_ve_nada(app_conn: Conn, world: dict[str, str]) -> None:
    with app_conn() as c:
        assert c.execute("SELECT count(*) FROM agent").fetchone()[0] == 0  # type: ignore[index]


def test_inv_sec_001_mensagem_em_conversa_alheia_recusada(app_conn: Conn, world: dict[str, str]) -> None:
    with pytest.raises(REJECT), as_user(app_conn, world["b"]) as cur:
        cur.execute("INSERT INTO message (conversation_id, author, body) VALUES (%s, 'user', 'oi')", (world["conv"],))


# ------------------------------------------------------------------ mensagens
def test_inv_msg_001_seq_sem_lacunas(app_conn: Conn, world: dict[str, str]) -> None:
    for i in range(3):
        mk_msg(app_conn, world["a"], world["conv"], f"m{i}")
    with as_user(app_conn, world["a"]) as cur:
        seqs = [r[0] for r in cur.execute("SELECT seq FROM message WHERE conversation_id = %s ORDER BY seq", (world["conv"],))]
    assert seqs == list(range(1, len(seqs) + 1))


def test_inv_msg_003_mensagem_vazia_recusada(app_conn: Conn, world: dict[str, str]) -> None:
    with pytest.raises(psycopg.errors.CheckViolation), as_user(app_conn, world["a"]) as cur:
        cur.execute("INSERT INTO message (conversation_id, author, body) VALUES (%s, 'user', '  ')", (world["conv"],))


def test_inv_msg_002_agente_sem_execucao_recusado(app_conn: Conn, world: dict[str, str]) -> None:
    with pytest.raises(psycopg.errors.CheckViolation), as_user(app_conn, world["a"]) as cur:
        cur.execute("INSERT INTO message (conversation_id, author, agent_name, body) VALUES (%s, 'agent', 'Ana', 'oi')", (world["conv"],))


def test_inv_msg_004_imagem_de_outro_dono_recusada(app_conn: Conn, world: dict[str, str]) -> None:
    with pytest.raises(psycopg.errors.CheckViolation), as_user(app_conn, world["a"]) as cur:
        cur.execute("INSERT INTO message (conversation_id, author, image_key) VALUES (%s, 'user', %s)",
                    (world["conv"], f"{world['b']}/img/x.jpg"))


def test_inv_msg_005_update_recusado_para_app(app_conn: Conn, world: dict[str, str]) -> None:
    mid = mk_msg(app_conn, world["a"], world["conv"])
    with pytest.raises(psycopg.errors.InsufficientPrivilege), as_user(app_conn, world["a"]) as cur:
        cur.execute("UPDATE message SET body = 'adulterado' WHERE id = %s", (mid,))


def test_inv_msg_005_update_recusado_ate_para_o_dono_do_schema(owner_conn: Conn, app_conn: Conn, world: dict[str, str]) -> None:
    mid = mk_msg(app_conn, world["a"], world["conv"])
    with pytest.raises(psycopg.errors.InsufficientPrivilege), owner_conn() as c:
        c.execute("UPDATE message SET body = 'adulterado' WHERE id = %s", (mid,))


def test_inv_msg_005_delete_recusado_para_app(app_conn: Conn, world: dict[str, str]) -> None:
    mid = mk_msg(app_conn, world["a"], world["conv"])
    with pytest.raises(psycopg.errors.InsufficientPrivilege), as_user(app_conn, world["a"]) as cur:
        cur.execute("DELETE FROM message WHERE id = %s", (mid,))


# ------------------------------------------------------------------ recibos
def test_inv_rcp_001_lido_antes_de_entregue_recusado(app_conn: Conn, world: dict[str, str]) -> None:
    mid = mk_msg(app_conn, world["a"], world["conv"])
    with pytest.raises(psycopg.errors.CheckViolation), as_user(app_conn, world["a"]) as cur:
        cur.execute("INSERT INTO message_receipt (message_id, state) VALUES (%s, 'read')", (mid,))


def test_inv_rcp_001_enviado_automatico_e_ordem_valida(app_conn: Conn, world: dict[str, str]) -> None:
    mid = mk_msg(app_conn, world["a"], world["conv"])
    with as_user(app_conn, world["a"]) as cur:
        cur.execute("INSERT INTO message_receipt (message_id, state) VALUES (%s, 'delivered')", (mid,))
        cur.execute("INSERT INTO message_receipt (message_id, state) VALUES (%s, 'read')", (mid,))
        states = [r[0] for r in cur.execute("SELECT state FROM message_receipt WHERE message_id = %s ORDER BY at", (mid,))]
    assert states == ["sent", "delivered", "read"]


def test_recibo_e_append_only(app_conn: Conn, owner_conn: Conn, world: dict[str, str]) -> None:
    mid = mk_msg(app_conn, world["a"], world["conv"])
    with pytest.raises(psycopg.errors.InsufficientPrivilege), owner_conn() as c:
        c.execute("UPDATE message_receipt SET at = now() - interval '1 day' WHERE message_id = %s", (mid,))


# ------------------------------------------------------------------ execuções
def test_inv_run_001_transicao_proibida(app_conn: Conn, world: dict[str, str]) -> None:
    mid = mk_msg(app_conn, world["a"], world["conv"])
    rid = mk_run(app_conn, world["a"], world["conv"], mid, world["agent"])
    with as_user(app_conn, world["a"]) as cur:
        cur.execute("UPDATE agent_run SET status = 'running', started_at = now() WHERE id = %s", (rid,))
        cur.execute("UPDATE agent_run SET status = 'done', finished_at = now() WHERE id = %s", (rid,))
    with pytest.raises(psycopg.errors.CheckViolation), as_user(app_conn, world["a"]) as cur:
        cur.execute("UPDATE agent_run SET status = 'running', finished_at = NULL WHERE id = %s", (rid,))


def test_inv_run_002_terminal_sem_finished_at_recusado(app_conn: Conn, world: dict[str, str]) -> None:
    mid = mk_msg(app_conn, world["a"], world["conv"])
    rid = mk_run(app_conn, world["a"], world["conv"], mid, world["agent"])
    with pytest.raises(psycopg.errors.CheckViolation), as_user(app_conn, world["a"]) as cur:
        cur.execute("UPDATE agent_run SET status = 'cancelled' WHERE id = %s", (rid,))


def test_inv_run_003_agente_fora_da_conversa_recusado(app_conn: Conn, world: dict[str, str]) -> None:
    outro = mk_agent(app_conn, world["a"], "Carla")
    mid = mk_msg(app_conn, world["a"], world["conv"])
    with pytest.raises(psycopg.errors.CheckViolation):
        mk_run(app_conn, world["a"], world["conv"], mid, outro)


def test_inv_run_004_tokens_nao_diminuem(app_conn: Conn, world: dict[str, str]) -> None:
    mid = mk_msg(app_conn, world["a"], world["conv"])
    rid = mk_run(app_conn, world["a"], world["conv"], mid, world["agent"])
    with as_user(app_conn, world["a"]) as cur:
        cur.execute("UPDATE agent_run SET status = 'running', started_at = now(), input_tokens = 100 WHERE id = %s", (rid,))
    with pytest.raises(psycopg.errors.CheckViolation), as_user(app_conn, world["a"]) as cur:
        cur.execute("UPDATE agent_run SET input_tokens = 10 WHERE id = %s", (rid,))


def test_inv_run_005_duas_execucoes_ativas_recusadas(app_conn: Conn, world: dict[str, str]) -> None:
    mid = mk_msg(app_conn, world["a"], world["conv"])
    mk_run(app_conn, world["a"], world["conv"], mid, world["agent"])
    with pytest.raises(psycopg.errors.UniqueViolation):
        mk_run(app_conn, world["a"], world["conv"], mid, world["agent"])


# ------------------------------------------------------------------ trilha SHA-256
def test_inv_aud_001_hash_calculado_pelo_banco_e_cadeia_integra(app_conn: Conn, world: dict[str, str]) -> None:
    mid = mk_msg(app_conn, world["a"], world["conv"])
    rid = mk_run(app_conn, world["a"], world["conv"], mid, world["agent"])
    with as_user(app_conn, world["a"]) as cur:
        for k in ("started", "tool_call", "answer"):
            cur.execute("INSERT INTO agent_run_event (run_id, kind, payload, hash) VALUES (%s, %s, '{}', %s)", (rid, k, "f" * 64))
        hashes = cur.execute("SELECT prev_hash, hash FROM agent_run_event WHERE run_id = %s ORDER BY id", (rid,)).fetchall()
        assert all(h != "f" * 64 for _, h in hashes)                     # valor da aplicação descartado
        assert hashes[0][0] is None and hashes[1][0] == hashes[0][1] and hashes[2][0] == hashes[1][1]
        assert cur.execute("SELECT count(*) FROM verify_run_chain(%s)", (rid,)).fetchone()[0] == 0  # type: ignore[index]


def test_inv_aud_001_adulteracao_detectada(app_conn: Conn, world: dict[str, str]) -> None:
    mid = mk_msg(app_conn, world["a"], world["conv"])
    rid = mk_run(app_conn, world["a"], world["conv"], mid, world["agent"])
    with as_user(app_conn, world["a"]) as cur:
        for k in ("started", "answer"):
            cur.execute("INSERT INTO agent_run_event (run_id, kind, payload, hash) VALUES (%s, %s, '{\"x\":1}', %s)", (rid, k, "0" * 64))
    admin = os.environ.get("TEST_PG_ADMIN", "postgresql://postgres@127.0.0.1:5433/postgres").rsplit("/", 1)[0]
    db = os.environ["DATABASE_URL"].rsplit("/", 1)[1]
    with psycopg.connect(f"{admin}/{db}", autocommit=True) as su:   # superusuário desliga a proteção e adultera
        su.execute("ALTER TABLE agent_run_event DISABLE TRIGGER run_event_no_update")
        su.execute("""UPDATE agent_run_event SET payload = '{"x":2}' WHERE run_id = %s AND kind = 'started'""", (rid,))
        su.execute("ALTER TABLE agent_run_event ENABLE TRIGGER run_event_no_update")
    with as_user(app_conn, world["a"]) as cur:
        problem = cur.execute("SELECT problem FROM verify_run_chain(%s)", (rid,)).fetchone()
    assert problem is not None and problem[0] == "hash não confere"


def test_trilha_update_recusado(app_conn: Conn, owner_conn: Conn, world: dict[str, str]) -> None:
    mid = mk_msg(app_conn, world["a"], world["conv"])
    rid = mk_run(app_conn, world["a"], world["conv"], mid, world["agent"])
    with as_user(app_conn, world["a"]) as cur:
        cur.execute("INSERT INTO agent_run_event (run_id, kind, hash) VALUES (%s, 'started', %s)", (rid, "0" * 64))
    with pytest.raises(psycopg.errors.InsufficientPrivilege), owner_conn() as c:
        c.execute("UPDATE agent_run_event SET kind = 'answer' WHERE run_id = %s", (rid,))


# ------------------------------------------------------------------ documentos
def _doc(cur: psycopg.Cursor[Any], uid: str, agent: str | None, conv: str | None, key: str | None = None) -> str:
    return str(cur.execute("""INSERT INTO document (owner_id, agent_id, conversation_id, filename, mime, size_bytes, sha256, storage_key, kind)
                              VALUES (%s, %s, %s, 'a.pdf', 'application/pdf', 10, %s, %s, 'pdf') RETURNING id""",
                           (uid, agent, conv, "a" * 64, key or f"{uid}/doc/{uuid.uuid4()}.pdf")).fetchone()[0])  # type: ignore[index]


def test_inv_doc_001_sem_escopo_recusado(app_conn: Conn, world: dict[str, str]) -> None:
    with pytest.raises(psycopg.errors.CheckViolation), as_user(app_conn, world["a"]) as cur:
        _doc(cur, world["a"], None, None)


def test_inv_doc_003_chave_de_outro_dono_recusada(app_conn: Conn, world: dict[str, str]) -> None:
    with pytest.raises(psycopg.errors.CheckViolation), as_user(app_conn, world["a"]) as cur:
        _doc(cur, world["a"], world["agent"], None, key=f"{world['b']}/doc/x.pdf")


def test_inv_doc_004_documento_processado_nao_volta(app_conn: Conn, world: dict[str, str]) -> None:
    with as_user(app_conn, world["a"]) as cur:
        did = _doc(cur, world["a"], world["agent"], None)
        cur.execute("UPDATE document SET status = 'ready', processed_at = now() WHERE id = %s", (did,))
    with pytest.raises(psycopg.errors.CheckViolation), as_user(app_conn, world["a"]) as cur:
        cur.execute("UPDATE document SET status = 'pending', processed_at = NULL WHERE id = %s", (did,))


def test_inv_msg_004_anexo_de_outra_conversa_recusado(app_conn: Conn, world: dict[str, str]) -> None:
    ag2 = mk_agent(app_conn, world["a"], "Dora")
    conv2 = mk_dm(app_conn, world["a"], ag2)
    with as_user(app_conn, world["a"]) as cur:
        did = _doc(cur, world["a"], None, conv2)
    with pytest.raises(psycopg.errors.CheckViolation), as_user(app_conn, world["a"]) as cur:
        cur.execute("INSERT INTO message (conversation_id, author, document_id) VALUES (%s, 'user', %s)", (world["conv"], did))


# ------------------------------------------------------------------ preferências
@pytest.mark.parametrize("data", ['{"tier": "turbo"}', '{"groupMax": 9}', '{"readMode": "x"}', '[]'])
def test_preferencias_invalidas_recusadas(app_conn: Conn, world: dict[str, str], data: str) -> None:
    with pytest.raises(REJECT + (psycopg.errors.InvalidTextRepresentation,)), as_user(app_conn, world["a"]) as cur:
        cur.execute("INSERT INTO user_settings (user_id, data) VALUES (%s, %s::jsonb)", (world["a"], data))


def test_exclusao_de_conta_apaga_tudo_em_cascata(app_conn: Conn, world: dict[str, str]) -> None:
    mk_msg(app_conn, world["a"], world["conv"])
    with as_user(app_conn, world["a"]) as cur:
        cur.execute("DELETE FROM app_user WHERE id = %s", (world["a"],))
    with as_user(app_conn, world["a"]) as cur:
        assert cur.execute("SELECT count(*) FROM conversation").fetchone()[0] == 0  # type: ignore[index]


def test_reaper_libera_conversa_com_execucao_orfa(app_conn: Conn, owner_conn: Conn, world: dict[str, str]) -> None:
    mid = mk_msg(app_conn, world["a"], world["conv"])
    rid = mk_run(app_conn, world["a"], world["conv"], mid, world["agent"])
    with as_user(app_conn, world["a"]) as cur:
        cur.execute("UPDATE agent_run SET status = 'running', started_at = now() - interval '2 hours' WHERE id = %s", (rid,))
    with app_conn() as c:                                   # roda sem usuário, como o worker
        assert c.execute("SELECT papo_reap_runs(interval '20 minutes')").fetchone()[0] >= 1  # type: ignore[index]
    with as_user(app_conn, world["a"]) as cur:
        assert cur.execute("SELECT status FROM agent_run WHERE id = %s", (rid,)).fetchone()[0] == "failed"  # type: ignore[index]
    mk_run(app_conn, world["a"], world["conv"], mid, world["agent"])   # conversa liberada


def test_reaper_nao_toca_execucao_recente(app_conn: Conn, world: dict[str, str]) -> None:
    mid = mk_msg(app_conn, world["a"], world["conv"])
    rid = mk_run(app_conn, world["a"], world["conv"], mid, world["agent"])
    with app_conn() as c:
        c.execute("SELECT papo_reap_runs(interval '20 minutes')")
    with as_user(app_conn, world["a"]) as cur:
        assert cur.execute("SELECT status FROM agent_run WHERE id = %s", (rid,)).fetchone()[0] == "queued"  # type: ignore[index]
