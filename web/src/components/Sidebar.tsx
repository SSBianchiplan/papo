import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";

import { api, ok, type Agent, type Conversation } from "../api/client";
import { openDm, useAgents, useConversations, useMe } from "../queries";
import { liveFor, useApp, type LiveRun } from "../store";
import { ConversaGovernanca } from "./Governanca";
import { ConversationSkills } from "./Skills";
import { Avatar, ContextMenu, hhmm, Modal, Icon, listTime, Ticks, useContextTrigger, type MenuItem, type MenuState } from "./ui";

// Fixar no topo é preferência deste navegador (não vai para o servidor).
const PIN_KEY = "papo.pinned";
function readPins(): string[] {
  try { return JSON.parse(localStorage.getItem(PIN_KEY) ?? "[]") as string[]; } catch { return []; }
}
function writePins(ids: string[]): void {
  try { localStorage.setItem(PIN_KEY, JSON.stringify(ids)); } catch { /* armazenamento indisponível: fixar só vale nesta sessão */ }
}

async function exportConversation(c: Conversation, name: string): Promise<void> {
  const ms = await ok(api.GET("/api/conversations/{cid}/messages", { params: { path: { cid: c.id }, query: { limit: 200 } } }));
  const lines = ms.map((m) => {
    const who = m.author === "user" ? "Você" : m.author === "system" ? "Sistema" : (m.agent_name ?? "Agente");
    const when = `${new Date(m.created_at).toLocaleDateString("pt-BR")} ${hhmm(m.created_at)}`;
    const extra = [m.document ? `[arquivo: ${m.document.filename}]` : "", m.image_key ? "[imagem]" : "", m.error ? `[erro: ${m.error}]` : "",
      m.sources.length ? `(com base em ${m.sources.join(", ")})` : ""].filter(Boolean).join(" ");
    return `[${when}] ${who}: ${m.body}${extra ? ` ${extra}` : ""}`;
  });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([`Conversa: ${name}\n\n${lines.join("\n")}\n`], { type: "text/plain;charset=utf-8" }));
  a.download = `papo-${name.toLowerCase().replace(/[^a-z0-9]+/gi, "-")}.txt`;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 5000);
}

type Filter = "todas" | "fixadas" | "grupos" | "agentes";
const FILTERS: [Filter, string][] = [["todas", "Todas"], ["fixadas", "Fixadas"], ["grupos", "Grupos"], ["agentes", "Agentes"]];

export function title(c: Conversation, agents: Agent[]): string {
  return c.kind === "group" ? (c.name ?? "Grupo") : (agents.find((a) => a.id === c.agent_id)?.name ?? "Agente");
}
export function avatarOf(c: Conversation, agents: Agent[]) {
  if (c.kind === "group") return { emoji: c.emoji, color: c.color };
  const a = agents.find((x) => x.id === c.agent_id);
  return { emoji: a?.emoji ?? "❔", color: a?.color ?? "#888" };
}

function preview(c: Conversation): string {
  const m = c.last_message;
  if (!m) return "";
  let t = m.body || (m.image_key ? "📷 Foto" : m.document ? `📄 ${m.document.filename}` : m.error ?? "");
  if (m.image_key && m.body) t = `📷 ${m.body}`;
  if (c.kind === "group" && m.author === "agent") t = `${m.agent_name}: ${t}`;
  return t;
}

function ConvItem({ c, agents, on, live, typingOn, receipts, pinned, openMenu }: {
  c: Conversation; agents: Agent[]; on: boolean; live: LiveRun | undefined; typingOn: boolean; receipts: boolean; pinned: boolean;
  openMenu: (c: Conversation, x: number, y: number) => void;
}) {
  const setView = useApp((s) => s.setView);
  const trigger = useContextTrigger((x, y) => openMenu(c, x, y));
  const av = avatarOf(c, agents);
  const last = c.last_message;
  return (
    <button className={`item ${on ? "on" : ""}`} onClick={() => setView({ kind: "chat", id: c.id })} {...trigger}
      aria-label={`${title(c, agents)}. Clique direito para mais opções`}>
      <Avatar {...av} />
      <div className="meta">
        <div className="row"><span className="name">{title(c, agents)}{c.kind === "dm" && agents.find((x) => x.id === c.agent_id)?.ativo === false && <span className="tag off">desativado</span>}</span>
          <span className="time">{listTime(c.last_activity_at)}</span></div>
        <div className="prev">
          {live && typingOn ? (
            <span className="typing">{c.kind === "group" ? `${live.agentName} está digitando…` : "digitando…"}</span>
          ) : (
            <>
              {receipts && last?.author === "user" && <Ticks status={last.status} />}
              <span className="ellip">{preview(c)}</span>
            </>
          )}
          {pinned && <span className="pin" aria-label="fixada"><Icon.pin /></span>}
        </div>
      </div>
    </button>
  );
}

function AgentItem({ a, start, openMenu }: { a: Agent; start: (a: Agent) => void; openMenu: (a: Agent, x: number, y: number) => void }) {
  const trigger = useContextTrigger((x, y) => openMenu(a, x, y));
  return (
    <button className="item" onClick={() => start(a)} {...trigger}>
      <Avatar emoji={a.emoji} color={a.color} small />
      <div className="meta"><div className="name">{a.name}</div><div className="prev ellip">{a.persona.slice(0, 70)}</div></div>
    </button>
  );
}

export function Sidebar() {
  const { data: convs = [] } = useConversations();
  const { data: agents = [] } = useAgents();
  const { data: me } = useMe();
  const qc = useQueryClient();
  const { view, setView, setDialog, runs, online, notify, convMenu: menuReq, openConvMenu } = useApp();
  const [q, setQ] = useState("");
  const [filter, setFilter] = useState<Filter>("todas");
  const [pins, setPins] = useState<string[]>(readPins);
  const [menu, setMenu] = useState<MenuState>(null);
  const [skillsFor, setSkillsFor] = useState<{ id: string; title: string } | null>(null);
  const [govFor, setGovFor] = useState<{ id: string; title: string } | null>(null);
  const closeMenu = useCallback(() => setMenu(null), []);
  const typingOn = me?.settings.typing ?? true;
  const receipts = me?.settings.receipts ?? true;

  const list = useMemo(() => convs
    .filter((c) => !q || title(c, agents).toLowerCase().includes(q.toLowerCase()))
    .filter((c) => filter === "todas" || (filter === "fixadas" ? pins.includes(c.id) : filter === "grupos" ? c.kind === "group" : c.kind === "dm"))
    .sort((a, b) => Number(pins.includes(b.id)) - Number(pins.includes(a.id))), [convs, agents, q, pins]);
  const withDm = new Set(convs.filter((c) => c.kind === "dm").map((c) => c.agent_id));
  const contacts = filter === "todas" || filter === "agentes"
    ? agents.filter((a) => !withDm.has(a.id) && (!q || a.name.toLowerCase().includes(q.toLowerCase()))) : [];
  const current = view.kind === "chat" ? view.id : null;

  const start = async (a: Agent) => {
    try {
      const c = await openDm(a.id);
      setView({ kind: "chat", id: c.id });
    } catch (e) {
      notify((e as Error).message);
    }
  };
  const togglePin = (id: string) => setPins((p) => { const n = p.includes(id) ? p.filter((x) => x !== id) : [id, ...p]; writePins(n); return n; });
  const refresh = () => { void qc.invalidateQueries({ queryKey: ["conversations"] }); void qc.invalidateQueries({ queryKey: ["agents"] }); };

  const convMenu = (c: Conversation, x: number, y: number) => {
    const name = title(c, agents);
    const items: MenuItem[] = [
      { icon: "💬", label: "Abrir conversa", onSelect: () => setView({ kind: "chat", id: c.id }) },
      { icon: "📌", label: pins.includes(c.id) ? "Desafixar" : "Fixar no topo", onSelect: () => togglePin(c.id) },
      c.kind === "group"
        ? { icon: "✏️", label: "Editar grupo e membros", onSelect: () => setDialog({ kind: "group", id: c.id }) }
        : { icon: "✏️", label: "Editar agente e base de arquivos", onSelect: () => setDialog({ kind: "agent", id: c.agent_id ?? undefined }) },
      { icon: "📘", label: "Skills desta conversa…", onSelect: () => setSkillsFor({ id: c.id, title: name }) },
      { icon: "🧭", label: "Governança desta conversa…", onSelect: () => setGovFor({ id: c.id, title: name }) },
      { icon: "⬇️", label: "Exportar conversa (.txt)", onSelect: () => void exportConversation(c, name).catch((e: Error) => notify(e.message)) },
      { icon: "📋", label: "Copiar nome", onSelect: () => void navigator.clipboard?.writeText(name).then(() => notify("Nome copiado.")) },
      "sep",
      { icon: "🗑️", label: c.kind === "group" ? "Apagar grupo" : "Apagar conversa", danger: true, onSelect: async () => {
        if (!confirm(`Apagar "${name}" com todas as mensagens e anexos? Não há como desfazer.${c.kind === "dm" ? " O agente continua existindo." : ""}`)) return;
        try {
          await ok(api.DELETE("/api/conversations/{cid}", { params: { path: { cid: c.id } } }));
          if (current === c.id) setView({ kind: "welcome" });
          if (pins.includes(c.id)) togglePin(c.id);
          refresh();
          notify("Conversa apagada.");
        } catch (e) { notify((e as Error).message); }
      } },
    ];
    setMenu({ x, y, items });
  };
  useEffect(() => {
    if (!menuReq) return;
    const c = convs.find((x) => x.id === menuReq.id);
    if (c) convMenu(c, menuReq.x, menuReq.y);
    openConvMenu(null);
  }, [menuReq]);   // eslint-disable-line react-hooks/exhaustive-deps
  const agentMenu = (a: Agent, x: number, y: number) => setMenu({ x, y, items: [
    { icon: "💬", label: "Conversar", onSelect: () => void start(a) },
    { icon: "✏️", label: "Editar agente e base de arquivos", onSelect: () => setDialog({ kind: "agent", id: a.id }) },
    { icon: "🧭", label: "Ficha de governança", onSelect: () => setView({ kind: "settings", tab: "governanca" }) },
    "sep",
    { icon: "🗑️", label: "Excluir agente", danger: true, onSelect: async () => {
      if (!confirm(`Excluir o agente "${a.name}" e a base de arquivos dele? Não há como desfazer.`)) return;
      try { await ok(api.DELETE("/api/agents/{agent_id}", { params: { path: { agent_id: a.id } } })); refresh(); notify("Agente excluído."); }
      catch (e) { notify((e as Error).message); }
    } },
  ] });

  return (
    <aside className="side">
      <div className="lhead">
        <div className="lbar">
          <button className="fab" aria-label="Mais opções" title="Mais opções" onClick={(e) => { const r = e.currentTarget.getBoundingClientRect(); setMenu({ x: r.left, y: r.bottom + 6, items: [
            { icon: "➕", label: "Novo agente", onSelect: () => setDialog({ kind: "agent" }) },
            { icon: "👥", label: "Novo grupo", onSelect: () => (agents.length ? setDialog({ kind: "group" }) : notify("Crie um agente antes de montar um grupo.")) },
            "sep",
            { icon: "📁", label: "Arquivos", onSelect: () => setView({ kind: "files" }) },
            { icon: "🧭", label: "Fluxo: como funciona", onSelect: () => setView({ kind: "flow" }) },
            { icon: "⚙️", label: "Configuração", onSelect: () => setView({ kind: "settings" }) },
          ] }); }}><Icon.dots /></button>
          <span className="brand">Papo</span>
          <button className="fab" aria-label="Novo grupo" title="Novo grupo"
            onClick={() => (agents.length ? setDialog({ kind: "group" }) : notify("Crie um agente antes de montar um grupo."))}><Icon.group /></button>
          <button className="fab primary" aria-label="Novo agente" title="Novo agente" onClick={() => setDialog({ kind: "agent" })}><Icon.plus /></button>
        </div>
        <h1>Conversas</h1>
        <label className="search"><Icon.search /><input type="search" placeholder="Pesquisar conversa ou agente" aria-label="Pesquisar" value={q} onChange={(e) => setQ(e.target.value)} /></label>
        <div className="chips" role="tablist" aria-label="Filtro">
          {FILTERS.map(([k, label]) => (
            <button key={k} role="tab" aria-selected={filter === k} className={filter === k ? "on" : ""} onClick={() => setFilter(k)}>
              {label}{k === "fixadas" && pins.length > 0 && <small>{pins.filter((id) => convs.some((c) => c.id === id)).length}</small>}
            </button>
          ))}
        </div>
      </div>
      {!online && <div className="banner">Reconectando ao servidor…</div>}
      <div className="list">
        {list.map((c) => (
          <ConvItem key={c.id} c={c} agents={agents} on={current === c.id} live={liveFor(runs, c.id)[0]} typingOn={typingOn} receipts={receipts}
            pinned={pins.includes(c.id)} openMenu={convMenu} />
        ))}
        {contacts.length > 0 && <div className="sublabel">Agentes sem conversa</div>}
        {contacts.map((a) => <AgentItem key={a.id} a={a} start={(x) => void start(x)} openMenu={agentMenu} />)}
        {!list.length && !contacts.length && (
          <div className="empty-list">{q || filter !== "todas" ? "Nada por aqui." : <>Nenhuma conversa ainda.<br /><button className="btn" onClick={() => setDialog({ kind: "agent" })}>Criar agente</button></>}</div>
        )}
      </div>
      {createPortal(<>
      <ContextMenu menu={menu} onClose={closeMenu} />
      {skillsFor && <ConversationSkills id={skillsFor.id} title={skillsFor.title} onClose={() => setSkillsFor(null)} />}
      {govFor && <Modal title={`Governança · ${govFor.title}`} onClose={() => setGovFor(null)}
        footer={<><span className="muted">Fichas dos agentes: Configuração → Governança de IA</span>
          <button className="btn ghost" onClick={() => { setGovFor(null); setView({ kind: "settings", tab: "governanca" }); }}>Abrir governança</button></>}>
        <ConversaGovernanca id={govFor.id} /></Modal>}
      </>, document.body)}
    </aside>
  );
}
