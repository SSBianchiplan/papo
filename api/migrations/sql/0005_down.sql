ALTER TABLE app_config DROP COLUMN storage_quota_mb;
REVOKE DELETE ON doc_chunk, doc_sheet, doc_row FROM papo_app;
DROP TABLE document_purge;
CREATE OR REPLACE FUNCTION trg_message_doc_scope() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
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
-- NOT VALID: mensagens já existentes com arquivo gerado continuam (são append-only); só as novas voltam à regra antiga
ALTER TABLE message DROP CONSTRAINT message_agent_has_text;
ALTER TABLE message ADD CONSTRAINT message_agent_has_text CHECK (author <> 'agent' OR length(btrim(body)) > 0 OR error IS NOT NULL) NOT VALID;
ALTER TABLE message DROP CONSTRAINT message_author_shape;
ALTER TABLE message ADD CONSTRAINT message_author_shape CHECK (
     (author = 'user'   AND agent_id IS NULL AND agent_name IS NULL AND run_id IS NULL)
  OR (author = 'agent'  AND agent_name IS NOT NULL AND run_id IS NOT NULL AND document_id IS NULL AND image_key IS NULL)
  OR (author = 'system' AND agent_id IS NULL AND run_id IS NULL AND document_id IS NULL AND image_key IS NULL)) NOT VALID;
ALTER TABLE document DROP CONSTRAINT document_agent_origin, DROP COLUMN run_id, DROP COLUMN origin;
