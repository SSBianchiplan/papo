-- =====================================================================
-- Papo · schema 0001
-- Invariantes (RFC-2119) referenciadas como INV-xxx em docs/SPEC-PAPO-001.md.
-- Executado pelo papel dono (papo_owner). A aplicação usa papo_app.
-- =====================================================================
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS unaccent;

-- unaccent não é IMMUTABLE; o wrapper fixa o dicionário e permite índice/coluna gerada
CREATE FUNCTION f_unaccent(text) RETURNS text
LANGUAGE sql IMMUTABLE PARALLEL SAFE STRICT
AS $$ SELECT public.unaccent('public.unaccent'::regdictionary, $1) $$;

-- usuário corrente da transação (SET LOCAL papo.uid) — base do RLS
CREATE FUNCTION papo_uid() RETURNS uuid
LANGUAGE sql STABLE
AS $$ SELECT nullif(current_setting('papo.uid', true), '')::uuid $$;

-- ---------------------------------------------------------------------
-- Usuários e preferências
-- ---------------------------------------------------------------------
CREATE TABLE app_user (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  sub          text NOT NULL UNIQUE CHECK (length(sub) BETWEEN 1 AND 255),
  email        text CHECK (email IS NULL OR length(email) <= 320),
  display_name text NOT NULL DEFAULT '' CHECK (length(display_name) <= 120),
  created_at   timestamptz NOT NULL DEFAULT now()
);

-- login: única porta de entrada para criar/achar o usuário antes de existir papo.uid
CREATE FUNCTION papo_login(p_sub text, p_email text, p_name text) RETURNS uuid
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
DECLARE v_id uuid;
BEGIN
  INSERT INTO app_user (sub, email, display_name)
  VALUES (p_sub, p_email, left(coalesce(p_name, ''), 120))
  ON CONFLICT (sub) DO UPDATE
     SET email = EXCLUDED.email,
         display_name = CASE WHEN EXCLUDED.display_name <> '' THEN EXCLUDED.display_name ELSE app_user.display_name END
  RETURNING id INTO v_id;
  RETURN v_id;
END $$;

CREATE TABLE user_settings (
  user_id    uuid PRIMARY KEY REFERENCES app_user (id) ON DELETE CASCADE,
  data       jsonb NOT NULL DEFAULT '{}'::jsonb,
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT settings_object    CHECK (jsonb_typeof(data) = 'object'),
  CONSTRAINT settings_tier      CHECK (NOT data ? 'tier'      OR data->>'tier' IN ('quick','default','complex')),
  CONSTRAINT settings_read_mode CHECK (NOT data ? 'readMode'  OR data->>'readMode' IN ('agent','direct')),
  CONSTRAINT settings_length    CHECK (NOT data ? 'length'    OR data->>'length' IN ('curta','media','detalhada')),
  CONSTRAINT settings_group     CHECK (NOT data ? 'groupMode' OR data->>'groupMode' IN ('auto','todos')),
  CONSTRAINT settings_group_max CHECK (NOT data ? 'groupMax'  OR (jsonb_typeof(data->'groupMax') = 'number' AND (data->>'groupMax')::numeric IN (1,2,3)))
);

-- ---------------------------------------------------------------------
-- Agentes
-- ---------------------------------------------------------------------
CREATE TABLE agent (
  id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  owner_id   uuid NOT NULL REFERENCES app_user (id) ON DELETE CASCADE,
  name       text NOT NULL CHECK (length(btrim(name)) BETWEEN 1 AND 40),
  emoji      text NOT NULL DEFAULT '🤖' CHECK (length(emoji) BETWEEN 1 AND 8),
  color      text NOT NULL DEFAULT '#1F8A70' CHECK (color ~ '^#[0-9A-Fa-f]{6}$'),
  persona    text NOT NULL DEFAULT '' CHECK (length(persona) <= 4000),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (owner_id, id)
);
-- INV-AGT-001: nome único por usuário, sem diferenciar maiúsculas
CREATE UNIQUE INDEX agent_owner_name_uq ON agent (owner_id, lower(btrim(name)));

-- ---------------------------------------------------------------------
-- Conversas
-- ---------------------------------------------------------------------
CREATE TABLE conversation (
  id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  owner_id         uuid NOT NULL REFERENCES app_user (id) ON DELETE CASCADE,
  kind             text NOT NULL CHECK (kind IN ('dm','group')),
  agent_id         uuid,
  name             text,
  emoji            text NOT NULL DEFAULT '👥' CHECK (length(emoji) BETWEEN 1 AND 8),
  color            text NOT NULL DEFAULT '#5B6B8C' CHECK (color ~ '^#[0-9A-Fa-f]{6}$'),
  next_seq         bigint NOT NULL DEFAULT 1 CHECK (next_seq >= 1),
  created_at       timestamptz NOT NULL DEFAULT now(),
  last_activity_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (owner_id, id),
  -- INV-CNV-002: o agente da conversa pertence ao mesmo usuário (FK composta)
  FOREIGN KEY (owner_id, agent_id) REFERENCES agent (owner_id, id) ON DELETE CASCADE,
  -- INV-CNV-001: forma da conversa
  CONSTRAINT conversation_shape CHECK (
       (kind = 'dm'    AND agent_id IS NOT NULL AND name IS NULL)
    OR (kind = 'group' AND agent_id IS NULL AND name IS NOT NULL AND length(btrim(name)) BETWEEN 1 AND 50))
);
-- INV-CNV-003: no máximo uma conversa individual por agente
CREATE UNIQUE INDEX conversation_one_dm_uq ON conversation (owner_id, agent_id) WHERE kind = 'dm';
CREATE INDEX conversation_owner_activity ON conversation (owner_id, last_activity_at DESC);

CREATE TABLE conversation_member (
  conversation_id uuid NOT NULL,
  owner_id        uuid NOT NULL,
  agent_id        uuid NOT NULL,
  PRIMARY KEY (conversation_id, agent_id),
  -- INV-CNV-004: membros e grupo do mesmo usuário
  FOREIGN KEY (owner_id, conversation_id) REFERENCES conversation (owner_id, id) ON DELETE CASCADE,
  FOREIGN KEY (owner_id, agent_id)        REFERENCES agent (owner_id, id) ON DELETE CASCADE
);

CREATE FUNCTION trg_member_group_only() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  -- INV-CNV-005: membros só existem em grupo
  IF NOT EXISTS (SELECT 1 FROM conversation WHERE id = NEW.conversation_id AND kind = 'group') THEN
    RAISE EXCEPTION 'INV-CNV-005: membros só podem ser adicionados a grupos' USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER member_group_only BEFORE INSERT OR UPDATE ON conversation_member
  FOR EACH ROW EXECUTE FUNCTION trg_member_group_only();

-- ---------------------------------------------------------------------
-- Documentos (base do agente ou anexo da conversa)
-- ---------------------------------------------------------------------
CREATE TABLE document (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  owner_id        uuid NOT NULL REFERENCES app_user (id) ON DELETE CASCADE,
  agent_id        uuid,
  conversation_id uuid,
  filename        text NOT NULL CHECK (length(filename) BETWEEN 1 AND 255),
  mime            text NOT NULL CHECK (length(mime) BETWEEN 1 AND 255),
  size_bytes      bigint NOT NULL CHECK (size_bytes BETWEEN 1 AND 52428800),
  sha256          text NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
  storage_key     text NOT NULL UNIQUE,
  kind            text NOT NULL CHECK (kind IN ('pdf','docx','table','text','other')),
  status          text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','ready','unreadable','failed')),
  pages           integer CHECK (pages IS NULL OR pages >= 0),
  note            text CHECK (note IS NULL OR length(note) <= 500),
  created_at      timestamptz NOT NULL DEFAULT now(),
  processed_at    timestamptz,
  FOREIGN KEY (owner_id, agent_id)        REFERENCES agent (owner_id, id) ON DELETE CASCADE,
  FOREIGN KEY (owner_id, conversation_id) REFERENCES conversation (owner_id, id) ON DELETE CASCADE,
  -- INV-DOC-001: pertence a exatamente um escopo
  CONSTRAINT document_scope CHECK (num_nonnulls(agent_id, conversation_id) = 1),
  -- INV-DOC-002: processado ⇔ fora de pending
  CONSTRAINT document_processed CHECK ((status = 'pending') = (processed_at IS NULL)),
  -- INV-DOC-003: a chave no storage é prefixada pelo dono
  CONSTRAINT document_key_owner CHECK (storage_key LIKE owner_id::text || '/%')
);
CREATE INDEX document_agent ON document (agent_id) WHERE agent_id IS NOT NULL;
CREATE INDEX document_conversation ON document (conversation_id) WHERE conversation_id IS NOT NULL;

CREATE FUNCTION trg_document_transition() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  -- INV-DOC-004: só sai de pending, uma vez; identidade do arquivo é imutável
  IF OLD.status <> 'pending' THEN
    RAISE EXCEPTION 'INV-DOC-004: documento já processado não muda' USING ERRCODE = 'check_violation';
  END IF;
  IF (NEW.owner_id, NEW.agent_id, NEW.conversation_id, NEW.filename, NEW.mime, NEW.size_bytes, NEW.sha256, NEW.storage_key, NEW.kind)
     IS DISTINCT FROM
     (OLD.owner_id, OLD.agent_id, OLD.conversation_id, OLD.filename, OLD.mime, OLD.size_bytes, OLD.sha256, OLD.storage_key, OLD.kind) THEN
    RAISE EXCEPTION 'INV-DOC-004: identidade do documento é imutável' USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER document_transition BEFORE UPDATE ON document
  FOR EACH ROW EXECUTE FUNCTION trg_document_transition();

CREATE TABLE doc_chunk (
  document_id uuid NOT NULL REFERENCES document (id) ON DELETE CASCADE,
  ord         integer NOT NULL CHECK (ord >= 1),
  label       text NOT NULL CHECK (length(label) BETWEEN 1 AND 60),
  body        text NOT NULL CHECK (length(body) <= 40000),
  tsv         tsvector GENERATED ALWAYS AS (to_tsvector('portuguese'::regconfig, f_unaccent(body))) STORED,
  PRIMARY KEY (document_id, ord)
);
CREATE INDEX doc_chunk_tsv ON doc_chunk USING gin (tsv);

CREATE TABLE doc_sheet (
  document_id uuid NOT NULL REFERENCES document (id) ON DELETE CASCADE,
  ord         integer NOT NULL CHECK (ord >= 1),
  name        text NOT NULL CHECK (length(name) BETWEEN 1 AND 120),
  columns     jsonb NOT NULL CHECK (jsonb_typeof(columns) = 'array' AND jsonb_array_length(columns) BETWEEN 1 AND 500),
  total_rows  integer NOT NULL CHECK (total_rows >= 0),
  stored_rows integer NOT NULL CHECK (stored_rows BETWEEN 0 AND total_rows),
  PRIMARY KEY (document_id, ord)
);

CREATE TABLE doc_row (
  document_id uuid NOT NULL,
  sheet_ord   integer NOT NULL,
  ord         integer NOT NULL CHECK (ord >= 1),
  cells       jsonb NOT NULL CHECK (jsonb_typeof(cells) = 'array'),
  PRIMARY KEY (document_id, sheet_ord, ord),
  FOREIGN KEY (document_id, sheet_ord) REFERENCES doc_sheet (document_id, ord) ON DELETE CASCADE
);

-- ---------------------------------------------------------------------
-- Execuções de agente (antes de message por causa da FK)
-- ---------------------------------------------------------------------
CREATE TABLE agent_run (
  id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  conversation_id    uuid NOT NULL REFERENCES conversation (id) ON DELETE CASCADE,
  trigger_message_id uuid NOT NULL,
  agent_id           uuid REFERENCES agent (id) ON DELETE SET NULL,
  agent_name         text NOT NULL CHECK (length(agent_name) BETWEEN 1 AND 40),
  status             text NOT NULL DEFAULT 'queued' CHECK (status IN ('queued','running','done','failed','cancelled')),
  tier               text NOT NULL CHECK (tier IN ('quick','default','complex')),
  read_mode          text NOT NULL CHECK (read_mode IN ('agent','direct','none')),
  model              text NOT NULL CHECK (length(model) BETWEEN 1 AND 100),
  input_tokens       integer NOT NULL DEFAULT 0 CHECK (input_tokens >= 0),
  output_tokens      integer NOT NULL DEFAULT 0 CHECK (output_tokens >= 0),
  tool_calls         integer NOT NULL DEFAULT 0 CHECK (tool_calls BETWEEN 0 AND 64),
  error              text CHECK (error IS NULL OR length(error) <= 1000),
  queued_at          timestamptz NOT NULL DEFAULT now(),
  started_at         timestamptz,
  finished_at        timestamptz,
  -- INV-RUN-002: terminal ⇔ finished_at; fora de queued exige started_at
  CONSTRAINT run_finished CHECK ((status IN ('done','failed','cancelled')) = (finished_at IS NOT NULL)),
  CONSTRAINT run_started  CHECK (status IN ('queued','cancelled','failed') OR started_at IS NOT NULL)
);
CREATE INDEX agent_run_conversation ON agent_run (conversation_id, queued_at DESC);
-- INV-RUN-005: no máximo uma execução ativa por conversa (grupo responde em sequência)
CREATE UNIQUE INDEX agent_run_one_active ON agent_run (conversation_id) WHERE status IN ('queued','running');

CREATE FUNCTION trg_run_transition() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  -- FK SET NULL do agente é a única mudança aceita em execução encerrada
  IF NEW.agent_id IS NULL AND OLD.agent_id IS NOT NULL
     AND (to_jsonb(NEW) - 'agent_id') = (to_jsonb(OLD) - 'agent_id') THEN
    RETURN NEW;
  END IF;
  -- INV-RUN-001: queued→running|failed|cancelled; running→done|failed|cancelled; terminal é final
  IF NOT ((OLD.status = 'queued'  AND NEW.status IN ('queued','running','failed','cancelled'))
       OR (OLD.status = 'running' AND NEW.status IN ('running','done','failed','cancelled'))) THEN
    RAISE EXCEPTION 'INV-RUN-001: transição % → % proibida', OLD.status, NEW.status USING ERRCODE = 'check_violation';
  END IF;
  IF (NEW.conversation_id, NEW.trigger_message_id, NEW.agent_name, NEW.queued_at)
     IS DISTINCT FROM (OLD.conversation_id, OLD.trigger_message_id, OLD.agent_name, OLD.queued_at) THEN
    RAISE EXCEPTION 'INV-RUN-001: identidade da execução é imutável' USING ERRCODE = 'check_violation';
  END IF;
  -- INV-RUN-004: contadores de consumo só crescem
  IF NEW.input_tokens < OLD.input_tokens OR NEW.output_tokens < OLD.output_tokens OR NEW.tool_calls < OLD.tool_calls THEN
    RAISE EXCEPTION 'INV-RUN-004: contadores não diminuem' USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER run_transition BEFORE UPDATE ON agent_run
  FOR EACH ROW EXECUTE FUNCTION trg_run_transition();

CREATE FUNCTION trg_run_member() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  -- INV-RUN-003: só responde quem faz parte da conversa
  IF NOT EXISTS (
       SELECT 1 FROM conversation c
        WHERE c.id = NEW.conversation_id
          AND ((c.kind = 'dm' AND c.agent_id = NEW.agent_id)
            OR (c.kind = 'group' AND EXISTS (SELECT 1 FROM conversation_member m
                                               WHERE m.conversation_id = c.id AND m.agent_id = NEW.agent_id)))) THEN
    RAISE EXCEPTION 'INV-RUN-003: agente não participa desta conversa' USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER run_member BEFORE INSERT ON agent_run
  FOR EACH ROW EXECUTE FUNCTION trg_run_member();

-- ---------------------------------------------------------------------
-- Mensagens: append-only
-- ---------------------------------------------------------------------
CREATE TABLE message (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  conversation_id uuid NOT NULL REFERENCES conversation (id) ON DELETE CASCADE,
  seq             bigint NOT NULL,
  author          text NOT NULL CHECK (author IN ('user','agent','system')),
  agent_id        uuid REFERENCES agent (id) ON DELETE SET NULL,
  agent_name      text CHECK (agent_name IS NULL OR length(agent_name) BETWEEN 1 AND 40),
  body            text NOT NULL DEFAULT '' CHECK (length(body) <= 20000),
  document_id     uuid REFERENCES document (id),
  image_key       text CHECK (image_key IS NULL OR length(image_key) <= 300),
  run_id          uuid REFERENCES agent_run (id),
  sources         jsonb NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(sources) = 'array'),
  steps           jsonb NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(steps) = 'array'),
  error           text CHECK (error IS NULL OR length(error) <= 500),
  created_at      timestamptz NOT NULL DEFAULT now(),
  UNIQUE (conversation_id, seq),
  -- INV-MSG-002: forma por autor
  CONSTRAINT message_author_shape CHECK (
       (author = 'user'   AND agent_id IS NULL AND agent_name IS NULL AND run_id IS NULL)
    OR (author = 'agent'  AND agent_name IS NOT NULL AND run_id IS NOT NULL AND document_id IS NULL AND image_key IS NULL)
    OR (author = 'system' AND agent_id IS NULL AND run_id IS NULL AND document_id IS NULL AND image_key IS NULL)),
  -- INV-MSG-003: mensagem do usuário nunca é vazia
  CONSTRAINT message_user_not_empty CHECK (
    author <> 'user' OR length(btrim(body)) > 0 OR document_id IS NOT NULL OR image_key IS NOT NULL),
  CONSTRAINT message_agent_has_text CHECK (author <> 'agent' OR length(btrim(body)) > 0 OR error IS NOT NULL)
);
CREATE INDEX message_conversation_seq ON message (conversation_id, seq DESC);

ALTER TABLE agent_run
  ADD CONSTRAINT agent_run_trigger_fk FOREIGN KEY (trigger_message_id) REFERENCES message (id) ON DELETE CASCADE;

-- INV-MSG-001: seq gapless e crescente por conversa; atualiza atividade
CREATE FUNCTION trg_message_seq() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
BEGIN
  UPDATE conversation
     SET next_seq = next_seq + 1, last_activity_at = now()
   WHERE id = NEW.conversation_id
  RETURNING next_seq - 1 INTO NEW.seq;
  IF NEW.seq IS NULL THEN
    RAISE EXCEPTION 'INV-MSG-001: conversa inexistente' USING ERRCODE = 'foreign_key_violation';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER message_seq BEFORE INSERT ON message
  FOR EACH ROW EXECUTE FUNCTION trg_message_seq();

CREATE FUNCTION trg_message_doc_scope() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  -- INV-MSG-004: anexo pertence à mesma conversa; imagem pertence ao dono
  IF NEW.document_id IS NOT NULL AND NOT EXISTS (
       SELECT 1 FROM document d WHERE d.id = NEW.document_id AND d.conversation_id = NEW.conversation_id) THEN
    RAISE EXCEPTION 'INV-MSG-004: anexo não pertence a esta conversa' USING ERRCODE = 'check_violation';
  END IF;
  IF NEW.image_key IS NOT NULL AND NOT EXISTS (
       SELECT 1 FROM conversation c WHERE c.id = NEW.conversation_id AND NEW.image_key LIKE c.owner_id::text || '/%') THEN
    RAISE EXCEPTION 'INV-MSG-004: imagem não pertence ao dono da conversa' USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER message_doc_scope BEFORE INSERT ON message
  FOR EACH ROW EXECUTE FUNCTION trg_message_doc_scope();

-- INV-MSG-005: mensagem é imutável (única exceção: FK SET NULL do agente)
CREATE FUNCTION trg_message_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.agent_id IS NULL AND OLD.agent_id IS NOT NULL
     AND (to_jsonb(NEW) - 'agent_id') = (to_jsonb(OLD) - 'agent_id') THEN
    RETURN NEW;
  END IF;
  RAISE EXCEPTION 'INV-MSG-005: mensagens são append-only' USING ERRCODE = 'insufficient_privilege';
END $$;
CREATE TRIGGER message_immutable BEFORE UPDATE ON message
  FOR EACH ROW EXECUTE FUNCTION trg_message_immutable();

-- confirmação de leitura: fato append-only
CREATE TABLE message_receipt (
  message_id uuid NOT NULL REFERENCES message (id) ON DELETE CASCADE,
  state      text NOT NULL CHECK (state IN ('sent','delivered','read')),
  at         timestamptz NOT NULL DEFAULT clock_timestamp(),
  PRIMARY KEY (message_id, state)
);

CREATE FUNCTION trg_receipt_order() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  -- INV-RCP-001: só para mensagem do usuário, em ordem sent → delivered → read
  IF NOT EXISTS (SELECT 1 FROM message WHERE id = NEW.message_id AND author = 'user') THEN
    RAISE EXCEPTION 'INV-RCP-001: recibo só para mensagem do usuário' USING ERRCODE = 'check_violation';
  END IF;
  IF NEW.state = 'delivered' AND NOT EXISTS (SELECT 1 FROM message_receipt WHERE message_id = NEW.message_id AND state = 'sent')
  OR NEW.state = 'read'      AND NOT EXISTS (SELECT 1 FROM message_receipt WHERE message_id = NEW.message_id AND state = 'delivered') THEN
    RAISE EXCEPTION 'INV-RCP-001: recibo fora de ordem' USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER receipt_order BEFORE INSERT ON message_receipt
  FOR EACH ROW EXECUTE FUNCTION trg_receipt_order();

CREATE FUNCTION trg_message_sent() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.author = 'user' THEN
    INSERT INTO message_receipt (message_id, state) VALUES (NEW.id, 'sent');
  END IF;
  RETURN NULL;
END $$;
CREATE TRIGGER message_sent AFTER INSERT ON message
  FOR EACH ROW EXECUTE FUNCTION trg_message_sent();

-- ---------------------------------------------------------------------
-- Trilha da execução: append-only com encadeamento SHA-256 por execução
-- ---------------------------------------------------------------------
CREATE TABLE agent_run_event (
  id        bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  run_id    uuid NOT NULL REFERENCES agent_run (id) ON DELETE CASCADE,
  at        timestamptz NOT NULL DEFAULT clock_timestamp(),
  kind      text NOT NULL CHECK (kind IN ('started','routed','context','tool_call','tool_result','answer','error','cancelled')),
  payload   jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(payload) = 'object'),
  prev_hash text CHECK (prev_hash IS NULL OR prev_hash ~ '^[0-9a-f]{64}$'),
  hash      text NOT NULL CHECK (hash ~ '^[0-9a-f]{64}$')
);
CREATE INDEX agent_run_event_run ON agent_run_event (run_id, id);

CREATE FUNCTION run_event_digest(p_prev text, p_run uuid, p_at timestamptz, p_kind text, p_payload jsonb) RETURNS text
LANGUAGE sql IMMUTABLE AS $$
  SELECT encode(digest(coalesce(p_prev, '') || '|' || p_run::text || '|' ||
                       to_char(p_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US') || '|' ||
                       p_kind || '|' || p_payload::text, 'sha256'), 'hex')
$$;

-- INV-AUD-001: hash calculado pelo banco; o valor enviado pela aplicação é descartado
CREATE FUNCTION trg_run_event_chain() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
BEGIN
  PERFORM 1 FROM agent_run WHERE id = NEW.run_id FOR UPDATE;   -- serializa a cadeia da execução
  SELECT hash INTO NEW.prev_hash FROM agent_run_event WHERE run_id = NEW.run_id ORDER BY id DESC LIMIT 1;
  NEW.at := clock_timestamp();
  NEW.hash := run_event_digest(NEW.prev_hash, NEW.run_id, NEW.at, NEW.kind, NEW.payload);
  RETURN NEW;
END $$;
CREATE TRIGGER run_event_chain BEFORE INSERT ON agent_run_event
  FOR EACH ROW EXECUTE FUNCTION trg_run_event_chain();

CREATE FUNCTION trg_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'tabela append-only: % não permitido em %', TG_OP, TG_TABLE_NAME USING ERRCODE = 'insufficient_privilege';
END $$;
CREATE TRIGGER run_event_no_update BEFORE UPDATE ON agent_run_event FOR EACH ROW EXECUTE FUNCTION trg_append_only();
CREATE TRIGGER receipt_no_update   BEFORE UPDATE ON message_receipt FOR EACH ROW EXECUTE FUNCTION trg_append_only();

-- verificação da cadeia: devolve o primeiro evento adulterado, ou nada
CREATE FUNCTION verify_run_chain(p_run uuid) RETURNS TABLE (event_id bigint, problem text)
LANGUAGE sql STABLE AS $$
  WITH e AS (
    SELECT id, prev_hash, hash, run_event_digest(prev_hash, run_id, at, kind, payload) AS calc,
           lag(hash) OVER (ORDER BY id) AS real_prev
      FROM agent_run_event WHERE run_id = p_run)
  SELECT id, CASE WHEN hash <> calc THEN 'hash não confere' ELSE 'elo quebrado' END
    FROM e WHERE hash <> calc OR prev_hash IS DISTINCT FROM real_prev
   ORDER BY id LIMIT 1
$$;

-- consumo: append-only, sobrevive à exclusão da conversa (sem FK para run)
CREATE TABLE usage_event (
  id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  user_id       uuid NOT NULL REFERENCES app_user (id) ON DELETE CASCADE,
  run_id        uuid,
  model         text NOT NULL,
  input_tokens  integer NOT NULL CHECK (input_tokens >= 0),
  output_tokens integer NOT NULL CHECK (output_tokens >= 0),
  at            timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX usage_event_user_at ON usage_event (user_id, at DESC);
CREATE TRIGGER usage_no_update BEFORE UPDATE ON usage_event FOR EACH ROW EXECUTE FUNCTION trg_append_only();

-- ---------------------------------------------------------------------
-- RLS: INV-SEC-001 — nenhum usuário enxerga dado de outro
-- ---------------------------------------------------------------------
ALTER TABLE app_user            ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_settings       ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent               ENABLE ROW LEVEL SECURITY;
ALTER TABLE conversation        ENABLE ROW LEVEL SECURITY;
ALTER TABLE conversation_member ENABLE ROW LEVEL SECURITY;
ALTER TABLE document            ENABLE ROW LEVEL SECURITY;
ALTER TABLE doc_chunk           ENABLE ROW LEVEL SECURITY;
ALTER TABLE doc_sheet           ENABLE ROW LEVEL SECURITY;
ALTER TABLE doc_row             ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent_run           ENABLE ROW LEVEL SECURITY;
ALTER TABLE message             ENABLE ROW LEVEL SECURITY;
ALTER TABLE message_receipt     ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent_run_event     ENABLE ROW LEVEL SECURITY;
ALTER TABLE usage_event         ENABLE ROW LEVEL SECURITY;

CREATE POLICY own ON app_user            USING (id = papo_uid()) WITH CHECK (id = papo_uid());
CREATE POLICY own ON user_settings       USING (user_id = papo_uid()) WITH CHECK (user_id = papo_uid());
CREATE POLICY own ON agent               USING (owner_id = papo_uid()) WITH CHECK (owner_id = papo_uid());
CREATE POLICY own ON conversation        USING (owner_id = papo_uid()) WITH CHECK (owner_id = papo_uid());
CREATE POLICY own ON conversation_member USING (owner_id = papo_uid()) WITH CHECK (owner_id = papo_uid());
CREATE POLICY own ON document            USING (owner_id = papo_uid()) WITH CHECK (owner_id = papo_uid());
CREATE POLICY own ON doc_chunk USING (EXISTS (SELECT 1 FROM document d WHERE d.id = document_id AND d.owner_id = papo_uid()))
                            WITH CHECK (EXISTS (SELECT 1 FROM document d WHERE d.id = document_id AND d.owner_id = papo_uid()));
CREATE POLICY own ON doc_sheet USING (EXISTS (SELECT 1 FROM document d WHERE d.id = document_id AND d.owner_id = papo_uid()))
                            WITH CHECK (EXISTS (SELECT 1 FROM document d WHERE d.id = document_id AND d.owner_id = papo_uid()));
CREATE POLICY own ON doc_row   USING (EXISTS (SELECT 1 FROM document d WHERE d.id = document_id AND d.owner_id = papo_uid()))
                            WITH CHECK (EXISTS (SELECT 1 FROM document d WHERE d.id = document_id AND d.owner_id = papo_uid()));
CREATE POLICY own ON agent_run USING (EXISTS (SELECT 1 FROM conversation c WHERE c.id = conversation_id AND c.owner_id = papo_uid()))
                            WITH CHECK (EXISTS (SELECT 1 FROM conversation c WHERE c.id = conversation_id AND c.owner_id = papo_uid()));
CREATE POLICY own ON message   USING (EXISTS (SELECT 1 FROM conversation c WHERE c.id = conversation_id AND c.owner_id = papo_uid()))
                            WITH CHECK (EXISTS (SELECT 1 FROM conversation c WHERE c.id = conversation_id AND c.owner_id = papo_uid()));
CREATE POLICY own ON message_receipt USING (EXISTS (SELECT 1 FROM message m JOIN conversation c ON c.id = m.conversation_id
                                                     WHERE m.id = message_id AND c.owner_id = papo_uid()))
                                  WITH CHECK (EXISTS (SELECT 1 FROM message m JOIN conversation c ON c.id = m.conversation_id
                                                     WHERE m.id = message_id AND c.owner_id = papo_uid()));
CREATE POLICY own ON agent_run_event USING (EXISTS (SELECT 1 FROM agent_run r JOIN conversation c ON c.id = r.conversation_id
                                                     WHERE r.id = run_id AND c.owner_id = papo_uid()))
                                  WITH CHECK (EXISTS (SELECT 1 FROM agent_run r JOIN conversation c ON c.id = r.conversation_id
                                                     WHERE r.id = run_id AND c.owner_id = papo_uid()));
CREATE POLICY own ON usage_event USING (user_id = papo_uid()) WITH CHECK (user_id = papo_uid());

-- ---------------------------------------------------------------------
-- Privilégios do papel da aplicação (P3: fatos sem UPDATE/DELETE)
-- ---------------------------------------------------------------------
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM papo_app;
GRANT USAGE ON SCHEMA public TO papo_app;
GRANT SELECT, UPDATE ON app_user TO papo_app;
GRANT DELETE ON app_user TO papo_app;                                  -- exclusão de conta (LGPD), em cascata
GRANT SELECT, INSERT, UPDATE ON user_settings TO papo_app;
GRANT SELECT, INSERT, DELETE ON agent TO papo_app;
GRANT UPDATE (name, emoji, color, persona, updated_at) ON agent TO papo_app;
GRANT SELECT, INSERT, DELETE ON conversation TO papo_app;
GRANT UPDATE (name, emoji, color) ON conversation TO papo_app;
GRANT SELECT, INSERT, DELETE ON conversation_member TO papo_app;
GRANT SELECT, INSERT, DELETE ON document TO papo_app;
GRANT UPDATE (status, pages, note, processed_at) ON document TO papo_app;
GRANT SELECT, INSERT ON doc_chunk, doc_sheet, doc_row TO papo_app;
GRANT SELECT, INSERT ON message, message_receipt, agent_run_event, usage_event TO papo_app;
GRANT SELECT, INSERT ON agent_run TO papo_app;
GRANT UPDATE (status, model, input_tokens, output_tokens, tool_calls, error, started_at, finished_at) ON agent_run TO papo_app;
GRANT EXECUTE ON FUNCTION papo_login(text, text, text), papo_uid(), f_unaccent(text), verify_run_chain(uuid) TO papo_app;
