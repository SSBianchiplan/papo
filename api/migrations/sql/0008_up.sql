-- Governança de IA (SPEC-GPS-CAMADAS-001) e Consultor de IA (SPEC-GPS-PAPO-CIA-001).
-- Regras que protegem autonomia e nota vivem aqui, em CHECK e trigger — não na aplicação nem no prompt.

-- ----------------------------------------------------------------- agente: tipo
ALTER TABLE agent ADD COLUMN kind text NOT NULL DEFAULT 'agente' CHECK (kind IN ('agente', 'consultor'));
CREATE UNIQUE INDEX agent_one_consultor_uq ON agent (owner_id) WHERE kind = 'consultor';

-- ----------------------------------------------------------------- ficha de governança (plano de controle)
CREATE TABLE agent_ficha (
  agent_id      uuid PRIMARY KEY,
  owner_id      uuid NOT NULL,
  dono          text NOT NULL DEFAULT '' CHECK (length(dono) <= 120),
  camada_real   smallint CHECK (camada_real BETWEEN 1 AND 6),
  nivel         text NOT NULL DEFAULT 'M0' CHECK (nivel IN ('M0', 'M1', 'M2', 'M3')),     -- ausente lê-se M0
  fontes        text[] NOT NULL DEFAULT '{}',
  ferramentas   jsonb NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(ferramentas) = 'array'),   -- [{nome, tipo}]
  raio_acao     text NOT NULL DEFAULT '' CHECK (length(raio_acao) <= 500),
  max_iteracoes smallint CHECK (max_iteracoes BETWEEN 1 AND 16),
  max_custo_conversa_usd numeric(10,4) CHECK (max_custo_conversa_usd > 0),
  max_segundos_turno smallint CHECK (max_segundos_turno BETWEEN 10 AND 600),
  aprovacao_humana text[] NOT NULL DEFAULT '{}',
  gatilhos      text[] NOT NULL DEFAULT '{T4,T6,T7,T8}' CHECK (gatilhos <@ '{T1,T2,T3,T4,T5,T6,T7,T8}'),
  canais        text[] NOT NULL DEFAULT '{direto}' CHECK (canais <@ '{direto,grupo,mencao}'),
  retencao_dias smallint NOT NULL DEFAULT 90 CHECK (retencao_dias BETWEEN 1 AND 3650),
  camadas_no_contexto boolean NOT NULL DEFAULT false,      -- o agente conhece o Modelo de Camadas
  uso_interno_evidencia boolean NOT NULL DEFAULT false,    -- libera M2 na camada 5 (matriz)
  excecao_m3    text CHECK (excecao_m3 IS NULL OR length(excecao_m3) BETWEEN 10 AND 1000),   -- exigida para M3 na camada 6
  ativo         boolean NOT NULL DEFAULT false,
  versao        integer NOT NULL DEFAULT 1,
  decidido_por  uuid,
  atualizado_em timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY (owner_id, agent_id) REFERENCES agent (owner_id, id) ON DELETE CASCADE,
  -- matriz camada × moderação (CAMADAS-001 §12): M3 só na camada 1, ou na 6 com exceção aprovada; M2 na 5 só para uso interno
  CONSTRAINT ficha_matriz CHECK (
        (nivel <> 'M3' OR camada_real = 1 OR (camada_real = 6 AND excecao_m3 IS NOT NULL))
    AND (nivel <> 'M2' OR camada_real IS DISTINCT FROM 5 OR uso_interno_evidencia)),
  -- I4: agente ativo só com ficha completa e dono
  CONSTRAINT ficha_i4_ativo CHECK (NOT ativo OR (
        length(btrim(dono)) > 0 AND camada_real IS NOT NULL AND jsonb_array_length(ferramentas) > 0
    AND cardinality(canais) > 0 AND max_iteracoes IS NOT NULL AND max_custo_conversa_usd IS NOT NULL
    AND max_segundos_turno IS NOT NULL AND length(btrim(raio_acao)) > 0))
);

-- histórico de versões da ficha (append-only): toda mudança fica registrada com quem decidiu
CREATE TABLE agent_ficha_historico (
  id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  agent_id   uuid NOT NULL,
  owner_id   uuid NOT NULL,
  versao     integer NOT NULL,
  ficha      jsonb NOT NULL,
  decidido_por uuid,
  em         timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY (owner_id, agent_id) REFERENCES agent (owner_id, id) ON DELETE CASCADE
);
CREATE FUNCTION trg_ficha_versao() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
BEGIN
  IF TG_OP = 'UPDATE' THEN
    NEW.versao := OLD.versao + 1;
    NEW.atualizado_em := now();
  END IF;
  INSERT INTO agent_ficha_historico (agent_id, owner_id, versao, ficha, decidido_por)
       VALUES (NEW.agent_id, NEW.owner_id, NEW.versao, to_jsonb(NEW) - 'owner_id', NEW.decidido_por);
  RETURN NEW;
END $$;
CREATE TRIGGER ficha_versao BEFORE INSERT OR UPDATE ON agent_ficha FOR EACH ROW EXECUTE FUNCTION trg_ficha_versao();
CREATE TRIGGER ficha_hist_no_update BEFORE UPDATE ON agent_ficha_historico FOR EACH ROW EXECUTE FUNCTION trg_append_only();

-- eventos de governança: gatilhos T1–T8 e paradas (append-only)
CREATE TABLE governanca_evento (
  id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  owner_id        uuid NOT NULL REFERENCES app_user (id) ON DELETE CASCADE,
  agent_id        uuid,
  conversation_id uuid,
  run_id          uuid,
  codigo          text NOT NULL CHECK (codigo IN ('T1','T2','T3','T4','T5','T6','T7','T8','PARADA','INATIVO','CANAL')),
  detalhe         text NOT NULL CHECK (length(detalhe) <= 500),
  nivel_antes     text,
  nivel_depois    text,
  em              timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX governanca_evento_owner ON governanca_evento (owner_id, em DESC);
CREATE TRIGGER governanca_no_update BEFORE UPDATE ON governanca_evento FOR EACH ROW EXECUTE FUNCTION trg_append_only();

-- opções por conversa
CREATE TABLE conversation_feature (
  conversation_id uuid PRIMARY KEY,
  owner_id        uuid NOT NULL,
  camadas         boolean NOT NULL DEFAULT false,     -- Modelo de Camadas no contexto dos agentes desta conversa
  consultor       boolean NOT NULL DEFAULT false,     -- Consultor de IA participa (grupo: só quando mencionado)
  FOREIGN KEY (owner_id, conversation_id) REFERENCES conversation (owner_id, id) ON DELETE CASCADE
);

-- cartões tipados nas mensagens (pergunta rápida, parecer): JSON renderizado pelo app, nunca HTML do agente
ALTER TABLE message ADD COLUMN card jsonb CHECK (card IS NULL OR (jsonb_typeof(card) = 'object' AND card ? 'tipo'));

-- ----------------------------------------------------------------- Consultor de IA
CREATE TABLE rubrica_versao (
  versao      text PRIMARY KEY CHECK (versao ~ '^\d+\.\d+\.\d+$'),
  definicao   jsonb NOT NULL CHECK (jsonb_typeof(definicao) = 'object'),
  ativa       boolean NOT NULL DEFAULT false,
  nota        text CHECK (nota IS NULL OR length(nota) <= 500),
  criada_por  uuid,
  criada_em   timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX rubrica_uma_ativa ON rubrica_versao (ativa) WHERE ativa;
CREATE FUNCTION trg_rubrica_imutavel() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.definicao IS DISTINCT FROM OLD.definicao OR NEW.versao IS DISTINCT FROM OLD.versao THEN
    RAISE EXCEPTION 'rubrica publicada é imutável: crie uma nova versão' USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER rubrica_imutavel BEFORE UPDATE ON rubrica_versao FOR EACH ROW EXECUTE FUNCTION trg_rubrica_imutavel();

CREATE TABLE consultor_avaliacao (
  id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  owner_id         uuid NOT NULL,
  conversation_id  uuid NOT NULL,
  rubrica_versao   text NOT NULL REFERENCES rubrica_versao (versao),
  estado           text NOT NULL DEFAULT 'aguardando_documento' CHECK (estado IN (
                     'aguardando_documento', 'lendo', 'triagem', 'avaliando', 'entrevista', 'confirmando',
                     'calculando', 'parecer', 'contestacao', 'rebaixado')),
  documento_id     uuid,
  titulo           text CHECK (titulo IS NULL OR length(titulo) <= 200),
  camada_declarada smallint CHECK (camada_declarada BETWEEN 1 AND 6),
  camada_real      smallint CHECK (camada_real BETWEEN 1 AND 6),
  camadas_usadas   smallint[] NOT NULL DEFAULT '{}',
  camada_minima    smallint CHECK (camada_minima BETWEEN 1 AND 6),
  desvio_justificativa text CHECK (desvio_justificativa IS NULL OR length(desvio_justificativa) <= 500),
  resumo           text CHECK (resumo IS NULL OR length(resumo) <= 2000),
  pergunta_atual   text,                      -- critério perguntado agora (entrevista) ou aguardando confirmação
  texto_pendente   text CHECK (texto_pendente IS NULL OR length(texto_pendente) <= 1000),
  ja_perguntados   text[] NOT NULL DEFAULT '{}',
  dado_sensivel    boolean NOT NULL DEFAULT false,
  criado_em        timestamptz NOT NULL DEFAULT now(),
  atualizado_em    timestamptz NOT NULL DEFAULT now(),
  UNIQUE (owner_id, id),
  FOREIGN KEY (owner_id, conversation_id) REFERENCES conversation (owner_id, id) ON DELETE CASCADE
);
CREATE INDEX consultor_avaliacao_conv ON consultor_avaliacao (conversation_id, criado_em DESC);

CREATE TABLE consultor_evidencia (
  id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  avaliacao_id  uuid NOT NULL,
  owner_id      uuid NOT NULL,
  criterio_id   text NOT NULL,
  pagina        integer CHECK (pagina >= 1),
  trecho        text NOT NULL CHECK (length(trecho) BETWEEN 1 AND 400),
  validada      boolean NOT NULL,
  motivo        text,
  em            timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY (owner_id, avaliacao_id) REFERENCES consultor_avaliacao (owner_id, id) ON DELETE CASCADE
);

CREATE TABLE consultor_criterio_estado (
  id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  avaliacao_id  uuid NOT NULL,
  owner_id      uuid NOT NULL,
  criterio_id   text NOT NULL CHECK (criterio_id ~ '^(N0[1-5]|C[1-6]\.[1-5])$'),
  estado        text NOT NULL CHECK (estado IN ('ATENDE','DECLARADO','NAO_ATENDE','LACUNA','NAO_SE_APLICA')),
  origem        text NOT NULL CHECK (origem IN ('documento','resposta','contestacao','sistema')),
  evidencia_id  bigint REFERENCES consultor_evidencia (id),
  justificativa text CHECK (justificativa IS NULL OR length(justificativa) <= 500),
  trace_id      uuid NOT NULL,
  em            timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY (owner_id, avaliacao_id) REFERENCES consultor_avaliacao (owner_id, id) ON DELETE CASCADE
);
CREATE INDEX consultor_estado_atual ON consultor_criterio_estado (avaliacao_id, criterio_id, id DESC);

-- I1: ATENDE exige evidência validada do mesmo critério e avaliação
CREATE FUNCTION trg_consultor_i1() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.estado = 'ATENDE' AND NOT EXISTS (
       SELECT 1 FROM consultor_evidencia e
        WHERE e.id = NEW.evidencia_id AND e.avaliacao_id = NEW.avaliacao_id AND e.criterio_id = NEW.criterio_id AND e.validada) THEN
    RAISE EXCEPTION 'I1: ATENDE sem evidencia validada (%/%)', NEW.avaliacao_id, NEW.criterio_id USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER consultor_i1 BEFORE INSERT ON consultor_criterio_estado FOR EACH ROW EXECUTE FUNCTION trg_consultor_i1();

CREATE VIEW consultor_estado_vigente WITH (security_invoker = true) AS
  SELECT DISTINCT ON (avaliacao_id, criterio_id) * FROM consultor_criterio_estado ORDER BY avaliacao_id, criterio_id, id DESC;

CREATE TABLE consultor_resposta (
  id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  avaliacao_id  uuid NOT NULL,
  owner_id      uuid NOT NULL,
  criterio_id   text NOT NULL,
  pergunta      text NOT NULL,
  resposta      text NOT NULL CHECK (length(resposta) <= 1000),
  indice        smallint,
  message_id    uuid,
  em            timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY (owner_id, avaliacao_id) REFERENCES consultor_avaliacao (owner_id, id) ON DELETE CASCADE
);

CREATE TABLE consultor_parecer (
  id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  avaliacao_id   uuid NOT NULL,
  owner_id       uuid NOT NULL,
  versao         integer NOT NULL CHECK (versao >= 1),
  rubrica_versao text NOT NULL,
  resultado      jsonb NOT NULL,          -- notas por bloco, nota geral, veredito, risco, condições, perguntas
  nota_geral     integer NOT NULL CHECK (nota_geral BETWEEN 0 AND 100),
  veredito       text NOT NULL CHECK (veredito IN ('PRONTA_PARA_AVANCAR','AVANCAR_COM_CONDICOES','NAO_AVANCAR_AINDA')),
  risco          text NOT NULL CHECK (risco IN ('BAIXO','MEDIO','ALTO')),
  hash_entrada   text NOT NULL CHECK (hash_entrada ~ '^[0-9a-f]{64}$'),
  hash_anterior  text,
  hash           text NOT NULL DEFAULT '',
  pdf_document_id uuid,
  pdf_sha256     text,
  em             timestamptz NOT NULL DEFAULT now(),
  UNIQUE (avaliacao_id, versao),
  FOREIGN KEY (owner_id, avaliacao_id) REFERENCES consultor_avaliacao (owner_id, id) ON DELETE CASCADE
);

-- I3: cada parecer aponta para o hash do anterior; o banco calcula o próprio hash
CREATE FUNCTION trg_consultor_i3() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE prev consultor_parecer%ROWTYPE;
BEGIN
  SELECT * INTO prev FROM consultor_parecer WHERE avaliacao_id = NEW.avaliacao_id ORDER BY versao DESC LIMIT 1;
  IF prev.id IS NULL THEN
    IF NEW.versao <> 1 OR NEW.hash_anterior IS NOT NULL THEN
      RAISE EXCEPTION 'I3: primeiro parecer deve ter versão 1 e sem anterior' USING ERRCODE = 'check_violation';
    END IF;
  ELSIF NEW.versao <> prev.versao + 1 OR NEW.hash_anterior IS DISTINCT FROM prev.hash THEN
    RAISE EXCEPTION 'I3: cadeia de pareceres quebrada' USING ERRCODE = 'check_violation';
  END IF;
  NEW.hash := encode(digest(coalesce(NEW.hash_anterior, '') || '|' || NEW.hash_entrada || '|' || NEW.versao || '|' || NEW.resultado::text, 'sha256'), 'hex');
  RETURN NEW;
END $$;
CREATE TRIGGER consultor_i3 BEFORE INSERT ON consultor_parecer FOR EACH ROW EXECUTE FUNCTION trg_consultor_i3();

-- o PDF selado é ligado depois (uma única vez); nada mais muda no parecer
CREATE FUNCTION trg_consultor_parecer_imutavel() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF OLD.pdf_document_id IS NULL AND NEW.pdf_document_id IS NOT NULL
     AND (to_jsonb(NEW) - 'pdf_document_id' - 'pdf_sha256') = (to_jsonb(OLD) - 'pdf_document_id' - 'pdf_sha256') THEN
    RETURN NEW;
  END IF;
  RAISE EXCEPTION 'I2: parecer selado é imutável' USING ERRCODE = 'insufficient_privilege';
END $$;
CREATE TRIGGER consultor_parecer_imutavel BEFORE UPDATE ON consultor_parecer FOR EACH ROW EXECUTE FUNCTION trg_consultor_parecer_imutavel();
CREATE TRIGGER consultor_estado_no_update BEFORE UPDATE ON consultor_criterio_estado FOR EACH ROW EXECUTE FUNCTION trg_append_only();
CREATE TRIGGER consultor_resposta_no_update BEFORE UPDATE ON consultor_resposta FOR EACH ROW EXECUTE FUNCTION trg_append_only();
CREATE TRIGGER consultor_evidencia_no_update BEFORE UPDATE ON consultor_evidencia FOR EACH ROW EXECUTE FUNCTION trg_append_only();

-- verificação da cadeia: devolve o primeiro parecer com problema, ou nada
CREATE FUNCTION verify_parecer_chain(p_avaliacao uuid) RETURNS TABLE (parecer_id uuid, problema text)
LANGUAGE sql STABLE AS $$
  WITH p AS (
    SELECT id, versao, hash, hash_anterior,
           encode(digest(coalesce(hash_anterior, '') || '|' || hash_entrada || '|' || versao || '|' || resultado::text, 'sha256'), 'hex') AS calc,
           lag(hash) OVER (ORDER BY versao) AS real_prev
      FROM consultor_parecer WHERE avaliacao_id = p_avaliacao)
  SELECT id, CASE WHEN hash <> calc THEN 'hash não confere' ELSE 'elo quebrado' END
    FROM p WHERE hash <> calc OR hash_anterior IS DISTINCT FROM real_prev ORDER BY versao LIMIT 1
$$;

-- ----------------------------------------------------------------- RLS e privilégios
ALTER TABLE agent_ficha               ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent_ficha_historico     ENABLE ROW LEVEL SECURITY;
ALTER TABLE governanca_evento         ENABLE ROW LEVEL SECURITY;
ALTER TABLE conversation_feature      ENABLE ROW LEVEL SECURITY;
ALTER TABLE consultor_avaliacao       ENABLE ROW LEVEL SECURITY;
ALTER TABLE consultor_evidencia       ENABLE ROW LEVEL SECURITY;
ALTER TABLE consultor_criterio_estado ENABLE ROW LEVEL SECURITY;
ALTER TABLE consultor_resposta        ENABLE ROW LEVEL SECURITY;
ALTER TABLE consultor_parecer         ENABLE ROW LEVEL SECURITY;
CREATE POLICY own ON agent_ficha               USING (owner_id = papo_uid()) WITH CHECK (owner_id = papo_uid());
CREATE POLICY own ON agent_ficha_historico     USING (owner_id = papo_uid()) WITH CHECK (owner_id = papo_uid());
CREATE POLICY own ON governanca_evento         USING (owner_id = papo_uid()) WITH CHECK (owner_id = papo_uid());
CREATE POLICY own ON conversation_feature      USING (owner_id = papo_uid()) WITH CHECK (owner_id = papo_uid());
CREATE POLICY own ON consultor_avaliacao       USING (owner_id = papo_uid()) WITH CHECK (owner_id = papo_uid());
CREATE POLICY own ON consultor_evidencia       USING (owner_id = papo_uid()) WITH CHECK (owner_id = papo_uid());
CREATE POLICY own ON consultor_criterio_estado USING (owner_id = papo_uid()) WITH CHECK (owner_id = papo_uid());
CREATE POLICY own ON consultor_resposta        USING (owner_id = papo_uid()) WITH CHECK (owner_id = papo_uid());
CREATE POLICY own ON consultor_parecer         USING (owner_id = papo_uid()) WITH CHECK (owner_id = papo_uid());

GRANT SELECT, INSERT, UPDATE ON agent_ficha TO papo_app;
GRANT SELECT, INSERT ON agent_ficha_historico, governanca_evento TO papo_app;
GRANT SELECT, INSERT, UPDATE ON conversation_feature TO papo_app;
GRANT SELECT, INSERT ON rubrica_versao TO papo_app;
GRANT UPDATE (ativa, nota) ON rubrica_versao TO papo_app;
GRANT SELECT, INSERT, UPDATE ON consultor_avaliacao TO papo_app;
-- I2: estados, respostas, evidências e pareceres só recebem INSERT (o PDF selado entra uma vez, pela coluna própria)
GRANT SELECT, INSERT ON consultor_evidencia, consultor_criterio_estado, consultor_resposta, consultor_parecer TO papo_app;
GRANT UPDATE (pdf_document_id, pdf_sha256) ON consultor_parecer TO papo_app;
GRANT SELECT ON consultor_estado_vigente TO papo_app;
GRANT EXECUTE ON FUNCTION verify_parecer_chain(uuid) TO papo_app;

-- fichas dos agentes que já existem: camada 6 (usam ferramentas em vários passos), M1, só leitura + escrita na própria conversa
INSERT INTO agent_ficha (agent_id, owner_id, dono, camada_real, nivel, fontes, ferramentas, raio_acao, max_iteracoes,
                         max_custo_conversa_usd, max_segundos_turno, canais, ativo)
SELECT a.id, a.owner_id, coalesce(nullif(u.display_name, ''), u.email, 'dono da conta'), 6, 'M1',
       '{base do agente,arquivos da conversa,docs do hub ligados}',
       '[{"nome":"listar_documentos","tipo":"leitura"},{"nome":"buscar_nos_documentos","tipo":"leitura"},
         {"nome":"ler_documento","tipo":"leitura"},{"nome":"analisar_planilha","tipo":"leitura"},
         {"nome":"buscar_na_conversa","tipo":"leitura"},{"nome":"usar_skill","tipo":"leitura"},
         {"nome":"hub_buscar","tipo":"leitura"},{"nome":"hub_ler","tipo":"leitura"},
         {"nome":"gerar_arquivo","tipo":"escrita_propria"}]'::jsonb,
       'anexos novos na própria conversa', 8, 2.00, 180, '{direto,grupo}', true
  FROM agent a JOIN app_user u ON u.id = a.owner_id;

-- todo agente nasce com ficha: o padrão do grupo (M1) para agentes comuns, a ficha da spec para o Consultor de IA
CREATE FUNCTION trg_agent_ficha_padrao() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE dono text;
BEGIN
  SELECT coalesce(nullif(display_name, ''), email, 'dono da conta') INTO dono FROM app_user WHERE id = NEW.owner_id;
  IF NEW.kind = 'consultor' THEN
    INSERT INTO agent_ficha (agent_id, owner_id, dono, camada_real, nivel, fontes, ferramentas, raio_acao, max_iteracoes,
                             max_custo_conversa_usd, max_segundos_turno, aprovacao_humana, gatilhos, canais, camadas_no_contexto, ativo)
    VALUES (NEW.id, NEW.owner_id, dono, 5, 'M1', '{avaliacao.documentos,rubrica.versao_ativa}',
            '[{"nome":"extrair_documento","tipo":"leitura"},{"nome":"buscar_trecho","tipo":"leitura"},
              {"nome":"classificar_camada","tipo":"escrita_propria"},{"nome":"propor_estado_criterio","tipo":"escrita_propria"},
              {"nome":"registrar_resposta","tipo":"escrita_propria"},{"nome":"calcular_parecer","tipo":"leitura"},
              {"nome":"gerar_pdf_parecer","tipo":"escrita_propria"}]'::jsonb,
            'registros da própria avaliação', 6, 1.50, 90, '{compartilhar_parecer_fora_do_papo}', '{T4,T6,T7,T8}', '{direto}', true, true);
  ELSE
    INSERT INTO agent_ficha (agent_id, owner_id, dono, camada_real, nivel, fontes, ferramentas, raio_acao, max_iteracoes,
                             max_custo_conversa_usd, max_segundos_turno, canais, ativo)
    VALUES (NEW.id, NEW.owner_id, dono, 6, 'M1', '{base do agente,arquivos da conversa,docs do hub ligados}',
            '[{"nome":"listar_documentos","tipo":"leitura"},{"nome":"buscar_nos_documentos","tipo":"leitura"},
              {"nome":"ler_documento","tipo":"leitura"},{"nome":"analisar_planilha","tipo":"leitura"},
              {"nome":"buscar_na_conversa","tipo":"leitura"},{"nome":"usar_skill","tipo":"leitura"},
              {"nome":"hub_buscar","tipo":"leitura"},{"nome":"hub_ler","tipo":"leitura"},
              {"nome":"gerar_arquivo","tipo":"escrita_propria"}]'::jsonb,
            'anexos novos na própria conversa', 8, 2.00, 180, '{direto,grupo}', true);
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER agent_ficha_padrao AFTER INSERT ON agent FOR EACH ROW EXECUTE FUNCTION trg_agent_ficha_padrao();

-- trilha da execução passa a registrar a governança (gatilho/parada) junto dos demais eventos
ALTER TABLE agent_run_event DROP CONSTRAINT agent_run_event_kind_check;
ALTER TABLE agent_run_event ADD CONSTRAINT agent_run_event_kind_check
  CHECK (kind IN ('started','routed','context','tool_call','tool_result','answer','error','cancelled','governanca'));
