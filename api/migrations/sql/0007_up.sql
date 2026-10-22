-- Docs do hub: fontes de leitura (VPS e site) e o catálogo de metadados. Nenhum conteúdo de arquivo é guardado aqui:
-- o arquivo é lido na origem, sob demanda, e interpretado em memória.
CREATE TABLE hub_source (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name         text NOT NULL UNIQUE CHECK (name ~ '^[a-z0-9][a-z0-9-]{1,39}$'),
  label        text NOT NULL CHECK (length(label) BETWEEN 1 AND 80),
  kind         text NOT NULL CHECK (kind IN ('local', 'remote', 'sftp')),
  config       jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(config) = 'object'),   -- nada secreto aqui
  secret_enc   bytea,                                                                        -- token/senha cifrados (SECRETS_KEY)
  extensions   text[] NOT NULL,
  enabled      boolean NOT NULL DEFAULT true,
  visible_all  boolean NOT NULL DEFAULT false,            -- além dos administradores, todos os usuários enxergam
  status       text NOT NULL DEFAULT 'nova' CHECK (status IN ('nova', 'ok', 'erro')),
  last_error   text CHECK (last_error IS NULL OR length(last_error) <= 500),
  last_scan_at timestamptz,
  file_count   integer NOT NULL DEFAULT 0,
  total_bytes  bigint NOT NULL DEFAULT 0,
  created_at   timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE hub_file (
  source_id  uuid NOT NULL REFERENCES hub_source (id) ON DELETE CASCADE,
  path       text NOT NULL CHECK (length(path) BETWEEN 3 AND 1024),
  ext        text NOT NULL,
  size_bytes bigint NOT NULL CHECK (size_bytes >= 0),
  mtime      timestamptz NOT NULL,
  seen_at    timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (source_id, path)
);
CREATE INDEX hub_file_ext ON hub_file (ext);
CREATE INDEX hub_file_mtime ON hub_file (mtime DESC);

-- quais fontes (e pastas) cada agente lê
CREATE TABLE agent_hub (
  owner_id  uuid NOT NULL,
  agent_id  uuid NOT NULL,
  source_id uuid NOT NULL REFERENCES hub_source (id) ON DELETE CASCADE,
  prefix    text NOT NULL DEFAULT '' CHECK (length(prefix) <= 512 AND prefix NOT LIKE '%..%'),
  PRIMARY KEY (agent_id, source_id, prefix),
  FOREIGN KEY (owner_id, agent_id) REFERENCES agent (owner_id, id) ON DELETE CASCADE
);
ALTER TABLE agent_hub ENABLE ROW LEVEL SECURITY;
CREATE POLICY own ON agent_hub USING (owner_id = papo_uid()) WITH CHECK (owner_id = papo_uid());

-- configuração global (como app_config): sem RLS; a API só deixa administrador alterar
GRANT SELECT, INSERT, UPDATE, DELETE ON hub_source, hub_file TO papo_app;
GRANT SELECT, INSERT, DELETE ON agent_hub TO papo_app;

-- papel de administrador visto no último login (o worker precisa dele para saber o que o dono do agente pode ler)
ALTER TABLE app_user ADD COLUMN is_admin boolean NOT NULL DEFAULT false;
