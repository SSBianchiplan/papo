# SPEC-PAPO-001 · Papo — chat com agentes de IA que leem arquivos e dados

**Fonte da verdade:** PostgreSQL 16 (`papo`). Arquivos originais no MinIO; Redis guarda só estado efêmero (fila, eventos, travas).
**Linguagem normativa:** RFC-2119 (DEVE, NÃO DEVE, PODE). Cada invariante tem teste RED-TEAM em `api/tests/test_invariants.py`.

## Invariantes

| ID | Regra | Onde é garantida |
|---|---|---|
| INV-SEC-001 | Um usuário NÃO DEVE ler nem gravar dado de outro usuário. | RLS em todas as tabelas (`papo.uid` por transação) |
| INV-AGT-001 | Nome de agente DEVE ser único por usuário, sem diferenciar maiúsculas. | índice único |
| INV-CNV-001 | DM DEVE ter agente e não ter nome; grupo DEVE ter nome e não ter agente. | CHECK |
| INV-CNV-002/004 | Agente, conversa e membros DEVEM pertencer ao mesmo usuário. | FKs compostas `(owner_id, id)` |
| INV-CNV-003 | DEVE existir no máximo uma DM por agente. | índice único parcial |
| INV-CNV-005 | Membros SÓ PODEM existir em grupos. | trigger |
| INV-MSG-001 | `seq` DEVE ser crescente e sem lacunas por conversa. | trigger com trava de linha |
| INV-MSG-002/003 | Forma da mensagem por autor; mensagem do usuário NÃO PODE ser vazia; mensagem do agente DEVE ter execução (pode levar anexo gerado por ele). | CHECK |
| INV-MSG-006 | Agente só anexa arquivo que ele mesmo gerou; usuário só anexa arquivo enviado. | trigger |
| INV-DOC-005 | Liberar espaço de anexo preso a mensagem não apaga o documento: tira arquivo e índice e registra em `document_purge` (append-only). | tabela + RLS |
| INV-HUB-001 | Arquivo do hub nunca é copiado para o Papo: o banco guarda só metadados (`hub_file`), os bytes passam em memória. | schema + teste |
| INV-HUB-002 | Leitura do hub só dentro das raízes, sem symlink para fora, sem segredo nem ruído, só GET. | `hub/rules.py` + `:ro` + teste |
| INV-HUB-003 | Agente só lê fontes/pastas ligadas a ele; usuário comum só fontes visíveis para todos. | API + motor + teste |
| INV-SKL-001 | Skill é lida pelo dono ou, se compartilhada por admin, por todos; só o dono altera ou apaga. | RLS |
| INV-MSG-004 | Anexo DEVE pertencer à mesma conversa; imagem DEVE pertencer ao dono. | trigger |
| INV-MSG-005 | Mensagem NÃO DEVE sofrer UPDATE nem DELETE direto (só cascata de exclusão de conversa/conta). | trigger + privilégios |
| INV-RCP-001 | Recibo SÓ para mensagem do usuário, na ordem enviado → entregue → lido; append-only. | trigger |
| INV-RUN-001/002 | Execução segue `queued → running → done/failed/cancelled`; terminal é final; terminal ⇔ `finished_at`. | trigger + CHECK |
| INV-RUN-003 | SÓ responde agente que participa da conversa. | trigger |
| INV-RUN-004 | Contadores de consumo NÃO DEVEM diminuir. | trigger |
| INV-RUN-005 | No máximo UMA execução ativa por conversa. | índice único parcial (+ trava no Redis na API) |
| INV-AUD-001 | Trilha da execução é append-only e encadeada por SHA-256 calculado pelo banco; `verify_run_chain()` detecta adulteração. | trigger SECURITY DEFINER |
| INV-DOC-001..004 | Documento tem exatamente um escopo; chave de storage prefixada pelo dono; sai de `pending` uma única vez; identidade imutável. | CHECK + trigger |

## Política de ferramentas do agente (P4)

As ferramentas de leitura (`listar_documentos`, `buscar_nos_documentos`, `ler_documento`, `analisar_planilha`, `buscar_na_conversa`, `usar_skill`) só leem e rodam sob o RLS do dono da conversa. A única ferramenta de saída é `gerar_arquivo`: ela só **cria** um anexo novo (HTML no design system ou Markdown) na conversa em curso, no máximo 5 por resposta; nunca altera nem apaga dado existente. O HTML é montado pelo servidor a partir de Markdown, com HTML cru do modelo escapado, e o download sai como anexo com `CSP: sandbox`. Não há ferramenta que altere dado; qualquer ferramenta de escrita futura DEVE entrar como proposta com aprovação humana registrada no banco.
Conteúdo de arquivo é dado, não instrução: o prompt manda ignorar ordens embutidas, mas a proteção real é a ausência de ferramenta de escrita e o RLS.

## Falhas no meio

| Falha | Comportamento |
|---|---|
| Worker cai durante resposta | O reaper (`papo_reap_runs`, a cada minuto e na subida do worker) marca como `failed` execuções presas há mais de 16 min; a trava do Redis expira em 15 min; a conversa volta a aceitar mensagens. |
| Arquivo corrompido/protegido | Documento vai para `failed` com nota legível; a fila segue. |
| Provedor de IA fora/limite | Execução `failed`, mensagem de erro legível no balão, consumo parcial registrado. |
| Usuário interrompe | Execução `cancelled`, texto parcial preservado com "Resposta interrompida.". |
| Limite diário atingido | Mensagem de sistema; nenhuma chamada ao modelo. |

## Gates SDD·BE (estado nesta entrega)

| Gate | Estado | Evidência |
|---|---|---|
| SPEC | PASS | este documento |
| BUILD | PASS | migration aplica, reverte e reaplica (`alembic upgrade/downgrade`, executado no teardown dos testes) |
| SELF-CHECK | PASS | 87 testes pytest (verificados em 02/10/2026, após corrigir pytest-asyncio 0.24→0.26, cujo `asyncio_default_test_loop_scope` era ignorado e derrubava 6 testes de fluxo); `mypy --strict` e `ruff` limpos; cobertura total 78%; `tsc` strict sem erros |
| RED-TEAM | PASS | 38 tentativas de violação direto no banco, todas recusadas |
| E2E | PASS | navegador (desktop e celular) com API, worker e modelo eco: criar agente, anexar PDF, resposta ao vivo, ✓✓ azul, etapas, Fluxo com trilha íntegra |
| HUMAN-GATE | PENDENTE | revisar contrato da API, testar com chave real da Anthropic, ensaiar restauração e medir o tempo |
| DONE | PENDENTE | depende do HUMAN-GATE |


## Governança de IA e Consultor de IA (SPEC-GPS-CAMADAS-001 v1.0.0 · SPEC-GPS-PAPO-CIA-001, onda 1)

| ID | Regra | Onde é garantida |
|---|---|---|
| INV-GOV-001 (I4) | Agente só fica ativo com ficha completa e dono nomeado. | CHECK `ficha_i4_ativo` |
| INV-GOV-002 | Matriz camada × moderação: M3 só na camada 1, ou na 6 com exceção aprovada; M2 na 5 só para uso interno com evidência. | CHECK `ficha_matriz` |
| INV-GOV-003 | Toda mudança de ficha gera versão no histórico, com quem decidiu; promoção para M2/M3 só por administrador. | trigger + API |
| INV-GOV-004 | Ferramenta fora da lista fechada não é oferecida; tentativa é recusada e registrada como T8; M0 nunca recebe escrita. | motor + `governanca_evento` |
| INV-GOV-005 | Gatilho aplicável (T1–T8) rebaixa para M1 e registra o código; teto de custo, tempo e iterações por turno encerram o turno com mensagem. | motor |
| I1 | Estado ATENDE exige evidência validada (trecho literal na página) do mesmo critério. | trigger `consultor_i1` |
| I2 | Estados, respostas, evidências e pareceres só recebem INSERT. | privilégios + triggers |
| I3 | Cada parecer grava o hash do anterior; `verify_parecer_chain()` detecta adulteração. | trigger `consultor_i3` |

**Gates do Consultor (§12 da CIA-001)** — estado em 04/10/2026:

| Gate | Estado | Evidência |
|---|---|---|
| G01 determinismo (50×) | PASS | `test_g01_mesma_entrada_mesma_nota_e_hash` |
| G02 ATENDE sem evidência falha (I1) | PASS | `test_fluxo_completo…` (insert direto recusado) |
| G03 UPDATE/DELETE negados | PASS | idem |
| G04 adulteração quebra a cadeia | PASS | `test_g04_adulterar_parecer_quebra_a_cadeia` |
| G05 contestação preserva a versão anterior | PASS | `test_fluxo_completo…` |
| G06 100 paráfrases recusadas | PASS | `test_g06_parafrase_nunca_vira_citacao` |
| G07 suíte de 12 documentos adversariais | HOLE | só 1 documento com instrução embutida testado |
| G08 isolamento com dois tenants em paralelo | HOLE | RLS por dono em todas as tabelas; teste paralelo não escrito |
| G09 ativar sem ficha/dono falha (I4) | PASS | `test_i4_e_matriz_no_banco` |
| G10 conjunto ouro (20 propostas, 2 avaliadores) | HOLE | depende de propostas reais e avaliadores humanos |
| G11 toda pergunta com respostas e mapa | PASS | `test_g11_…` |
| G12 PDF corresponde ao registro selado | HOLE | PDF determinístico e SHA-256 gravado; conferência automática não escrita |
| G13 resumo ≤ 60 s p95 (30 páginas) | HOLE | medido 36 s numa proposta de 3 páginas, em produção |
| G14 custo ≤ US$ 1,50 p95 | HOLE | teto aplicado pela ficha; p95 não medido |

Pela §12, com gates em HOLE o Consultor fica como **onda 1, uso interno** (decisão D5 padrão: só equipe GPlanSiS).
