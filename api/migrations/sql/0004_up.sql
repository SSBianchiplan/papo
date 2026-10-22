-- Escolha de modelo por nível (NULL = o do .env) e lista de modelos que a conta enxerga (gravada pelo teste da chave).
ALTER TABLE app_config
  ADD COLUMN model_quick   text CHECK (model_quick   IS NULL OR model_quick   ~ '^[a-z0-9.-]{3,80}$'),
  ADD COLUMN model_default text CHECK (model_default IS NULL OR model_default ~ '^[a-z0-9.-]{3,80}$'),
  ADD COLUMN model_complex text CHECK (model_complex IS NULL OR model_complex ~ '^[a-z0-9.-]{3,80}$'),
  ADD COLUMN model_router  text CHECK (model_router  IS NULL OR model_router  ~ '^[a-z0-9.-]{3,80}$'),
  ADD COLUMN models_available text[],
  ADD COLUMN models_checked_at timestamptz;

-- Catálogo: modelos atuais da Anthropic com preço público (US$ por milhão de tokens, set/2026). Não sobrescreve o que o admin editou.
INSERT INTO model_price (model, label, input_usd_mtok, output_usd_mtok) VALUES
  ('claude-fable-5-1',  'Claude Fable 5.1',  10, 50),
  ('claude-fable-5',    'Claude Fable 5',    10, 50),
  ('claude-opus-5-5',   'Claude Opus 5.5',    4, 20),
  ('claude-opus-5',     'Claude Opus 5',      5, 25),
  ('claude-opus-4-8',   'Claude Opus 4.8',    5, 25),
  ('claude-opus-4-7',   'Claude Opus 4.7',    5, 25),
  ('claude-opus-4-6',   'Claude Opus 4.6',    5, 25),
  ('claude-sonnet-5-5', 'Claude Sonnet 5.5',  2, 10),
  ('claude-sonnet-5',   'Claude Sonnet 5',    2, 10),
  ('claude-sonnet-4-6', 'Claude Sonnet 4.6',  3, 15),
  ('claude-haiku-4-5',  'Claude Haiku 4.5',   1,  5)
ON CONFLICT (model) DO NOTHING;
