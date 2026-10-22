-- Skills: pacotes de instruções (SKILL.md + referências) que os agentes carregam sob demanda.
CREATE TABLE skill (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  owner_id    uuid NOT NULL REFERENCES app_user (id) ON DELETE CASCADE,
  name        text NOT NULL CHECK (name ~ '^[a-z0-9][a-z0-9:_.-]{0,79}$'),
  description text NOT NULL CHECK (length(description) BETWEEN 1 AND 2000),
  body        text NOT NULL CHECK (length(body) BETWEEN 1 AND 300000),
  version     integer NOT NULL DEFAULT 1 CHECK (version >= 1),
  enabled     boolean NOT NULL DEFAULT true,
  shared      boolean NOT NULL DEFAULT false,              -- só administrador liga: vale para todos os usuários
  size_bytes  integer NOT NULL CHECK (size_bytes >= 0),
  created_at  timestamptz NOT NULL DEFAULT now(),
  updated_at  timestamptz NOT NULL DEFAULT now(),
  UNIQUE (owner_id, id)
);
CREATE UNIQUE INDEX skill_owner_name_uq ON skill (owner_id, lower(name));

CREATE TABLE skill_file (
  skill_id uuid NOT NULL REFERENCES skill (id) ON DELETE CASCADE,
  path     text NOT NULL CHECK (path ~ '^[A-Za-z0-9][A-Za-z0-9 _./-]{0,199}$' AND path NOT LIKE '%..%'),
  body     text NOT NULL CHECK (length(body) <= 1000000),
  PRIMARY KEY (skill_id, path)
);

-- ativação: por agente e por conversa (mesmo dono; skill compartilhada de outro dono também vale)
CREATE TABLE agent_skill (
  owner_id uuid NOT NULL,
  agent_id uuid NOT NULL,
  skill_id uuid NOT NULL REFERENCES skill (id) ON DELETE CASCADE,
  PRIMARY KEY (agent_id, skill_id),
  FOREIGN KEY (owner_id, agent_id) REFERENCES agent (owner_id, id) ON DELETE CASCADE
);
CREATE TABLE conversation_skill (
  owner_id        uuid NOT NULL,
  conversation_id uuid NOT NULL,
  skill_id        uuid NOT NULL REFERENCES skill (id) ON DELETE CASCADE,
  PRIMARY KEY (conversation_id, skill_id),
  FOREIGN KEY (owner_id, conversation_id) REFERENCES conversation (owner_id, id) ON DELETE CASCADE
);

ALTER TABLE skill              ENABLE ROW LEVEL SECURITY;
ALTER TABLE skill_file         ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent_skill        ENABLE ROW LEVEL SECURITY;
ALTER TABLE conversation_skill ENABLE ROW LEVEL SECURITY;
-- ler: as suas e as compartilhadas; escrever: só as suas
CREATE POLICY ver   ON skill FOR SELECT USING (owner_id = papo_uid() OR shared);
CREATE POLICY criar ON skill FOR INSERT WITH CHECK (owner_id = papo_uid());
CREATE POLICY mudar ON skill FOR UPDATE USING (owner_id = papo_uid()) WITH CHECK (owner_id = papo_uid());
CREATE POLICY tirar ON skill FOR DELETE USING (owner_id = papo_uid());
CREATE POLICY ver   ON skill_file FOR SELECT USING (EXISTS (SELECT 1 FROM skill s WHERE s.id = skill_id AND (s.owner_id = papo_uid() OR s.shared)));
CREATE POLICY gravar ON skill_file FOR ALL USING (EXISTS (SELECT 1 FROM skill s WHERE s.id = skill_id AND s.owner_id = papo_uid()))
  WITH CHECK (EXISTS (SELECT 1 FROM skill s WHERE s.id = skill_id AND s.owner_id = papo_uid()));
CREATE POLICY own ON agent_skill        USING (owner_id = papo_uid()) WITH CHECK (owner_id = papo_uid());
CREATE POLICY own ON conversation_skill USING (owner_id = papo_uid()) WITH CHECK (owner_id = papo_uid());

GRANT SELECT, INSERT, DELETE ON skill, skill_file, agent_skill, conversation_skill TO papo_app;
GRANT UPDATE (description, body, version, enabled, shared, size_bytes, updated_at) ON skill TO papo_app;
