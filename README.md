<p align="center">
  <a href="https://papo.gplansis.com"><img src=".github/capa.png" alt="GPlanSiS|Papo: converse com agentes de IA que leem os seus arquivos" width="100%"></a>
</p>

<h1 align="center">GPlanSiS|Papo</h1>

<p align="center">
  <b>Chat com agentes de IA que leem PDF, Word e planilhas, fazem as contas e respondem citando documento e página.</b>
</p>

<p align="center">
  <a href="https://papo.gplansis.com"><img alt="No ar" src="https://img.shields.io/badge/no%20ar-papo.gplansis.com-21C063?style=for-the-badge"></a>
  <img alt="Versão" src="https://img.shields.io/badge/versão-1.0.0-12343B?style=for-the-badge">
  <a href="LICENSE"><img alt="licença MIT" src="https://img.shields.io/badge/licen%C3%A7a-MIT-2ea44f?style=flat-square"></a>
</p>

<p align="center">
  <img alt="Python" src="https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white">
  <img alt="FastAPI" src="https://img.shields.io/badge/FastAPI-async-009688?logo=fastapi&logoColor=white">
  <img alt="PostgreSQL" src="https://img.shields.io/badge/PostgreSQL-16%20%C2%B7%20RLS-4169E1?logo=postgresql&logoColor=white">
  <img alt="Redis" src="https://img.shields.io/badge/Redis-7.4%20%C2%B7%20arq-DC382D?logo=redis&logoColor=white">
  <img alt="Keycloak" src="https://img.shields.io/badge/Keycloak-26.7%20%C2%B7%20OIDC-4D4D4D?logo=keycloak&logoColor=white">
  <img alt="React" src="https://img.shields.io/badge/React-19-61DAFB?logo=react&logoColor=black">
  <img alt="TypeScript" src="https://img.shields.io/badge/TypeScript-strict-3178C6?logo=typescript&logoColor=white">
  <img alt="Anthropic" src="https://img.shields.io/badge/IA-Anthropic%20Claude-D97757">
  <img alt="PWA" src="https://img.shields.io/badge/PWA-instalável-5A0FC8?logo=pwa&logoColor=white">
</p>

<p align="center">
  <a href="https://papo.gplansis.com"><b>Abrir o GPlanSiS|Papo →</b></a>
  &nbsp;·&nbsp; <a href="#como-rodar-localmente">Rodar localmente</a>
  &nbsp;·&nbsp; <a href="#contribua">Contribua</a>
</p>

---

## O que é

O **GPlanSiS|Papo** é um chat no jeito de um mensageiro, mas os contatos são **agentes de IA**. Cada agente tem persona, cor e uma base de arquivos. Você conversa com ele 1:1 ou monta **grupos** com vários agentes, e cada um responde com o que leu nos documentos:
- em PDF, cita a página;
- em planilha, faz a conta com ferramenta, em vez de estimar;
- sempre mostra a fonte.

Os dados de cada conta ficam isolados no PostgreSQL por **RLS**: nem o administrador lê as conversas de outra pessoa. A chave da IA é cifrada no banco. O custo é medido por modelo e por pessoa, com teto mensal. Toda execução de agente deixa trilha.

O Papo faz parte do ecossistema **GPlanSiS|Group** e lê, só leitura, os documentos dos outros sistemas do hub ("Docs do hub").

## Funcionalidades

- **Conversas 1:1 e em grupo** com agentes. No grupo, um roteador escolhe quem responde, ou você chama alguém com `@nome`. Tem respostas em tempo real (WebSocket), recibos de leitura, "digitando…", fixar, exportar `.txt` e menu de clique direito ou toque longo.
- **Agentes que leem arquivos.** Leem PDF, Word, Excel/CSV, PowerPoint, OpenDocument, RTF, e-mail, EPUB, HTML, Markdown, Jupyter, código e `.zip` com documentos. Usam as ferramentas `listar_documentos`, `buscar_nos_documentos`, `ler_documento` e `analisar_planilha` (descrever, filtrar, agrupar e somar) e respondem com **fontes citadas**.
- **Arquivos gerados.** Relatórios em HTML ou Markdown chegam como anexo na conversa, com prévia isolada (iframe sem script) e download.
- **Skills.** Envie um `SKILL.md`, `.zip` ou `.skill` e ative por agente ou por conversa. O agente carrega a skill com `usar_skill` quando a tarefa combina.
- **Docs do hub.** Os agentes leem documentos de outros sistemas **direto na origem**: pastas montadas só leitura, um leitor remoto com TLS fixado (`hubreader/`) ou SFTP. O Papo guarda só o índice, nunca o arquivo.
- **Governança de IA.** Cada agente tem uma ficha com dono, camada real, moderação M0–M3, lista fechada de ferramentas, teto de custo, tempo e iterações por turno, gatilhos e retenção. O motor aplica a ficha em código e registra cada evento.
- **Consultor de IA.** Um contato que recebe uma proposta de IA (PDF ou Word) e devolve um **parecer com nota determinística**: a rubrica é versionada, o hash é reproduzível e o PDF sai selado. O texto do modelo nunca define a nota. Ver [`docs/SPEC-GPS-PAPO-CIA-001.md`](docs/SPEC-GPS-PAPO-CIA-001.md).
- **Custos sob controle.** Há teto mensal em US$, limite diário de tokens e limite de mensagens por minuto por pessoa. A tabela de preços é editável, e o consumo aparece por dia, por modelo e por pessoa.
- **Administração.** Inclui a chave da Anthropic, cifrada com AES-GCM e testada no worker, e a escolha do modelo de cada nível (Rápido, Padrão, Avançado e roteador). A gestão de contas usa a Admin API do Keycloak, com papéis `papo-admin` e `papo-master`. A tela **Fluxo do sistema** mostra o estado ao vivo de cada peça.
- **PWA instalável**, com layout de uma coluna no celular, diálogos em bottom sheet e tema claro e escuro.

## Telas

As capturas usam dados fictícios: modo de desenvolvimento local, agentes, planilha e manual inventados.

| Conversa com um agente que analisa uma planilha | Grupo com dois agentes |
|---|---|
| <img src=".github/telas/conversa-planilha.png" alt="Agente responde a receita por região com tabela e fonte citada"> | <img src=".github/telas/grupo.png" alt="Grupo com Analista de Vendas e Manutenção respondendo à mesma pergunta"> |

| Gerenciador de arquivos | No celular |
|---|---|
| <img src=".github/telas/arquivos.png" alt="Armazenamento por local e por tipo, cota e limpeza"> | <img src=".github/telas/celular.png" alt="Conversa no celular citando a página do manual" width="300"> |

## Arquitetura

```mermaid
flowchart LR
  U["Navegador / PWA"] -->|HTTPS + WSS| P["Proxy<br/>Traefik ou Caddy"]
  P --> W["web<br/>nginx + React 19"]
  P --> A["api<br/>FastAPI"]
  P --> K["Keycloak 26.7<br/>realm papo"]
  A -->|JWKS| K
  A --> PG[("PostgreSQL 16<br/>RLS por usuário")]
  A --> R[("Redis<br/>fila + eventos")]
  A --> S[("S3<br/>MinIO / RustFS")]
  R --> WK["worker (arq)"]
  WK --> PG
  WK --> S
  WK -->|única saída| AI["API da Anthropic"]
  A --> GW["hubgw<br/>gateway só leitura"]
  WK --> GW
  GW --> F1["pastas :ro"]
  GW -->|TLS fixado + token| F2["hubreader<br/>outra VPS"]
  GW -->|SFTP| F3["site / WordPress"]
```

**Pontos de projeto:**
- **O banco é a fonte da verdade.** As invariantes (`INV-xxx`) moram no PostgreSQL: RLS em todas as tabelas, FKs compostas `(owner_id, id)`, CHECKs e triggers. Cada uma tem um teste RED-TEAM em `api/tests/test_invariants.py`. Ver [`docs/SPEC-PAPO-001.md`](docs/SPEC-PAPO-001.md).
- **Só o worker sai para a internet.** Banco, Redis e storage ficam numa rede interna (`papo_data`, `internal: true`). A API não fala com a Anthropic.
- **Dois papéis no banco:** `papo_owner` roda as migrations e `papo_app` atende a aplicação, sem DDL e sujeito a RLS.
- **Nada de HTML do modelo na página.** As respostas são escapadas antes de ganhar formatação, e as prévias de arquivo abrem em iframe sandbox.

## Stack

| Camada | Tecnologia |
|---|---|
| API | Python 3.12, FastAPI, Pydantic v2, SQLAlchemy async + asyncpg, Alembic (migrations em SQL com `up`/`down`) |
| Fila e tempo real | Redis 7.4, arq (worker), WebSocket |
| IA | SDK oficial `anthropic`, ferramentas tipadas, roteador de grupo, cache de prompt |
| Leitura de arquivos | pypdf, python-docx, openpyxl, Pillow, extratores próprios para Office/ODF/RTF/EPUB/e-mail |
| Banco | PostgreSQL 16 (RLS, pgcrypto, unaccent) |
| Arquivos | S3 (MinIO ou RustFS) |
| Identidade | Keycloak 26.7 (OIDC + PKCE), tema de login próprio |
| Web | React 19, Vite 6, TypeScript strict, Tailwind 4, TanStack Query, Zustand, `openapi-fetch` com tipos gerados do OpenAPI, `oidc-client-ts` |
| Entrega | Docker Compose, nginx (CSP), Traefik ou Caddy na frente |
| Testes | pytest (140 testes: invariantes, ferramentas, leitores, fluxo ponta a ponta, governança, consultor, hub, contas) |

## Como rodar localmente

### Opção 1: desenvolvimento, sem Keycloak e sem chave de IA

O mais rápido. A API aceita um usuário de teste (`AUTH_DEV_MODE`) e o modelo `echo` responde sem rede. Precisa de PostgreSQL 16 e Redis locais. O Docker serve:

```bash
# banco e Redis de teste (o script cria os papéis papo_owner/papo_app e o banco papo)
docker run -d --name papo-pg -p 127.0.0.1:5433:5432 -e POSTGRES_PASSWORD=postgres \
  -e PAPO_OWNER_PASSWORD=owner -e PAPO_APP_PASSWORD=app -e KEYCLOAK_DB_PASSWORD=kc \
  -v "$PWD/infra/postgres/10-init.sh:/docker-entrypoint-initdb.d/10-init.sh:ro" postgres:16.6-alpine
docker run -d --name papo-redis -p 127.0.0.1:6380:6379 redis:7.4.1-alpine

cd api && python3.12 -m venv .venv && . .venv/bin/activate && pip install -e ".[dev]"
MIGRATION_DATABASE_URL=postgresql+psycopg://papo_owner:owner@127.0.0.1:5433/papo alembic upgrade head
export ENV=development AUTH_DEV_MODE=true LLM_PROVIDER=echo STORAGE_DIR=/tmp/papo-files \
       DATABASE_URL=postgresql+asyncpg://papo_app:app@127.0.0.1:5433/papo REDIS_URL=redis://127.0.0.1:6380/0 \
       SECRETS_KEY=chave-local-qualquer
uvicorn app.main:app --reload &        # API em :8000
arq app.worker.WorkerSettings &        # worker

cd ../web && npm ci && VITE_AUTH_MODE=dev npm run dev   # http://localhost:5173 (pede um nome de usuário de teste)
```

- **Modelo real:** troque `LLM_PROVIDER=echo` por `anthropic` e defina `ANTHROPIC_API_KEY`.
- **Fora de development/test:** `AUTH_DEV_MODE`, `STORAGE_DIR` e `echo` são **recusados** pela API.
- **Usuários de teste:** `admin` é tratado como administrador e `master` como master (variáveis `DEV_ADMINS` e `DEV_MASTERS`).

### Opção 2: a pilha completa com Docker Compose

```bash
cp .env.example .env
./ops/gen-secrets.sh >> .env            # uma vez só
# edite: APP_DOMAIN, AUTH_DOMAIN, ACME_EMAIL, ADMIN_IP_ALLOWLIST (e, se quiser, ANTHROPIC_API_KEY)
chmod 600 .env
docker compose build && docker compose up -d
docker compose ps                       # tudo healthy; "migrate" termina com Exited (0)
```

**Primeiro acesso:**
1. Abra `https://AUTH_DOMAIN/admin` de um IP da `ADMIN_IP_ALLOWLIST` e troque a senha do admin do Keycloak.
2. No realm **papo**, crie as contas.
3. Para ligar a gestão de contas pela interface, dê ao service account do cliente `papo-users` os papéis `view-users`, `query-users` e `manage-users` de `realm-management`, e ponha o segredo do cliente em `KC_ADMIN_CLIENT_SECRET`.

**Atrás de um proxy que já existe** (Caddy, por exemplo), use `docker-compose.hub.yml`:
- o Traefik fica desligado e as portas ficam em `127.0.0.1`;
- o login é servido no mesmo domínio, em `/auth` (`AUTH_URL=https://APP_DOMAIN/auth`, `KC_HTTP_RELATIVE_PATH=/auth`);
- há um exemplo em `infra/caddy/papo.caddy`.

### Testes

```bash
cd api
TEST_PG_ADMIN=postgresql://postgres:postgres@127.0.0.1:5433/postgres TEST_PG_HOST=127.0.0.1:5433 \
TEST_REDIS_URL=redis://127.0.0.1:6380/9 pytest -q          # 140 passed
ruff check app tests && mypy app
cd ../web && npm run build                                  # tsc strict + vite
```

Os testes criam um banco temporário, aplicam todas as migrations, testam e revertem até a base, e no fim apagam o banco. Depois de mudar a API, regenere os tipos do front:

```bash
python -c "import json;from app.main import app;json.dump(app.openapi(),open('../web/openapi.json','w'))"
cd ../web && npm run gen:api
```

## Estrutura de pastas

```
papo/
├── api/
│   ├── app/
│   │   ├── agent/          # motor do agente, ferramentas, cliente da IA, prompts
│   │   ├── consultor/      # Consultor de IA: rubrica versionada, parecer, PDF
│   │   ├── extract/        # leitores de PDF, Office, ODF, RTF, EPUB, e-mail…
│   │   ├── hub/            # Docs do hub: regras, fontes, backends (local/remoto/SFTP)
│   │   ├── modules/        # rotas da API (conversas, agentes, arquivos, admin…)
│   │   ├── governanca.py   # Modelo de Camadas e ficha de governança
│   │   ├── hubgw.py        # gateway só leitura das fontes do hub
│   │   ├── kcadmin.py      # gestão de contas pela Admin API do Keycloak
│   │   └── worker.py       # jobs do arq (responder, ler documento, reindexar)
│   ├── migrations/         # Alembic + SQL up/down com as invariantes
│   └── tests/              # 140 testes (RED-TEAM das invariantes incluído)
├── web/                    # React 19 + Vite + TS strict (PWA)
├── hubreader/              # leitor do hub para outra VPS (só GET, TLS fixado, token, IP)
├── infra/                  # Keycloak (realm + tema), Traefik, Caddy, init do PostgreSQL
├── ops/                    # gerar segredos, backup e restauração
└── docs/                   # especificações (invariantes, camadas da IA, consultor)
```

## Variáveis de ambiente

Os nomes estão abaixo, e os valores de exemplo ficam em [`.env.example`](.env.example). Os segredos são gerados por `ops/gen-secrets.sh` e ficam só no `.env` do servidor.

| Variável | Para quê |
|---|---|
| `APP_DOMAIN`, `AUTH_DOMAIN`, `AUTH_URL`, `KC_HTTP_RELATIVE_PATH` | Endereços do app e do login |
| `ACME_EMAIL`, `ADMIN_IP_ALLOWLIST` | Let's Encrypt (Traefik) e redes que abrem o console do Keycloak |
| `POSTGRES_PASSWORD`, `PAPO_OWNER_PASSWORD`, `PAPO_APP_PASSWORD`, `KEYCLOAK_DB_PASSWORD` | Banco: superusuário, dono do schema, aplicação e Keycloak |
| `KEYCLOAK_ADMIN_USER`, `KEYCLOAK_ADMIN_PASSWORD` | Admin inicial do Keycloak |
| `KC_ADMIN_CLIENT_SECRET` | Segredo do cliente `papo-users` (gestão de contas) |
| `REDIS_PASSWORD`, `MINIO_ROOT_USER`, `MINIO_ROOT_PASSWORD` | Redis e storage S3 |
| `SECRETS_KEY` | Cifra a chave da IA e as senhas de SFTP guardadas no banco |
| `HUBGW_TOKEN` | Token entre API/worker e o gateway do hub |
| `ANTHROPIC_API_KEY`, `ANTHROPIC_WORKSPACE_ID` | Chave padrão da IA (a cadastrada no painel tem prioridade) |
| `MODEL_QUICK`, `MODEL_DEFAULT`, `MODEL_COMPLEX`, `MODEL_ROUTER` | Modelo de cada nível |
| `DAILY_TOKEN_LIMIT`, `MESSAGES_PER_MINUTE` | Limites por pessoa |
| `PAPO_VERSION` | Tag das imagens `papo-api` e `papo-web` |

## Operação

- **Backup.** `./ops/backup.sh /backups` faz o dump dos bancos `papo` e `keycloak`, copia o storage e grava `SHA256SUMS`. `./ops/restore.sh` é destrutivo: confere os hashes e mede o tempo. Ensaie a restauração antes de depender dela.
- **Atualização.** Faça o backup, rode `docker compose build` e depois `docker compose up -d`. O serviço `migrate` aplica as migrations antes de a API subir. Para voltar uma migration: `docker compose run --rm migrate alembic downgrade <revisão>`.
- **Keycloak.** A atualização migra o banco do Keycloak sozinha, e voltar de versão exige restaurar o dump. Depois da importação inicial, o realm é configurado pelo console ou pelo `kcadm.sh`. O `infra/keycloak/papo-realm.json` só vale para um realm novo e vem com o reset de senha por e-mail desligado.

## Limites conhecidos

- PDF escaneado (sem texto) é sinalizado, mas não passa por OCR.
- `.doc`, `.xls` e `.ppt` antigos e fotos HEIC ainda não são lidos.
- Uma mensagem leva um anexo por vez.
- A busca é textual em português, sem embeddings. Em bases muito grandes, o próximo passo é o pgvector.

## Contribua

O Papo é aberto e quer gente junto: quem programa, quem testa com documentos de verdade (os seus, localmente) e quem escreve.

**Boas primeiras issues:**
- **OCR** para PDF escaneado (por exemplo, OCRmyPDF no worker, com limite de páginas e de memória).
- **Leitores novos:** HEIC, `.doc`/`.xls`/`.ppt` antigos (via LibreOffice em processo isolado).
- **Busca semântica** com pgvector, mantendo a busca textual como reserva.
- **Mais de um anexo** por mensagem.
- **Acessibilidade:** leitor de tela nas bolhas, foco no teclado e contraste no tema escuro.
- **Testes do front**, que hoje só passa pelo typecheck e pelo build.
- **Traduções** da interface (hoje só em pt-BR).

**Como começar:** leia o [CONTRIBUTING.md](CONTRIBUTING.md), rode a [opção 1](#opção-1-desenvolvimento-sem-keycloak-e-sem-chave-de-ia) e abra uma issue com o modelo "Ideia" antes de mudanças grandes. Falhas de segurança vão por e-mail, conforme o [SECURITY.md](SECURITY.md), nunca em issue pública.

## Licença

[MIT](LICENSE) © 2026 GPlanSiS.

**Avisos de terceiros:**
- **Fonte Manrope**, embutida no tema de login em `infra/keycloak/themes/papo/login/resources/fonts/`: SIL Open Font License 1.1 (texto em `OFL.txt` na mesma pasta).
- **Dependências Python e npm:** são instaladas pelo `pip`/`npm` e seguem as licenças de cada uma. Nenhum código de terceiros está copiado no repositório.

## Créditos

Feito pela **GPlanSiS** como parte do ecossistema **GPlanSiS|Group**. Contato: **contato@gplansis.com**.
