-- Arquivos gerados pelo agente (HTML/Markdown) entram na conversa como anexo da resposta e viram contexto pesquisável.
ALTER TABLE document
  ADD COLUMN origin text NOT NULL DEFAULT 'upload' CHECK (origin IN ('upload', 'agent')),
  ADD COLUMN run_id uuid,                     -- execução que gerou (sem FK: a cascada de exclusão não pode tocar documento processado)
  ADD CONSTRAINT document_agent_origin CHECK (origin = 'upload' OR conversation_id IS NOT NULL);

-- INV-MSG-002 (revisada): mensagem de agente pode levar documento — só um gerado por agente (verificado no trigger abaixo)
ALTER TABLE message DROP CONSTRAINT message_author_shape;
ALTER TABLE message ADD CONSTRAINT message_author_shape CHECK (
     (author = 'user'   AND agent_id IS NULL AND agent_name IS NULL AND run_id IS NULL)
  OR (author = 'agent'  AND agent_name IS NOT NULL AND run_id IS NOT NULL AND image_key IS NULL)
  OR (author = 'system' AND agent_id IS NULL AND run_id IS NULL AND document_id IS NULL AND image_key IS NULL));
ALTER TABLE message DROP CONSTRAINT message_agent_has_text;
ALTER TABLE message ADD CONSTRAINT message_agent_has_text
  CHECK (author <> 'agent' OR length(btrim(body)) > 0 OR error IS NOT NULL OR document_id IS NOT NULL);

CREATE OR REPLACE FUNCTION trg_message_doc_scope() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  -- INV-MSG-004: anexo pertence à mesma conversa; imagem pertence ao dono
  IF NEW.document_id IS NOT NULL AND NOT EXISTS (
       SELECT 1 FROM document d WHERE d.id = NEW.document_id AND d.conversation_id = NEW.conversation_id) THEN
    RAISE EXCEPTION 'INV-MSG-004: anexo não pertence a esta conversa' USING ERRCODE = 'check_violation';
  END IF;
  -- INV-MSG-006: agente só anexa arquivo que ele mesmo gerou; usuário só anexa arquivo enviado
  IF NEW.document_id IS NOT NULL AND NOT EXISTS (
       SELECT 1 FROM document d WHERE d.id = NEW.document_id
          AND d.origin = CASE WHEN NEW.author = 'agent' THEN 'agent' ELSE 'upload' END) THEN
    RAISE EXCEPTION 'INV-MSG-006: origem do anexo não confere com o autor' USING ERRCODE = 'check_violation';
  END IF;
  IF NEW.image_key IS NOT NULL AND NOT EXISTS (
       SELECT 1 FROM conversation c WHERE c.id = NEW.conversation_id AND NEW.image_key LIKE c.owner_id::text || '/%') THEN
    RAISE EXCEPTION 'INV-MSG-004: imagem não pertence ao dono da conversa' USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END $$;

-- Gerenciador de arquivos: liberar espaço de anexo de conversa sem apagar a mensagem (append-only).
-- O documento continua existindo (a mensagem aponta para ele); o arquivo e o índice saem, e o fato fica registrado.
CREATE TABLE document_purge (
  document_id uuid PRIMARY KEY REFERENCES document (id) ON DELETE CASCADE,
  owner_id    uuid NOT NULL REFERENCES app_user (id) ON DELETE CASCADE,
  bytes_freed bigint NOT NULL CHECK (bytes_freed >= 0),
  purged_at   timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE document_purge ENABLE ROW LEVEL SECURITY;
CREATE POLICY own ON document_purge USING (owner_id = papo_uid()) WITH CHECK (owner_id = papo_uid());
CREATE TRIGGER document_purge_no_update BEFORE UPDATE ON document_purge FOR EACH ROW EXECUTE FUNCTION trg_append_only();
GRANT SELECT, INSERT ON document_purge TO papo_app;
GRANT DELETE ON doc_chunk, doc_sheet, doc_row TO papo_app;     -- só pelo gerenciador, sob o RLS do dono

-- Cota de armazenamento por usuário (MB). NULL = sem cota.
ALTER TABLE app_config ADD COLUMN storage_quota_mb integer CHECK (storage_quota_mb IS NULL OR storage_quota_mb > 0);
