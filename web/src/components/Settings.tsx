import { useEffect, useState } from "react";

import { api, downloadExport, ok, type UserConfig } from "../api/client";
import { logout } from "../auth";
import { useMe, useSettings } from "../queries";
import { useApp } from "../store";
import { AccountsPanel } from "./Accounts";
import { AdminPanel, UsagePanel } from "./Costs";
import { HubDocsSection } from "./HubDocs";
import { SkillsSection } from "./Skills";
import { GovernancaTab } from "./Governanca";
import { SystemFlowSection } from "./SystemFlow";
import { Icon } from "./ui";

type Opt<K extends keyof UserConfig> = [UserConfig[K], string];

export function ViewHead({ title, sub }: { title: string; sub: string }) {
  const setView = useApp((s) => s.setView);
  return (
    <div className="top vhead">
      <button className="iconbtn back" aria-label="Voltar" onClick={() => setView({ kind: "welcome" })}><Icon.back /></button>
      <div className="t"><div className="tn">{title}</div><div className="sub">{sub}</div></div>
    </div>
  );
}

const TAB_KEY = "papo.settingsTab";
const TAB_ICON: Record<string, string> = { geral: "⚙️", ia: "🤖", governanca: "🧭", usuarios: "👥", admin: "🔐", sistema: "🛰️" };
const readTab = () => { try { return localStorage.getItem(TAB_KEY) ?? "geral"; } catch { return "geral"; } };

export function Settings() {
  const { data: me } = useMe();
  const view = useApp((s) => s.view);
  const [tab, setTab] = useState(() => (view.kind === "settings" && view.tab) || readTab());
  useEffect(() => { if (view.kind === "settings" && view.tab) setTab(view.tab); }, [view]);
  const save = useSettings();
  const notify = useApp((s) => s.notify);
  if (!me) return null;
  const cfg = me.settings;
  const set = <K extends keyof UserConfig>(k: K, v: UserConfig[K]) => save.mutate({ ...cfg, [k]: v });

  function Seg<K extends keyof UserConfig>({ k, opts }: { k: K; opts: Opt<K>[] }) {
    return (
      <div className="seg" role="radiogroup">
        {opts.map(([v, l]) => <button key={String(v)} type="button" role="radio" aria-checked={cfg[k] === v} onClick={() => set(k, v)}>{l}</button>)}
      </div>
    );
  }
  function Sw({ k, label, hint }: { k: "showSteps" | "showSources" | "receipts" | "typing" | "enterSend"; label: string; hint: string }) {
    return (
      <label className="sw"><span><b>{label}</b><small>{hint}</small></span>
        <input type="checkbox" checked={cfg[k] ?? true} onChange={(e) => set(k, e.target.checked)} /><i aria-hidden /></label>
    );
  }

  const wipe = async () => {
    if (!confirm("Excluir sua conta, agentes, conversas e arquivos? Não há como desfazer.")) return;
    if (prompt("Para confirmar, digite EXCLUIR") !== "EXCLUIR") return;
    try {
      await ok(api.DELETE("/api/me"));
      await logout();
    } catch (e) {
      notify((e as Error).message);
    }
  };

  const tabs: [string, string][] = [["geral", "Geral"], ["ia", "Agentes e IA"], ["governanca", "Governança de IA"],
    ...(me.is_admin ? [["usuarios", "Usuários"], ["admin", "Administração"], ["sistema", "Sistema"]] as [string, string][] : [])];
  const current = tabs.some(([k]) => k === tab) ? tab : "geral";
  const choose = (k: string) => { setTab(k); try { localStorage.setItem(TAB_KEY, k); } catch { /* sem armazenamento: só nesta sessão */ } };

  return (
    <>
      <ViewHead title="Configuração" sub="Como os agentes leem, respondem e aparecem" />
      <nav className="tabs" role="tablist" aria-label="Seções da configuração">
        {tabs.map(([k, l]) => <button key={k} role="tab" aria-selected={current === k} className={current === k ? "on" : ""}
          ref={current === k ? (el) => el?.scrollIntoView({ block: "nearest", inline: "center" }) : undefined}
          onClick={() => choose(k)}><span aria-hidden>{TAB_ICON[k]}</span>{l}</button>)}
      </nav>
      <div className="view"><div className="vwrap">
        {current === "ia" && <><SkillsSection /><HubDocsSection /><UsagePanel /></>}
        {current === "governanca" && <GovernancaTab />}
        {current === "usuarios" && me.is_admin && <AccountsPanel />}
        {current === "admin" && me.is_admin && <AdminPanel />}
        {current === "sistema" && me.is_admin && <SystemFlowSection />}
        {current === "geral" && <>
        <section className="grp"><h3>Agentes</h3>
          <div className="opt"><div><b>Modelo</b><small>Rápido responde quase na hora. Avançado pensa mais e é melhor em análises difíceis.</small>
            {me.tiers && <small className="tier-models">Rápido: {me.tiers.quick} · Padrão: {me.tiers.default} · Avançado: {me.tiers.complex}</small>}</div>
            <Seg k="tier" opts={[["quick", "Rápido"], ["default", "Padrão"], ["complex", "Avançado"]]} /></div>
          <div className="opt"><div><b>Tamanho das respostas</b></div><Seg k="length" opts={[["curta", "Curta"], ["media", "Média"], ["detalhada", "Detalhada"]]} /></div>
        </section>
        <section className="grp"><h3>Leitura de arquivos e dados</h3>
          <div className="opt"><div><b>Modo de leitura</b><small>No modo agente, ele busca, abre só as páginas necessárias e calcula sobre as planilhas. No modo direto, o conteúdo vai junto com a pergunta: mais rápido, limitado a arquivos menores e sem cálculos exatos.</small></div>
            <Seg k="readMode" opts={[["agent", "Agente"], ["direct", "Direto"]]} /></div>
          <Sw k="showSteps" label="Mostrar etapas da leitura" hint="Exibe no balão o que o agente buscou, leu e calculou." />
          <Sw k="showSources" label="Mostrar fontes" hint="Rodapé com documento e página usados na resposta." />
        </section>
        <section className="grp"><h3>Grupos</h3>
          <div className="opt"><div><b>Quem responde</b><small>Automático escolhe pelo assunto. @nome sempre chama alguém específico.</small></div>
            <Seg k="groupMode" opts={[["auto", "Automático"], ["todos", "Todos"]]} /></div>
          {cfg.groupMode !== "todos" && <div className="opt"><div><b>Máximo de respostas por mensagem</b></div><Seg k="groupMax" opts={[[1, "1"], [2, "2"], [3, "3"]]} /></div>}
        </section>
        <section className="grp"><h3>Conversa</h3>
          <Sw k="receipts" label="Confirmações de leitura" hint="Mostra ✓ enviado, ✓✓ entregue e ✓✓ azul lido." />
          <Sw k="typing" label="Mostrar “digitando…”" hint="Indicador enquanto o agente escreve." />
          <Sw k="enterSend" label="Enter envia a mensagem" hint="No computador. Shift+Enter quebra linha." />
        </section>
        <section className="grp"><h3>Aparência</h3>
          <div className="opt"><div><b>Tema</b></div><Seg k="theme" opts={[["system", "Sistema"], ["light", "Claro"], ["dark", "Escuro"]]} /></div>
          <div className="opt"><div><b>Tamanho do texto</b></div><Seg k="fontSize" opts={[[14, "A-"], [15, "A"], [17, "A+"]]} /></div>
        </section>
        <section className="grp"><h3>Conta e dados</h3>
          <p className="muted">{me.name || me.email}{me.email && me.name ? ` · ${me.email}` : ""}</p>
          <div className="kbact">
            <button className="btn ghost" onClick={() => downloadExport().catch((e: Error) => notify(e.message))}>Exportar meus dados</button>
            <button className="btn ghost" onClick={() => void logout()}>Sair</button>
          </div>
          <button className="btn danger" onClick={() => void wipe()}>Excluir conta e todos os dados</button>
        </section>
        </>}
      </div></div>
    </>
  );
}
