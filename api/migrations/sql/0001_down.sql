DROP TABLE IF EXISTS usage_event, agent_run_event, message_receipt CASCADE;
ALTER TABLE IF EXISTS agent_run DROP CONSTRAINT IF EXISTS agent_run_trigger_fk;
DROP TABLE IF EXISTS message, agent_run, doc_row, doc_sheet, doc_chunk, document,
  conversation_member, conversation, agent, user_settings, app_user CASCADE;
DROP FUNCTION IF EXISTS verify_run_chain(uuid), trg_append_only(), trg_run_event_chain(),
  run_event_digest(text, uuid, timestamptz, text, jsonb), trg_message_sent(), trg_receipt_order(),
  trg_message_immutable(), trg_message_doc_scope(), trg_message_seq(), trg_run_member(), trg_run_transition(),
  trg_document_transition(), trg_member_group_only(), papo_login(text, text, text), papo_uid(), f_unaccent(text);
