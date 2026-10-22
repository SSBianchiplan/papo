import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";

import { api, downloadDocument, ok, upload, type Conversation, type Doc, type Message, type S } from "../api/client";
import { importSkillFiles, importSummary, isSkillFile } from "./Skills";
import { formatMessage } from "../format";
import { MessageCard } from "./Cards";
import { canPreview, Preview } from "./Files";
import { cancelRun, useAgents, useConversations, useMe, useMessages, useSend } from "../queries";
import { liveFor, useApp, type LiveRun } from "../store";
import { avatarOf, title } from "./Sidebar";
import { AuthImage, Avatar, ContextMenu, dayLabel, hhmm, Icon, isMobile, kb, Ticks, useContextTrigger, type MenuState } from "./ui";

type Pending = { kind: "image"; key: string; preview: string; name: string } | { kind: "document"; doc: Doc; name: string } | { kind: "uploading"; name: string };

function DocCard({ doc }: { doc: Doc }) {
  const live = useApp((s) => s.docStatus[doc.id]);
  const notify = useApp((s) => s.notify);
  const [preview, setPreview] = useState(false);
  const status = live ?? doc.status;
  const info = doc.kind === "pdf" ? `${doc.pages ?? doc.parts} pág.` : doc.sheets.length ? doc.sheets.map((s) => `${s.stored_rows} linhas`).join(" + ") : doc.parts ? `${doc.parts} seç.` : "";
  const ext = (doc.filename.split(".").pop() ?? "ARQ").slice(0, 4).toUpperCase();
  const bad = status === "failed" || status === "unreadable";
  return (
    <div className={`file ${doc.purged ? "gone" : ""}`}>
      <div className="ic">{ext}</div>
      <div className="fbody">
        <div className="fn">{doc.filename}</div>
        <div className="fs">{doc.purged ? "arquivo removido para liberar espaço" : [kb(doc.size_bytes), status === "pending" ? "lendo…" : info, doc.origin === "agent" ? "gerado" : ""].filter(Boolean).join(" · ")}</div>
        {!doc.purged && bad && <div className="fs warn">{doc.note ?? "Não foi possível ler o arquivo."}</div>}
        {!doc.purged && status !== "pending" && (
          <div className="fact">
            {canPreview(doc.filename) && <button type="button" onClick={() => setPreview(true)}>Ver</button>}
            <button type="button" onClick={() => void downloadDocument(doc.id, doc.filename).catch((e: Error) => notify(e.message))}>Baixar</button>
          </div>
        )}
      </div>
      {preview && <Preview id={doc.id} filename={doc.filename} onClose={() => setPreview(false)} />}
    </div>
  );
}

function Steps({ steps, live }: { steps: S["Step"][]; live?: boolean }) {
  const lines = steps.map((s, i) => (
    <div key={i} className={live && i === steps.length - 1 ? "live" : ""}><span>{s.icon}</span><span>{s.text}</span></div>
  ));
  if (live) return <div className="steps">{lines}</div>;
  return <details className="steps"><summary>{steps.length} consulta{steps.length > 1 ? "s" : ""} aos arquivos</summary>{lines}</details>;
}

function Bubble({ m, c, color, onImage, onMenu, live }: { m: Message; c: Conversation; color?: string; onImage: (s: string) => void;
  onMenu: (m: Message, x: number, y: number) => void; live: boolean }) {
  const { data: me } = useMe();
  const cfg = me?.settings;
  const trigger = useContextTrigger((x, y) => onMenu(m, x, y));
  if (m.author === "system") return <div className="sysmsg"><span>{m.body}</span></div>;
  const mine = m.author === "user";
  return (
    <div className={`msg ${mine ? "me" : "them"}`}>
      <div className="bub" {...trigger}>
        {c.kind === "group" && !mine && <div className="who" style={{ color: color ?? "var(--accent)" }}>{m.agent_name}</div>}
        {m.image_key && <AuthImage k={m.image_key} onOpen={onImage} />}
        {m.document && <DocCard doc={m.document} />}
        {cfg?.showSteps !== false && m.steps.length > 0 && <Steps steps={m.steps} />}
        {m.body && <div className="txt" dangerouslySetInnerHTML={{ __html: formatMessage(m.body) }} />}
        {m.card && <MessageCard card={m.card as { tipo: string }} live={live} />}
        {cfg?.showSources !== false && m.sources.length > 0 && <div className="src">Com base em {m.sources.map((s, i) => <b key={i}>{i ? ", " : ""}{s}</b>)}</div>}
        {m.error && <div className="src err">{m.error}</div>}
        <span className="stamp">{hhmm(m.created_at)}{mine && cfg?.receipts !== false && <Ticks status={m.status} />}</span>
      </div>
    </div>
  );
}

function LiveBubble({ r, c, color }: { r: LiveRun; c: Conversation; color?: string }) {
  const { data: me } = useMe();
  return (
    <div className="msg them">
      <div className="bub">
        {c.kind === "group" && <div className="who" style={{ color: color ?? "var(--accent)" }}>{r.agentName}</div>}
        {me?.settings.showSteps !== false && r.steps.length > 0 && <Steps steps={r.steps} live />}
        {r.text ? <div className="txt" dangerouslySetInnerHTML={{ __html: formatMessage(r.text) }} />
          : me?.settings.typing !== false && <div className="dots" aria-label="digitando"><i /><i /><i /></div>}
        <span className="stamp">agora</span>
      </div>
    </div>
  );
}

export function Chat({ id }: { id: string }) {
  const { data: convs = [] } = useConversations();
  const { data: agents = [] } = useAgents();
  const { data: me } = useMe();
  const { data: messages = [], isLoading } = useMessages(id);
  const { runs, setView, setDialog, notify, openConvMenu } = useApp();
  const send = useSend(id);
  const [text, setText] = useState("");
  const [pending, setPending] = useState<Pending | null>(null);
  const [lightbox, setLightbox] = useState<string | null>(null);
  const [menu, setMenu] = useState<MenuState>(null);
  const closeMenu = useCallback(() => setMenu(null), []);
  const wall = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLTextAreaElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const docStatus = useApp((s) => (pending?.kind === "document" ? s.docStatus[pending.doc.id] : undefined));

  const c = convs.find((x) => x.id === id);
  const live = liveFor(runs, id);
  const busy = !!c?.active_run || live.length > 0 || send.isPending;

  useLayoutEffect(() => {
    const w = wall.current;
    if (w) w.scrollTop = w.scrollHeight;
  }, [messages.length, live.map((r) => r.text.length + r.steps.length).join()]);
  useEffect(() => { if (!isMobile()) input.current?.focus(); }, [id]);
  useEffect(() => { setPending(null); setText(""); }, [id]);

  if (!c) return <div className="welcome"><div className="card"><p>Conversa não encontrada.</p></div></div>;
  const av = avatarOf(c, agents);
  const members = c.kind === "group" ? agents.filter((a) => c.members.includes(a.id)) : agents.filter((a) => a.id === c.agent_id);
  const colorOf = (name: string | null | undefined) => agents.find((a) => a.name === name)?.color;
  const typing = live[0] && me?.settings.typing !== false ? (c.kind === "group" ? `${live[0].agentName} está digitando…` : "digitando…") : null;
  const sub = typing ?? (c.kind === "group" ? ["você", ...members.map((a) => a.name)].join(", ")
    : members[0]?.documents ? `online · ${members[0].documents} arquivo${members[0].documents > 1 ? "s" : ""} na base` : "online");

  const pickFile = async (f: File) => {
    if (isSkillFile(f.name)) {             // .skill anexado na conversa: importa e ativa nesta conversa
      const r = await importSkillFiles([f]);
      if (r.ids.length) {
        const cur = await ok(api.GET("/api/conversations/{cid}/skills", { params: { path: { cid: id } } }));
        await ok(api.PUT("/api/conversations/{cid}/skills", { params: { path: { cid: id } }, body: { skill_ids: [...new Set([...(cur.skill_ids ?? []), ...r.ids])] } }));
      }
      return notify(r.fails.length ? r.fails.join(" ") : `${importSummary(r)} · ativa nesta conversa`);
    }
    setPending({ kind: "uploading", name: f.name });
    try {
      const up = await upload<S["Upload"]>(`/api/conversations/${id}/attachments`, f);
      if (up.kind === "image" && up.image_key) setPending({ kind: "image", key: up.image_key, preview: URL.createObjectURL(f), name: f.name });
      else if (up.document) setPending({ kind: "document", doc: up.document, name: f.name });
    } catch (e) {
      setPending(null);
      notify((e as Error).message);
    }
  };

  const docReady = pending?.kind !== "document" || (docStatus ?? pending.doc.status) !== "pending";
  const submit = () => {
    if (busy) return;
    if (pending?.kind === "uploading" || !docReady) return notify("Aguarde terminar a leitura do arquivo.");
    if (!text.trim() && !pending) return input.current?.focus();
    send.mutate(
      { body: text.trim(), image_key: pending?.kind === "image" ? pending.key : null, document_id: pending?.kind === "document" ? pending.doc.id : null },
      { onSuccess: () => { setText(""); setPending(null); } },
    );
  };
  const stop = async () => {
    try { await cancelRun(id); notify("Interrompendo…"); } catch (e) { notify((e as Error).message); }
  };

  const copy = (t: string, what: string) => void navigator.clipboard?.writeText(t).then(() => notify(`${what} copiado.`), () => notify("Não foi possível copiar."));
  const msgMenu = (m: Message, x: number, y: number) => {
    const items: NonNullable<MenuState>["items"] = [];
    if (m.body) items.push({ icon: "📋", label: "Copiar texto", onSelect: () => copy(m.body, "Texto") });
    if (m.sources.length) items.push({ icon: "📚", label: "Copiar fontes", onSelect: () => copy(m.sources.join("\n"), "Fontes") });
    if (m.author === "user" && m.body) items.push({ icon: "↩️", label: "Usar esta pergunta de novo", onSelect: () => { setText(m.body); input.current?.focus(); } });
    if (m.author === "agent" && m.body) items.push({ icon: "💬", label: "Responder citando", onSelect: () => {
      setText(`> ${m.body.split("\n")[0]!.slice(0, 160)}\n`); input.current?.focus(); } });
    if (m.error) items.push({ icon: "⚠️", label: "Copiar erro", onSelect: () => copy(m.error ?? "", "Erro") });
    if (items.length) setMenu({ x, y, items });
  };

  let lastDay = "";
  return (
    <>
      <div className="top chathead">
        <button className="iconbtn back" aria-label="Voltar" onClick={() => setView({ kind: "welcome" })}><Icon.back /></button>
        <Avatar {...av} small />
        <button className="t" onClick={() => setDialog(c.kind === "group" ? { kind: "group", id: c.id } : { kind: "agent", id: c.agent_id ?? undefined })}>
          <div className="tn">{title(c, agents)}</div>
          <div className={`sub ${typing ? "typing" : ""}`}>{sub}</div>
        </button>
        <button className="iconbtn" title="Opções da conversa" aria-label="Opções da conversa"
          onClick={(e) => { const r = e.currentTarget.getBoundingClientRect(); openConvMenu({ id: c.id, x: r.right, y: r.bottom + 4 }); }}><Icon.more /></button>
      </div>
      <div className="wall" ref={wall} aria-live="polite">
        {isLoading && <div className="sysmsg"><span>Carregando…</span></div>}
        {!isLoading && !messages.length && <div className="sysmsg"><span>Diga oi para {members.map((a) => a.name).join(", ")}. Você pode anexar foto, PDF, Word, Excel, PowerPoint, e-mail, .zip e muito mais — ou um .skill para ativar uma skill aqui.</span></div>}
        {messages.map((m) => {
          const d = dayLabel(m.created_at);
          const sep = d !== lastDay ? <div className="day"><span>{d}</span></div> : null;
          lastDay = d;
          return <div key={m.id}>{sep}<Bubble m={m} c={c} color={colorOf(m.agent_name)} onImage={setLightbox} onMenu={msgMenu}
            live={m.id === messages[messages.length - 1]?.id && !busy} /></div>;
        })}
        {live.map((r) => <LiveBubble key={r.runId} r={r} c={c} color={colorOf(r.agentName)} />)}
      </div>
      {pending && (
        <div className="attach-prev">
          <div className="chipx">
            {pending.kind === "image" ? <img src={pending.preview} alt="" /> : <span aria-hidden>📄</span>}
            <span>{pending.name} <small>{pending.kind === "uploading" ? "enviando…" : pending.kind === "document" ? (docReady ? (docStatus ?? pending.doc.status) === "ready" ? "pronto" : "não legível" : "lendo…") : ""}</small></span>
            <button aria-label="Remover anexo" onClick={() => setPending(null)}>×</button>
          </div>
        </div>
      )}
      <div className="composer">
        <button className="iconbtn plus" aria-label="Anexar imagem ou arquivo" title="Anexar" onClick={() => fileRef.current?.click()} disabled={!!pending}><Icon.plus /></button>
        <div className="box">
          <textarea ref={input} rows={1} value={text} aria-label="Mensagem" maxLength={20000}
            placeholder={c.kind === "group" ? "Mensagem (use @nome para chamar alguém)" : "Mensagem"}
            onChange={(e) => { setText(e.target.value); e.target.style.height = "auto"; e.target.style.height = `${Math.min(e.target.scrollHeight, 140)}px`; }}
            onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey && me?.settings.enterSend !== false && !isMobile()) { e.preventDefault(); submit(); } }} />
          <input ref={fileRef} type="file" hidden
            onChange={(e) => { const f = e.target.files?.[0]; e.target.value = ""; if (f) void pickFile(f); }} />
        </div>
        <button className={`send ${busy ? "stop" : ""}`} aria-label={busy ? "Parar resposta" : "Enviar"} onMouseDown={(e) => e.preventDefault()}
          onClick={() => (busy ? void stop() : submit())}>{busy ? <Icon.stop /> : <Icon.send />}</button>
      </div>
      {lightbox && <div className="lightbox on" onClick={() => setLightbox(null)}><img src={lightbox} alt="" /></div>}
      <ContextMenu menu={menu} onClose={closeMenu} />
    </>
  );
}
