# SPEC-GPS-CAMADAS-001 · Modelo de Camadas da IA

Oct 4, 2026 · GPlanSiS

## 1. Propósito e escopo

Esta spec define o Modelo de Camadas da IA do GPlanSiS|Group: seis camadas, uma ficha padrão por camada, regras de classificação e a ligação entre camada e nível de autonomia. É a referência única usada pelo Consultor de IA do Papo (SPEC-GPS-PAPO-CIA-001), pelos Workshops de IA por setor e pela ficha de governança de todo agente do grupo.

**O que o modelo responde, para qualquer sistema ou proposta.**

- Em que camada o sistema realmente está, independentemente de como é vendido.
- Qual é a camada mínima que resolveria o mesmo trabalho.
- Que evidência, métrica e controle são exigidos naquela camada.
- Até que nível de moderação o sistema pode operar.

**Fora do escopo.** Escolha de fornecedor, preço, aspectos jurídicos e a implementação técnica de cada camada; essas ficam nas specs de cada produto.

## 2. Visão geral

O modelo tem seis camadas, da IA clássica à agêntica, e cinco elementos transversais exigidos em todas; a moderação máxima de cada camada está à direita de cada faixa.

&#91;embedded content: modelo de camadas da IA · 6 camadas e 5 elementos transversais\]

A ordem vertical indica capacidade, custo e risco operacional crescentes, não qualidade da solução: a camada 1 admite M3 justamente por ser inteiramente auditável.

## 3. Princípios do modelo

As camadas organizam a conversa; não são uma escada de valor. Sete princípios valem em qualquer aplicação do modelo.

1. **Camada não é mérito.** Subir de camada aumenta capacidade, custo, opacidade e risco operacional. A camada certa é a mínima que resolve o trabalho com a evidência disponível.
2. **Camada real prevalece sobre a declarada.** Um sistema é classificado pelo que faz, não pelo que o material comercial diz.
3. **As camadas se sobrepõem.** Um sistema real costuma usar várias; ele é classificado pela mais alta com sinal confirmado e avaliado em todas as que usa.
4. **Toda camada tem teste de sucesso.** Sem métrica, limiar e conjunto de avaliação definidos antes da implantação, o sistema não sai do piloto.
5. **Controle cresce com a camada.** Quanto mais alta a camada, mais controles obrigatórios e menor a autonomia padrão.
6. **A IA propõe, o humano decide.** Nenhuma camada, em nenhum nível, autoriza efeito irreversível sem decisão humana registrada.
7. **O transversal não é opcional.** Dados, avaliação, governança, observabilidade e dono humano atravessam todas as camadas e são exigidos em todas.

## 4. Ficha padrão de camada

Cada camada é especificada pelos mesmos nove atributos, na mesma ordem, para que avaliações de camadas diferentes sejam comparáveis.

| Atributo | O que define |
| --- | --- |
| Definição | O que a camada é, em uma frase |
| Componentes | Métodos, arquiteturas ou capacidades que pertencem a ela |
| Sinais de classificação | O que, num sistema ou proposta, confirma que ela está presente |
| Quando usar | Tipo de problema em que ela é a camada mínima adequada |
| Pergunta decisiva | A pergunta que mais separa proposta séria de demonstração |
| Teste de sucesso | Métrica, forma de medição e condição de aprovação |
| Controles obrigatórios | O que precisa existir antes de produção |
| Sinais de alerta | Padrões que indicam risco ou avaliação fraca |
| Moderação máxima | Nível mais alto de autonomia permitido sem exceção aprovada |

Os IDs de critério usados pela rubrica do Consultor de IA (C1.x a C6.x) derivam dos controles e do teste de sucesso de cada camada.

## 5. Camada 1 · IA clássica

É a camada mais auditável e, para decisões com restrições estáveis, quase sempre a mais barata e segura.

| Atributo | Especificação |
| --- | --- |
| Definição | Sistemas que decidem a partir de conhecimento e regras explícitas, escritas por pessoas |
| Componentes | IA simbólica, sistemas especialistas, representação do conhecimento, lógica e raciocínio, busca e otimização com restrições |
| Sinais de classificação | Regras, tabelas de decisão, ontologias ou modelos de otimização; nenhum parâmetro aprendido de dados |
| Quando usar | Intertravamentos, validações, conformidade normativa, roteamento, sequenciamento com restrições conhecidas |
| Pergunta decisiva | Quem escreve as regras e as exceções, e quem pode alterá-las? |
| Teste de sucesso | 100% dos casos da tabela de casos conhecidos corretos; comportamento definido e testado para entrada fora das regras |
| Controles obrigatórios | C1.1 regras e exceções versionadas com dono nomeado; C1.2 falha fechada para entrada não coberta |
| Sinais de alerta | Regra que só existe na cabeça de alguém; exceções tratadas "no caso a caso"; ninguém sabe quem altera |
| Moderação máxima | M3, com raio de ação aprovado; escrita em OT sempre atrás de gate humano por comando |

## 6. Camada 2 · Aprendizado de máquina

Entra quando existe padrão nos dados que é caro ou impossível de escrever como regra, e só se os dados representam a operação real.

| Atributo | Especificação |
| --- | --- |
| Definição | Modelos que aprendem padrões a partir de dados para prever, classificar ou agrupar |
| Componentes | Regimes: supervisionado, não supervisionado, por reforço. Tarefas: classificação, regressão, agrupamento, detecção de anomalia |
| Sinais de classificação | Parâmetros ajustados por treino; existência de conjunto de treino e de teste |
| Quando usar | Previsão de demanda, qualidade ou falha; detecção de anomalia em processo; segmentação |
| Pergunta decisiva | Os dados representam o trabalho que o modelo vai fazer, com turnos, lotes, sazonalidade e equipamentos reais? |
| Teste de sucesso | Ganho sobre baseline simples em dados separados, com métrica ponderada pelo custo de cada tipo de erro (falso positivo e falso negativo) |
| Controles obrigatórios | C2.1 representatividade dos dados documentada; C2.2 separação treino e teste sem vazamento; C2.3 métrica ligada ao custo do erro |
| Sinais de alerta | Acurácia alta em base desbalanceada; teste com dado do mesmo período do treino; nenhuma baseline |
| Moderação máxima | M2: propõe e aplica em sandbox; efeito em produção por lote aprovado |

## 7. Camada 3 · Redes neurais

É uma família dentro do aprendizado de máquina; ganha camada própria porque o objetivo de treino passa a decidir que erros o sistema tolera.

| Atributo | Especificação |
| --- | --- |
| Definição | Modelos compostos por unidades conectadas em camadas, treinados por minimização de uma função de custo |
| Componentes | Perceptrons, camadas ocultas, funções de ativação, funções de custo, retropropagação |
| Sinais de classificação | Arquitetura em camadas com pesos treinados por gradiente; menção a épocas, perda, otimizador |
| Quando usar | Relações não lineares em dados tabulares ou de sensor em que modelos mais simples ficaram abaixo da meta |
| Pergunta decisiva | Quais erros o objetivo de treino penaliza, e isso coincide com o resultado que o usuário precisa? |
| Teste de sucesso | Erro medido separadamente nos casos críticos (eventos raros, extremos), não só na média; ganho sobre modelo clássico da camada 2 |
| Controles obrigatórios | C3.1 objetivo de treino explicado em termos de negócio e revisado com o dono do processo |
| Sinais de alerta | Rede neural escolhida sem comparação com modelo mais simples; erro médio baixo escondendo falhas nos picos |
| Moderação máxima | M2 |

## 8. Camada 4 · Deep learning

É a camada da visão computacional, do áudio e das sequências longas; o risco típico é um modelo excelente em benchmark que não cabe na latência ou no hardware da operação.

| Atributo | Especificação |
| --- | --- |
| Definição | Redes neurais profundas com arquiteturas especializadas por tipo de dado |
| Componentes | CNNs (imagem), RNNs e LSTMs (sequência; LSTM é um tipo de RNN), Transformers (sequências longas e multimodal), autoencoders (compressão e anomalia) |
| Sinais de classificação | Arquitetura profunda nomeada; uso de GPU ou acelerador; dataset anotado de imagem, áudio ou sequência |
| Quando usar | Inspeção visual, contagem, OCR, classificação de grão ou defeito, séries longas de sensor |
| Pergunta decisiva | Por que esta arquitetura se encaixa nos seus dados e na sua tarefa? |
| Teste de sucesso | Acurácia, latência no p95 e custo por inferência medidos juntos no hardware alvo (borda ou servidor), com dados da própria planta |
| Controles obrigatórios | C4.1 medição no hardware alvo; C4.2 plano de drift, reteste e retreino ao mudar câmera, iluminação, matéria-prima ou condição de operação |
| Sinais de alerta | Benchmark apenas em dataset público; nenhuma menção a latência; dataset com vazamento entre treino e teste por similaridade de imagem |
| Moderação máxima | M2; a máquina detecta e propõe, o humano confirma |

## 9. Camada 5 · IA generativa

Produz conteúdo novo e, por isso, exige definir antes o que é uma saída útil; é a camada em que demonstração convincente mais engana.

| Atributo | Especificação |
| --- | --- |
| Definição | Modelos que geram texto, imagem, áudio, código ou combinações a partir de uma entrada |
| Componentes | LLMs, modelos de difusão, modelos de áudio e imagem, modelos multimodais, VAEs; recuperação de conhecimento (RAG) quando o conteúdo precisa de fonte |
| Sinais de classificação | Saída livre gerada por modelo; prompt, contexto ou base recuperada como entrada |
| Quando usar | Resumo e busca em documentação técnica, rascunho de relatório, atendimento de primeiro nível, extração de dados de documentos |
| Pergunta decisiva | Como é uma saída útil, e quem a confere antes que ela produza efeito? |
| Teste de sucesso | Conjunto de avaliação com casos reais do cliente; factualidade com citação de fonte, consistência entre execuções e recusa adequada fora do escopo |
| Controles obrigatórios | C5.1 conjunto de avaliação próprio; C5.2 factualidade com fonte; C5.3 ponto de revisão humana antes do efeito |
| Sinais de alerta | Avaliação só com exemplos escolhidos a dedo; resposta sem fonte em domínio técnico; nenhuma medição de consistência |
| Moderação máxima | M1 por padrão: gera em sandbox e o humano lê e aplica; M2 só para uso interno com evidência acumulada |

## 10. Camada 6 · IA agêntica

É a única camada que age no mundo por conta própria; por isso é definida tanto pelo que pode fazer quanto pelo que está proibido de fazer.

| Atributo | Especificação |
| --- | --- |
| Definição | Sistemas que combinam memória, planejamento e uso de ferramentas para executar passos em direção a um objetivo |
| Componentes | Memória, planejamento, agentes, uso de ferramentas, execução autônoma, orquestração multiagente |
| Sinais de classificação | Chamada a ferramenta ou API externa; execução em múltiplos passos sem intervenção a cada passo; escrita em sistema de terceiros |
| Quando usar | Tarefas de vários passos, repetitivas, com ações reversíveis e bem delimitadas; nunca como primeira opção quando um fluxo fixo resolve |
| Pergunta decisiva | Que ações o sistema pode executar sozinho, com quais ferramentas e com qual privilégio? |
| Teste de sucesso | Tarefa concluída corretamente, sem efeito colateral; medidos passos, custo por tarefa, ações não pretendidas e taxa de intervenção humana |
| Controles obrigatórios | C6.1 lista fechada de ferramentas com privilégio mínimo; C6.2 condições de parada e teto de custo; C6.3 aprovação humana para ação irreversível; C6.4 rollback e trilha auditável por passo; C6.5 nível de moderação declarado e gatilhos T1 a T8 em código |
| Sinais de alerta | "O agente decide sozinho" sem log nem limite de gasto; human-in-the-loop só na interface, ignorado pela API; agente de chat com escrita em sistema transacional sem confirmação por mensagem |
| Moderação máxima | M1 por padrão; M2 com gate humano por lote; M3 só com raio de ação aprovado, rollback provado e kill-switch. Não existe M4 |

## 11. Regras de classificação

A camada real é a mais alta cujo sinal de classificação está confirmado por evidência; a camada declarada só é registrada para comparação. Toda classificação produz três resultados: camada real, camadas usadas e camada mínima.

**Procedimento, sempre de cima para baixo.**

1. Há chamada a ferramenta externa, execução em múltiplos passos ou escrita em sistema de terceiros? Se sim, camada 6.
2. Há saída livre gerada por modelo? Se sim, camada 5.
3. Há arquitetura profunda especializada (CNN, RNN, Transformer, autoencoder)? Se sim, camada 4.
4. Há rede neural treinada por gradiente? Se sim, camada 3.
5. Há parâmetros ajustados por treino com dados? Se sim, camada 2.
6. Caso contrário, camada 1.

**Evidência aceita.** Documento técnico, código, arquitetura descrita ou demonstração observada. Afirmação comercial sem descrição técnica não confirma sinal.

**Camada mínima.** É a camada mais baixa que atenderia o teste de sucesso do trabalho descrito. Quando ela é inferior à camada real, o desvio é registrado com a justificativa apresentada; sem justificativa, vira condição no parecer.

**Registro de classificação.**

```json
{
  "camada_declarada": 6,
  "camada_real": 5,
  "camadas_usadas": [1, 4, 5],
  "camada_minima": 2,
  "evidencias": [{"sinal": "C5", "fonte": "proposta.pdf", "pagina": 7}],
  "desvio_justificado": false
}
```

## 12. Matriz camada × moderação

A autonomia permitida cai à medida que a camada sobe; nenhuma camada chega a M4, e qualquer promoção é decisão humana registrada.

| Camada | M0 Observador | M1 Propositor | M2 Executor assistido | M3 Executor escopado |
| --- | --- | --- | --- | --- |
| 1 Clássica | Livre | Livre | Livre | Com raio de ação aprovado |
| 2 Aprendizado de máquina | Livre | Livre | Com gate por lote | Proibido |
| 3 Redes neurais | Livre | Livre | Com gate por lote | Proibido |
| 4 Deep learning | Livre | Livre | Com gate por lote | Proibido |
| 5 Generativa | Livre | Padrão | Só uso interno, com evidência | Proibido |
| 6 Agêntica | Livre | Padrão | Com gate por lote | Exceção aprovada, rollback provado e kill-switch |

**Regras que valem em todas as linhas.**

- Moderação não declarada lê-se M0.
- Escrita em OT (PLC, SCADA, HMI, setpoint, receita, alarme) exige gate humano por comando, em qualquer camada e nível.
- Os gatilhos T1 a T8 rebaixam para M1 automaticamente e registram o código.
- A camada 1 admite M3 porque sua decisão é inteiramente auditável; isso não dispensa rollback nem dono.

## 13. Elementos transversais

Cinco elementos atravessam todas as camadas e são verificados no núcleo da avaliação (critérios N01 a N05) antes de qualquer critério de camada.

| Elemento | Exigência mínima | Critério |
| --- | --- | --- |
| Dados | Origem, período, dono e licença de uso documentados; qualidade marcada (boa, incerta, ruim) | Núcleo e C2.1 |
| Avaliação | Teste de sucesso com métrica e limiar definido antes da implantação; reavaliação periódica | N02 |
| Governança | Problema de negócio e decisão apoiada descritos; versão do sistema e da regra rastreável | N01 |
| Observabilidade | Log por execução com `trace_id`, entrada, saída, custo e latência; alerta de desvio | N04 e C6.4 |
| Dono humano | Pessoa nomeada que responde por falhas em produção e decide promoção de autonomia | N03 |

Custo total (licença, infraestrutura e operação) é exigido como N05 em toda avaliação, porque a camada mais alta quase sempre é a mais cara de operar.

## 14. Versionamento e governança do modelo

O modelo é versionado como código: a versão vigente é 1.0.0, e toda avaliação grava a versão do modelo e da rubrica que usou.

| Mudança | Versão | Exige |
| --- | --- | --- |
| Texto, exemplo ou sinal de alerta | Patch (1.0.x) | Revisão do dono do modelo |
| Novo critério, peso ou componente de camada | Menor (1.x.0) | Revisão por segundo engenheiro sênior e reprocessamento do conjunto ouro |
| Nova camada, mudança de regra de classificação ou da matriz de moderação | Maior (x.0.0) | Decisão registrada do dono do grupo e plano de migração das avaliações abertas |

**Regras.**

- Avaliação já selada nunca é recalculada com versão nova; uma reavaliação gera novo registro.
- O conjunto ouro (20 propostas anonimizadas) é reprocessado a cada versão menor ou maior, e a concordância com avaliadores humanos fica registrada.
- Os IDs de critério são estáveis: um critério removido é marcado como obsoleto, nunca reaproveitado.

**Decisões em aberto.**

- [ ] Dono do modelo de camadas: a confirmar.
- [ ] Periodicidade de revisão do modelo (proposta: semestral).
- [ ] Publicar o modelo como material do Programa ONDA ou mantê-lo de uso interno.
