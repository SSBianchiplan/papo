"""Governança de IA no Papo: Modelo de Camadas (SPEC-GPS-CAMADAS-001 v1.0.0) e ficha de governança dos agentes.

A ficha vive no plano de controle: o agente lê, nunca escreve. O motor aplica a ficha em código — lista fechada de
ferramentas, moderação, condições de parada, canais — e registra cada gatilho (T1–T8) ou parada em governanca_evento.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from .db import row

MODELO_VERSAO = "1.0.0"

CAMADAS: list[dict[str, Any]] = [
    {"n": 1, "nome": "IA clássica", "definicao": "Decide a partir de conhecimento e regras explícitas, escritas por pessoas.",
     "componentes": "IA simbólica, sistemas especialistas, representação do conhecimento, lógica, busca e otimização com restrições",
     "sinais": "Regras, tabelas de decisão, ontologias ou otimização; nenhum parâmetro aprendido de dados",
     "quando": "Intertravamentos, validações, conformidade normativa, roteamento, sequenciamento com restrições conhecidas",
     "pergunta": "Quem escreve as regras e as exceções, e quem pode alterá-las?",
     "teste": "100% dos casos conhecidos corretos; comportamento definido e testado para entrada fora das regras",
     "controles": "C1.1 regras e exceções versionadas com dono; C1.2 falha fechada para entrada não coberta",
     "alerta": "Regra que só existe na cabeça de alguém; exceções no caso a caso; ninguém sabe quem altera",
     "moderacao": "M3 com raio de ação aprovado; escrita em OT sempre atrás de gate humano por comando"},
    {"n": 2, "nome": "Aprendizado de máquina", "definicao": "Modelos que aprendem padrões a partir de dados para prever, classificar ou agrupar.",
     "componentes": "Supervisionado, não supervisionado, por reforço; classificação, regressão, agrupamento, anomalia",
     "sinais": "Parâmetros ajustados por treino; conjunto de treino e de teste",
     "quando": "Previsão de demanda, qualidade ou falha; detecção de anomalia; segmentação",
     "pergunta": "Os dados representam o trabalho real, com turnos, lotes, sazonalidade e equipamentos?",
     "teste": "Ganho sobre baseline simples em dados separados, com métrica ponderada pelo custo de cada erro",
     "controles": "C2.1 representatividade documentada; C2.2 treino e teste sem vazamento; C2.3 métrica ligada ao custo do erro",
     "alerta": "Acurácia alta em base desbalanceada; teste no mesmo período do treino; nenhuma baseline",
     "moderacao": "M2: propõe e aplica em sandbox; efeito em produção por lote aprovado"},
    {"n": 3, "nome": "Redes neurais", "definicao": "Unidades conectadas em camadas, treinadas por minimização de uma função de custo.",
     "componentes": "Perceptrons, camadas ocultas, ativação, função de custo, retropropagação",
     "sinais": "Pesos treinados por gradiente; épocas, perda, otimizador",
     "quando": "Relações não lineares em dados tabulares ou de sensor em que modelos mais simples ficaram abaixo da meta",
     "pergunta": "Quais erros o objetivo de treino penaliza, e isso coincide com o resultado que o usuário precisa?",
     "teste": "Erro medido nos casos críticos (raros, extremos), não só na média; ganho sobre a camada 2",
     "controles": "C3.1 objetivo de treino explicado em termos de negócio e revisado com o dono do processo",
     "alerta": "Rede neural sem comparação com modelo mais simples; erro médio baixo escondendo falhas nos picos",
     "moderacao": "M2"},
    {"n": 4, "nome": "Deep learning", "definicao": "Redes profundas com arquiteturas especializadas por tipo de dado.",
     "componentes": "CNNs, RNNs e LSTMs, Transformers, autoencoders",
     "sinais": "Arquitetura profunda nomeada; GPU ou acelerador; dataset anotado de imagem, áudio ou sequência",
     "quando": "Inspeção visual, contagem, OCR, classificação de grão ou defeito, séries longas de sensor",
     "pergunta": "Por que esta arquitetura se encaixa nos seus dados e na sua tarefa?",
     "teste": "Acurácia, latência p95 e custo por inferência medidos juntos no hardware alvo, com dados da planta",
     "controles": "C4.1 medição no hardware alvo; C4.2 plano de drift, reteste e retreino",
     "alerta": "Benchmark só em dataset público; nenhuma menção a latência; vazamento entre treino e teste",
     "moderacao": "M2; a máquina detecta e propõe, o humano confirma"},
    {"n": 5, "nome": "IA generativa", "definicao": "Modelos que geram texto, imagem, áudio, código ou combinações a partir de uma entrada.",
     "componentes": "LLMs, difusão, áudio e imagem, multimodais, VAEs; RAG quando o conteúdo precisa de fonte",
     "sinais": "Saída livre gerada por modelo; prompt, contexto ou base recuperada como entrada",
     "quando": "Resumo e busca em documentação, rascunho de relatório, atendimento de primeiro nível, extração de documentos",
     "pergunta": "Como é uma saída útil, e quem a confere antes que ela produza efeito?",
     "teste": "Avaliação com casos reais; factualidade com fonte, consistência entre execuções e recusa fora do escopo",
     "controles": "C5.1 conjunto de avaliação próprio; C5.2 factualidade com fonte; C5.3 revisão humana antes do efeito",
     "alerta": "Avaliação com exemplos escolhidos a dedo; resposta sem fonte em domínio técnico; sem medir consistência",
     "moderacao": "M1 por padrão; M2 só para uso interno com evidência acumulada"},
    {"n": 6, "nome": "IA agêntica", "definicao": "Combina memória, planejamento e ferramentas para executar passos em direção a um objetivo.",
     "componentes": "Memória, planejamento, agentes, ferramentas, execução autônoma, orquestração multiagente",
     "sinais": "Chamada a ferramenta ou API; vários passos sem intervenção a cada passo; escrita em sistema de terceiros",
     "quando": "Tarefas de vários passos, repetitivas, reversíveis e delimitadas; nunca a primeira opção quando um fluxo fixo resolve",
     "pergunta": "Que ações o sistema pode executar sozinho, com quais ferramentas e com qual privilégio?",
     "teste": "Tarefa correta sem efeito colateral; passos, custo, ações não pretendidas e intervenção humana medidos",
     "controles": "C6.1 ferramentas em lista fechada; C6.2 parada e teto de custo; C6.3 aprovação humana para irreversível; "
                  "C6.4 rollback e trilha por passo; C6.5 moderação declarada e gatilhos T1–T8 em código",
     "alerta": "'O agente decide sozinho' sem log nem limite; humano só na interface; escrita transacional sem confirmação",
     "moderacao": "M1 por padrão; M2 com gate por lote; M3 só com raio aprovado, rollback provado e kill-switch. Não existe M4"},
]
MATRIZ = {  # camada → nível → permissão (CAMADAS-001 §12)
    1: {"M0": "Livre", "M1": "Livre", "M2": "Livre", "M3": "Com raio de ação aprovado"},
    2: {"M0": "Livre", "M1": "Livre", "M2": "Com gate por lote", "M3": "Proibido"},
    3: {"M0": "Livre", "M1": "Livre", "M2": "Com gate por lote", "M3": "Proibido"},
    4: {"M0": "Livre", "M1": "Livre", "M2": "Com gate por lote", "M3": "Proibido"},
    5: {"M0": "Livre", "M1": "Padrão", "M2": "Só uso interno, com evidência", "M3": "Proibido"},
    6: {"M0": "Livre", "M1": "Padrão", "M2": "Com gate por lote", "M3": "Exceção aprovada, rollback provado e kill-switch"},
}
NIVEIS = {"M0": "Observador: lê, analisa, diagnostica; nenhuma escrita",
          "M1": "Propositor: gera artefato em sandbox; o humano lê e aplica",
          "M2": "Executor assistido: aplica em sandbox; produção por lote aprovado",
          "M3": "Executor escopado: dentro do raio aprovado, com rollback e kill-switch"}
GATILHOS = {"T1": "Gauntlet com FAIL ou HOLE", "T2": "Toca invariante, CHECK, trigger ou trilha de auditoria",
            "T3": "Escreve em OT (PLC, SCADA, HMI, setpoint, receita, alarme)", "T4": "Move dado de produção, pessoal ou credencial",
            "T5": "Ação irreversível ou rollback não provado", "T6": "Spec ou rubrica ambígua ou silenciosa",
            "T7": "Estoura o orçamento (custo, passos ou tempo)", "T8": "Precisa sair do raio de ação"}
TRANSVERSAIS = [
    {"elemento": "Dados", "exigencia": "Origem, período, dono e licença documentados; qualidade marcada", "criterio": "Núcleo e C2.1"},
    {"elemento": "Avaliação", "exigencia": "Teste de sucesso com métrica e limiar antes da implantação; reavaliação periódica", "criterio": "N02"},
    {"elemento": "Governança", "exigencia": "Problema de negócio e decisão apoiada descritos; versão rastreável", "criterio": "N01"},
    {"elemento": "Observabilidade", "exigencia": "Log por execução com trace_id, entrada, saída, custo e latência", "criterio": "N04 e C6.4"},
    {"elemento": "Dono humano", "exigencia": "Pessoa nomeada que responde por falhas e decide promoção de autonomia", "criterio": "N03"},
]
WRITE_TYPES = {"escrita", "escrita_propria"}


def camadas_prompt() -> str:
    """Resumo do modelo para o contexto de um agente (quando ligado na ficha ou na conversa)."""
    linhas = [f"Camada {c['n']} · {c['nome']}: {c['definicao']} Sinais: {c['sinais']}. Pergunta decisiva: {c['pergunta']} "
              f"Moderação máxima: {c['moderacao']}." for c in CAMADAS]
    return ("Você conhece o Modelo de Camadas da IA do GPlanSiS (SPEC-GPS-CAMADAS-001 v1.0.0). Camada não é mérito: a certa é a mínima "
            "que resolve o trabalho com a evidência disponível; a camada real é a mais alta com sinal confirmado, não a declarada. "
            "Classifique de cima para baixo: ferramenta externa ou vários passos = 6; saída livre gerada = 5; arquitetura profunda = 4; "
            "rede neural treinada = 3; parâmetros treinados com dados = 2; senão 1. A IA propõe, o humano decide; não existe M4.\n"
            + "\n".join(linhas))


@dataclass
class Ficha:
    agent_id: UUID
    dono: str = ""
    camada_real: int | None = None
    nivel: str = "M0"
    ferramentas: list[dict[str, str]] = field(default_factory=list)
    max_iteracoes: int = 8
    max_custo_conversa_usd: float = 2.0
    max_segundos_turno: int = 180
    gatilhos: list[str] = field(default_factory=list)
    canais: list[str] = field(default_factory=lambda: ["direto"])
    camadas_no_contexto: bool = False
    ativo: bool = False
    versao: int = 0

    def allows(self, tool: str) -> bool:
        """Lista fechada (C6.1) + moderação: M0 não recebe ferramenta de escrita, mesmo listada."""
        t = next((f for f in self.ferramentas if f.get("nome") == tool), None)
        if t is None:
            return False
        return not (self.nivel == "M0" and t.get("tipo") in WRITE_TYPES)


async def load_ficha(conn: AsyncConnection, agent_id: UUID) -> Ficha:
    r = await row(conn, "SELECT * FROM agent_ficha WHERE agent_id = :a", a=agent_id)
    if not r:
        return Ficha(agent_id=agent_id)                               # sem ficha: M0 e inativo
    return Ficha(agent_id=agent_id, dono=r["dono"], camada_real=r["camada_real"], nivel=r["nivel"], ferramentas=list(r["ferramentas"] or []),
                 max_iteracoes=r["max_iteracoes"] or 8, max_custo_conversa_usd=float(r["max_custo_conversa_usd"] or 2),
                 max_segundos_turno=r["max_segundos_turno"] or 180, gatilhos=list(r["gatilhos"] or []), canais=list(r["canais"] or []),
                 camadas_no_contexto=r["camadas_no_contexto"], ativo=r["ativo"], versao=r["versao"])


async def evento(conn: AsyncConnection, owner: UUID, codigo: str, detalhe: str, *, agent_id: UUID | None = None,
                 conversation_id: UUID | None = None, run_id: UUID | None = None, antes: str | None = None, depois: str | None = None) -> None:
    await conn.execute(text("""INSERT INTO governanca_evento (owner_id, agent_id, conversation_id, run_id, codigo, detalhe, nivel_antes, nivel_depois)
                               VALUES (:o, :a, :c, :r, :k, :d, :na, :nd)"""),
                       {"o": owner, "a": agent_id, "c": conversation_id, "r": run_id, "k": codigo, "d": detalhe[:500], "na": antes,
                        "nd": depois})


async def conversation_features(conn: AsyncConnection, conversation_id: UUID) -> dict[str, bool]:
    r = await row(conn, "SELECT camadas, consultor FROM conversation_feature WHERE conversation_id = :c", c=conversation_id)
    return {"camadas": bool(r and r["camadas"]), "consultor": bool(r and r["consultor"])}


async def conversation_cost_usd(conn: AsyncConnection, conversation_id: UUID) -> float:
    """Custo estimado de IA já gasto nesta conversa (para a condição de parada da ficha)."""
    from . import costs

    prices = await costs.load_prices(conn)
    rs = await conn.execute(text("""SELECT u.model, sum(u.input_tokens) AS i, sum(u.output_tokens) AS o FROM usage_event u
                                     JOIN agent_run r ON r.id = u.run_id WHERE r.conversation_id = :c GROUP BY u.model"""), {"c": conversation_id})
    return sum(costs.cost_usd(m, int(i), int(o), prices) for m, i, o in rs.all())


async def disparar(conn: AsyncConnection, owner: UUID, ficha: Ficha, codigo: str, detalhe: str, *,
                   conversation_id: UUID | None = None, run_id: UUID | None = None) -> str:
    """Registra gatilho ou parada. Gatilho aplicável a um agente acima de M1 rebaixa a ficha para M1 (decisão do sistema,
    registrada; promoção de volta só por pessoa). Devolve o nível em vigor depois."""
    antes = ficha.nivel
    if codigo in ficha.gatilhos and antes in ("M2", "M3"):
        await conn.execute(text("UPDATE agent_ficha SET nivel = 'M1', decidido_por = NULL WHERE agent_id = :a"), {"a": ficha.agent_id})
        ficha.nivel = "M1"
    await evento(conn, owner, codigo, detalhe, agent_id=ficha.agent_id, conversation_id=conversation_id, run_id=run_id,
                 antes=antes, depois=ficha.nivel)
    return ficha.nivel
