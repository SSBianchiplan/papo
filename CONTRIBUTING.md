# Como contribuir com o GPlanSiS|Papo

Obrigado pelo interesse! Este guia explica como propor mudanças de um jeito que a revisão seja rápida.

## Antes de começar
- Leia o [código de conduta](CODE_OF_CONDUCT.md).
- Para mudanças maiores que uma correção pontual, **abra uma issue primeiro** (modelos "Ideia" ou "Bug") e combine a abordagem.
- Falhas de segurança **não** vão em issue pública: siga a [política de segurança](SECURITY.md).

## Ambiente de desenvolvimento
Siga [Como rodar localmente → opção 1](README.md#como-rodar-localmente). Você vai precisar de:
- PostgreSQL 16 e Redis em Docker;
- a API com `ENV=development AUTH_DEV_MODE=true LLM_PROVIDER=echo`;
- o front com `VITE_AUTH_MODE=dev npm run dev`.

Não precisa de Keycloak nem de chave da Anthropic para a maior parte do trabalho.

## Organização do código
- `api/migrations/sql/*_up.sql` / `*_down.sql`: **onde moram as regras**, com RLS, CHECKs, triggers e FKs compostas de cada `INV-xxx` (lista em `docs/SPEC-PAPO-001.md`).
- `api/app/agent/`: motor do agente (`engine.py`), ferramentas tipadas (`tools.py`), cliente da IA (`llm.py`) e prompts.
- `api/app/extract/`: leitores de arquivo. Formato novo entra aqui, com teste em `tests/test_parsers.py`.
- `api/app/modules/`: rotas da API. `api/app/worker.py`: jobs do arq.
- `api/app/hub/` e `hubreader/`: leitura só leitura dos Docs do hub. As regras (`rules.py`) são as mesmas nos dois lados.
- `web/src/`: React 19. Os tipos da API vêm de `web/openapi.json` (`npm run gen:api`).

## Regras do projeto
- **Isolamento por usuário é inegociável.** Toda tabela nova tem `owner_id`, RLS e teste em `tests/test_invariants.py` provando que outro usuário não lê nem grava.
- **Invariante nova vai para o banco** com código `INV-xxx` e entra em `docs/SPEC-PAPO-001.md`. A API e a tela só repetem a regra para dar uma mensagem melhor.
- **Migrations sempre com `down`.** Os testes aplicam e revertem tudo até a base.
- **Ferramentas do agente só leem** e nunca saem do escopo do usuário. Ferramenta nova entra na lista fechada da ficha de governança.
- **Só o worker sai para a internet.** Não adicione chamadas externas na API.
- **Nada de HTML do modelo na página.** A formatação passa por `web/src/format.ts`, que escapa primeiro.
- **Interface em português do Brasil**, com textos curtos e diretos.
- **Dados:** use só agentes, conversas e arquivos fictícios. Nunca ponha em commits, testes, issues ou capturas:
  - conversas ou documentos reais;
  - chaves da Anthropic;
  - `.env`, dumps ou tokens.

## Antes de abrir o PR
```bash
cd api && pytest -q && ruff check app tests && mypy app
cd ../web && npm run build
```

## Pull requests
1. Faça um fork e crie uma branch a partir de `main` (`feat/…`, `fix/…`, `docs/…`).
2. Faça commits pequenos, com mensagem no imperativo explicando o porquê.
3. Preencha o modelo do PR: o que mudou, como testou e capturas, se mexeu na interface.
4. Atualize o `CHANGELOG.md` quando a mudança for visível para quem usa.

## Dúvidas
Abra uma issue com o modelo "Pergunta" ou escreva para contato@gplansis.com.
