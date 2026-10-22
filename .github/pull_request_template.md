## O que muda
<!-- Resumo da mudança e o porquê. Referencie a issue: "Fecha #123". -->

## Tipo
- [ ] Correção de bug
- [ ] Nova funcionalidade
- [ ] Documentação
- [ ] Refatoração / manutenção

## Como testei
<!-- Passos, ambiente (local/Docker), navegadores. Cole o resumo do `pytest` e do `npm run build`. -->

## Capturas
<!-- Se mexeu na interface, antes/depois — só com agentes e arquivos fictícios (modo dev), nunca com conversas reais. -->

## Checklist
- [ ] `cd api && pytest` passa (PostgreSQL 16 + Redis, ver `tests/conftest.py`)
- [ ] `ruff check app tests` e `mypy app` sem erros novos
- [ ] `cd web && npm run build` passa (TypeScript strict)
- [ ] Invariante nova está no banco (RLS, CHECK, trigger ou FK) com código `INV-xxx` em `docs/SPEC-PAPO-001.md` e teste em `tests/test_invariants.py`
- [ ] Mudou a API? Regenerei `web/openapi.json` e `web/src/api/schema.d.ts`
- [ ] Ferramenta nova do agente só lê (nunca grava fora do próprio usuário) e respeita a ficha de governança
- [ ] Sem segredos, `.env`, dumps, conversas ou documentos reais no commit
- [ ] `CHANGELOG.md` atualizado (se visível para quem usa)
