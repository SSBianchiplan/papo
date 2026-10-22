# Changelog

Formato baseado em [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/).

## [1.0.0] — 2026-10-22
Primeira publicação do código, igual ao que está no ar em papo.gplansis.com.

### Incluído
- Conversas 1:1 e em grupo com agentes de IA, com respostas em tempo real e fontes citadas.
- Leitura de PDF, Word, Excel/CSV, PowerPoint, OpenDocument, RTF, e-mail, EPUB, HTML, Markdown e `.zip`, com ferramentas de busca, leitura e análise de planilha.
- Arquivos gerados (HTML e Markdown), skills por agente ou por conversa e gerenciador de arquivos com cota.
- Docs do hub: leitura só leitura direto na origem (pastas `:ro`, `hubreader/` com TLS fixado e SFTP).
- Governança de IA (Modelo de Camadas, ficha por agente) e Consultor de IA com rubrica versionada e parecer em PDF.
- Chave da IA cifrada, teto mensal de custo, limites por pessoa, preços editáveis e consumo por modelo e por pessoa.
- Multiusuário com RLS, gestão de contas pela Admin API do Keycloak, PWA instalável.

### Segurança
- Keycloak 26.0.7 → **26.7.5** (CVE-2026-18963, tomada de conta pelo reset de senha, e demais avisos da linha 26.0).
- Realm com `resetPasswordAllowed: false`.
- `hubreader/` com FastAPI 0.149 e Starlette 1.9.0.

### Publicação
- IPs, endereços de servidores e nomes pessoais trocados por valores de exemplo (`203.0.113.x`, documentação).
- Especificações movidas para `docs/`.
- README, capa, telas com dados fictícios, guias de contribuição e segurança, modelos de issue e PR, licença MIT.
