import { useEffect, useRef, useState } from "react";

import type { Run, UserConfig } from "../api/client";
import { useMe, useRuns } from "../queries";
import { ViewHead } from "./Settings";

const TIER: Record<string, string> = { quick: "Rápido", default: "Padrão", complex: "Avançado" };
const MODE: Record<string, string> = { agent: "agente com ferramentas", direct: "direto", none: "sem arquivos" };

const STAGES: { icon: string; title: string; what: string; detail: string; cfg: (c: UserConfig) => string }[] = [
  { icon: "✉️", title: "Você envia", what: "Texto, foto ou arquivo entram na conversa.",
    detail: "A mensagem é gravada no servidor e ganha ✓. Quando o worker a recebe, vira ✓✓. Fotos são reduzidas e têm os metadados removidos antes de chegar ao agente.",
    cfg: (c) => `Confirmações de leitura: ${c.receipts ? "ligadas" : "desligadas"}` },
  { icon: "📥", title: "Leitura do arquivo", what: "PDF, Word e planilhas viram texto e tabelas.",
    detail: "O worker lê o arquivo no servidor: PDF por página, Word por seção (parágrafos e tabelas na ordem real), Excel e CSV como tabela com colunas. O texto é indexado para busca em português, sem depender de acento.",
    cfg: () => "Até 50 MB por arquivo" },
  { icon: "🧭", title: "Quem responde", what: "Em grupo, o app decide qual agente fala.",
    detail: "Na conversa individual responde o próprio agente. No grupo: @nome chama alguém específico; “pessoal” chama todos; sem isso, um modelo rápido escolhe o especialista pelo assunto.",
    cfg: (c) => (c.groupMode === "todos" ? "Grupos: todos respondem" : `Grupos: automático, até ${c.groupMax} por mensagem`) },
  { icon: "🧩", title: "Montagem do contexto", what: "Persona, histórico e lista de arquivos.",
    detail: "O agente recebe a personalidade, as regras de estilo, as últimas 30 mensagens e o catálogo dos arquivos (páginas, abas, colunas). Conteúdo de arquivo é tratado como dado, nunca como instrução.",
    cfg: (c) => `Modelo: ${TIER[c.tier]} · Respostas: ${c.length}` },
  { icon: "🔎", title: "Consulta aos dados", what: "O agente busca, lê e calcula antes de responder.",
    detail: "No modo agente ele trabalha em ciclos: lista os documentos, busca, abre as páginas relevantes e, em planilhas, filtra, agrupa e soma com os dados reais. Todas as ferramentas são só de leitura; nenhuma altera seus dados.",
    cfg: (c) => `Modo de leitura: ${MODE[c.readMode]}` },
  { icon: "💬", title: "Resposta", what: "Aparece ao vivo, com a fonte no rodapé.",
    detail: "Enquanto escreve aparece “digitando…” e sua mensagem fica ✓✓ azul. A resposta termina com as fontes, como “contrato.pdf p. 5”. O botão ■ interrompe.",
    cfg: (c) => `Etapas no balão: ${c.showSteps ? "sim" : "não"} · Fontes: ${c.showSources ? "sim" : "não"}` },
  { icon: "🔐", title: "Registro e auditoria", what: "Cada passo fica numa trilha à prova de adulteração.",
    detail: "Mensagens e confirmações nunca são editadas. Cada passo do agente entra numa trilha encadeada por SHA-256, calculada pelo banco, e a integridade é verificada abaixo.",
    cfg: () => "Isolamento por usuário garantido no banco" },
];

function secs(r: Run, at: string) {
  return `${((new Date(at).getTime() - new Date(r.queued_at).getTime()) / 1000).toFixed(1).replace(".", ",")} s`;
}
function eventText(e: Run["events"][number]): [string, string] {
  const p = e.payload as Record<string, unknown>;
  switch (e.kind) {
    case "started": return ["🤖", `${String(p.agente)} começou · ${String(p.modelo)} · modo ${MODE[String(p.modo)] ?? p.modo}`];
    case "routed": return ["🧭", `Escolha por ${String(p.motivo)}`];
    case "context": return ["🧩", `Arquivos no contexto: ${(p.arquivos as string[]).join(", ")}`];
    case "tool_call": return ["🔧", `Chamou ${String(p.ferramenta)}`];
    case "tool_result": return [p.ok ? "✅" : "⚠️", p.ok ? `${String(p.ferramenta)} respondeu` : `${String(p.ferramenta)}: ${String(p.erro)}`];
    case "answer": return ["💬", `Resposta pronta${(p.fontes as string[])?.length ? ` · fontes: ${(p.fontes as string[]).join("; ")}` : ""} · ${String(p.tokens)} tokens`];
    case "cancelled": return ["■", "Interrompida por você"];
    default: return ["⚠️", `Falhou: ${String(p.erro ?? "erro")}`];
  }
}

export function Flow() {
  const { data: me } = useMe();
  const { data: runs = [] } = useRuns();
  const [open, setOpen] = useState<number | null>(null);
  const [live, setLive] = useState<number | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined);
  useEffect(() => () => clearTimeout(timer.current), []);
  if (!me) return null;
  const play = () => {
    clearTimeout(timer.current);
    const step = (i: number) => {
      setLive(i < STAGES.length ? i : null);
      setOpen(i < STAGES.length ? i : null);
      if (i < STAGES.length) timer.current = setTimeout(() => step(i + 1), 2600);
    };
    step(0);
  };
  const last = runs[0];
  return (
    <>
      <ViewHead title="Fluxo" sub="O caminho de uma mensagem até a resposta" />
      <div className="view"><div className="vwrap">
        <div className="flowbar"><p className="muted">Toque numa etapa para ver os detalhes. Os destaques vêm da sua configuração atual.</p>
          <button className="btn" onClick={play}>Ver demonstração</button></div>
        <ol className="flow">
          {STAGES.map((s, i) => (
            <li key={s.title} className={`stage ${open === i ? "open" : ""} ${live === i ? "live" : ""} ${live !== null && i < live ? "done" : ""}`}>
              <button className="shead" aria-expanded={open === i} onClick={() => setOpen(open === i ? null : i)}>
                <span className="sic">{s.icon}</span><span className="stx"><b>{s.title}</b><small>{s.what}</small></span><span className="snum">{i + 1}</span>
              </button>
              {open === i && <div className="sbody"><p>{s.detail}</p><span className="scfg">{s.cfg(me.settings)}</span></div>}
            </li>
          ))}
        </ol>
        <section className="grp"><h3>Últimas respostas</h3>
          {!last && <p className="muted">Mande uma mensagem para um agente e volte aqui para ver cada etapa, com o tempo de cada uma.</p>}
          {runs.slice(0, 5).map((r) => (
            <details key={r.id} open={r.id === last?.id} className="runbox">
              <summary>
                <b>{r.agent_name}</b> em {r.conversation_title} · {new Date(r.queued_at).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" })}
                <span className={`badge ${r.chain_ok ? "ok" : "bad"}`}>{r.chain_ok ? "trilha íntegra" : "trilha adulterada"}</span>
              </summary>
              <ol className="trace">
                {r.events.map((e, i) => { const [ic, t] = eventText(e); return <li key={i}><span className="tt">{secs(r, e.at)}</span><span>{ic} {t}</span></li>; })}
              </ol>
              <p className="muted">{TIER[r.tier]} · {r.tool_calls} consulta(s) · {(r.input_tokens + r.output_tokens).toLocaleString("pt-BR")} tokens · {r.status}</p>
            </details>
          ))}
        </section>
      </div></div>
    </>
  );
}
