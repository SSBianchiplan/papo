-- Administração do serviço de IA: chave (cifrada fora do banco), orçamento e preços por modelo.
-- Configuração global, não é dado de usuário: sem RLS. Só a API, com o papel papo-admin do Keycloak, altera.

CREATE TABLE app_config (
  id                     boolean PRIMARY KEY DEFAULT true CHECK (id),        -- linha única
  anthropic_key_enc      bytea,                                              -- AES-GCM com SECRETS_KEY (que não fica no banco)
  anthropic_key_hint     text CHECK (anthropic_key_hint IS NULL OR length(anthropic_key_hint) <= 32),
  anthropic_workspace_id text CHECK (anthropic_workspace_id IS NULL OR anthropic_workspace_id ~ '^[A-Za-z0-9_-]{1,80}$'),
  monthly_budget_usd     numeric(12,2) CHECK (monthly_budget_usd IS NULL OR monthly_budget_usd >= 0),   -- NULL = sem teto
  alert_pct              integer NOT NULL DEFAULT 80 CHECK (alert_pct BETWEEN 1 AND 100),
  daily_token_limit      integer CHECK (daily_token_limit IS NULL OR daily_token_limit >= 0),         -- NULL = usa o .env
  updated_by             uuid REFERENCES app_user (id) ON DELETE SET NULL,
  updated_at             timestamptz NOT NULL DEFAULT now(),
  CHECK ((anthropic_key_enc IS NULL) = (anthropic_key_hint IS NULL))
);
INSERT INTO app_config DEFAULT VALUES;
CREATE TRIGGER app_config_no_delete BEFORE DELETE ON app_config FOR EACH ROW EXECUTE FUNCTION trg_append_only();

-- Preço por milhão de tokens. "model" casa por prefixo: claude-haiku-4-5 vale para claude-haiku-4-5-20251001.
CREATE TABLE model_price (
  model           text PRIMARY KEY CHECK (model ~ '^[a-z0-9.-]{3,80}$'),
  label           text NOT NULL CHECK (length(label) BETWEEN 1 AND 60),
  input_usd_mtok  numeric(10,4) NOT NULL CHECK (input_usd_mtok >= 0),
  output_usd_mtok numeric(10,4) NOT NULL CHECK (output_usd_mtok >= 0),
  updated_at      timestamptz NOT NULL DEFAULT now()
);
-- tabela oficial da Anthropic (API direta), set/2026
INSERT INTO model_price (model, label, input_usd_mtok, output_usd_mtok) VALUES
  ('claude-opus-5-5',   'Claude Opus 5.5',   4, 20),
  ('claude-sonnet-5-5', 'Claude Sonnet 5.5', 2, 10),
  ('claude-haiku-4-5',  'Claude Haiku 4.5',  1, 5);

GRANT SELECT, UPDATE ON app_config TO papo_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON model_price TO papo_app;

-- Consumo agregado de todos os usuários (painel do administrador e teto mensal).
-- SECURITY DEFINER para atravessar o RLS; devolve só contagens, nunca conteúdo de conversa.
CREATE FUNCTION papo_usage_rollup(p_since timestamptz)
RETURNS TABLE (user_id uuid, user_name text, email text, day date, model text, input_tokens bigint, output_tokens bigint, events bigint)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
  SELECT u.user_id, a.display_name, a.email, (u.at AT TIME ZONE 'America/Sao_Paulo')::date, u.model,
         sum(u.input_tokens)::bigint, sum(u.output_tokens)::bigint, count(*)::bigint
    FROM usage_event u JOIN app_user a ON a.id = u.user_id
   WHERE u.at >= p_since
   GROUP BY 1, 2, 3, 4, 5
$$;
REVOKE ALL ON FUNCTION papo_usage_rollup(timestamptz) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION papo_usage_rollup(timestamptz) TO papo_app;
