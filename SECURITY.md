# Política de segurança

## Versões suportadas
| Versão | Suporte |
|---|---|
| 1.0.x (em produção em papo.gplansis.com) | ✅ |

## Como relatar uma vulnerabilidade
**Não abra issue pública.** Envie um e-mail para **contato@gplansis.com** com o assunto `[SEGURANÇA] GPlanSiS|Papo`, contendo:
- descrição do problema e impacto;
- passos para reproduzir (ou prova de conceito);
- versão/commit, navegador e ambiente usados.

Confirmamos o recebimento assim que possível, mantemos você informado sobre a correção e damos crédito na publicação, se desejar.

## Escopo
- Isolamento entre usuários (RLS) e papéis `papo-admin`/`papo-master`.
- Validação de tokens OIDC e gestão de contas pela Admin API do Keycloak.
- Ferramentas do agente e injeção de prompt que leve a ler ou gravar fora do escopo.
- Leitores de arquivo (PDF, Office, ZIP).
- Prévias em iframe e formatação das respostas.
- Gateway e leitor do hub (`hubgw`, `hubreader/`).
- Cifra da chave da IA.
- Limites de custo.

Teste numa **instância local**, no modo de desenvolvimento. **Não** teste contra papo.gplansis.com nem tente acessar dados de outras pessoas. Uma forma rápida de achar furos é propor um ataque novo para `api/tests/test_invariants.py`.
