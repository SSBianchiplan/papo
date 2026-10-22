ALTER TABLE agent_run_event DROP CONSTRAINT agent_run_event_kind_check;
ALTER TABLE agent_run_event ADD CONSTRAINT agent_run_event_kind_check
  CHECK (kind IN ('started','routed','context','tool_call','tool_result','answer','error','cancelled')) NOT VALID;
DROP TRIGGER IF EXISTS agent_ficha_padrao ON agent;
DROP FUNCTION IF EXISTS trg_agent_ficha_padrao();
DROP FUNCTION IF EXISTS verify_parecer_chain(uuid);
DROP VIEW IF EXISTS consultor_estado_vigente;
DROP TABLE IF EXISTS consultor_parecer, consultor_resposta, consultor_criterio_estado, consultor_evidencia, consultor_avaliacao, rubrica_versao;
DROP FUNCTION IF EXISTS trg_consultor_i1(), trg_consultor_i3(), trg_consultor_parecer_imutavel(), trg_rubrica_imutavel();
ALTER TABLE message DROP COLUMN IF EXISTS card;
DROP TABLE IF EXISTS conversation_feature, governanca_evento, agent_ficha_historico, agent_ficha;
DROP FUNCTION IF EXISTS trg_ficha_versao();
DROP INDEX IF EXISTS agent_one_consultor_uq;
ALTER TABLE agent DROP COLUMN IF EXISTS kind;
