// Gerenciador de arquivos: espaço usado, cota, duplicados, problemas e ações por arquivo. E a pré-visualização segura.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import { api, ApiError, downloadDocument, ok, upload, type ManagedDoc } from "../api/client";
import { useAgents, useConversations, useMe } from "../queries";
import { title as convTitle } from "./Sidebar";
import { importSkillFiles, importSummary, isSkillFile } from "./Skills";
import { useApp } from "../store";
import { ViewHead } from "./Settings";
import { currentTheme, kb, Modal } from "./ui";

const full = (e: Error) => (e instanceof ApiError && e.hint ? `${e.message} ${e.hint}` : e.message);
const PREVIEWABLE = /\.(html?|md|markdown|txt|csv|tsv|json|xml|ya?ml|log|sql|pdf|docx|xlsx|xlsm|pptx|odt|ods|odp|rtf|epub|eml|ipynb|py|js|ts)$/i;
export const canPreview = (filename: string) => PREVIEWABLE.test(filename);

/** Página formatada pelo servidor (Markdown renderizado, Word/PDF por página, planilha como tabela), num iframe sandbox sem script. */
export function Preview({ id, filename, onClose }: { id: string; filename: string; onClose: () => void }) {
  const [page, setPage] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    ok(api.GET("/api/documents/{document_id}/preview", { params: { path: { document_id: id }, query: { theme: currentTheme() } } }))
      .then((r) => setPage(r.html), (e: Error) => setErr(e.message));
  }, [id]);
  return (
    <Modal title={filename} onClose={onClose} wide
      footer={<><span className="muted">Visualização formatada · scripts desativados</span>
        <button className="btn" onClick={() => void downloadDocument(id, filename)}>Baixar</button></>}>
      {err ? <p className="muted" style={{ padding: 16 }}>{err}</p> : page === null ? <p className="muted" style={{ padding: 16 }}>Carregando…</p>
        : <iframe className="preview-frame" title={filename} sandbox="" srcDoc={page} />}
    </Modal>
  );
}

type Sent = { name: string; state: "enviando" | "lendo" | "pronto" | "erro" | "skill"; note?: string; id?: string };

/** Área de envio: escolhe o destino (base de um agente ou uma conversa), botão ou arrastar e soltar, vários de uma vez. */
function UploadCard() {
  const qc = useQueryClient();
  const notify = useApp((s) => s.notify);
  const docStatus = useApp((s) => s.docStatus);
  const { data: agents = [] } = useAgents();
  const { data: convs = [] } = useConversations();
  const [dest, setDest] = useState("");
  const [drag, setDrag] = useState(false);
  const [sent, setSent] = useState<Sent[]>([]);
  const input = useRef<HTMLInputElement>(null);
  useEffect(() => { if (!dest && agents[0]) setDest(`agent:${agents[0].id}`); }, [agents, dest]);
  const [kind, target] = dest.split(":") as ["agent" | "conv", string];
  const set = (name: string, patch: Partial<Sent>) => setSent((l) => l.map((x) => (x.name === name ? { ...x, ...patch } : x)));

  const send = async (files: File[]) => {
    if (!target) return notify("Crie um agente ou uma conversa antes de enviar arquivos.");
    setSent((l) => [...files.map((f) => ({ name: f.name, state: "enviando" as const })), ...l.filter((x) => !files.some((f) => f.name === x.name))].slice(0, 30));
    const skills = files.filter((f) => isSkillFile(f.name));
    if (skills.length) {
      const r = await importSkillFiles(skills);
      if (r.ids.length && kind === "agent") {
        const params = { path: { agent_id: target } };
        const cur = await ok(api.GET("/api/agents/{agent_id}/skills", { params }));
        await ok(api.PUT("/api/agents/{agent_id}/skills", { params, body: { skill_ids: [...new Set([...(cur.skill_ids ?? []), ...r.ids])] } }));
      } else if (r.ids.length) {
        const params = { path: { cid: target } };
        const cur = await ok(api.GET("/api/conversations/{cid}/skills", { params }));
        await ok(api.PUT("/api/conversations/{cid}/skills", { params, body: { skill_ids: [...new Set([...(cur.skill_ids ?? []), ...r.ids])] } }));
      }
      skills.forEach((f) => set(f.name, r.fails.some((x) => x.startsWith(f.name)) ? { state: "erro", note: r.fails.find((x) => x.startsWith(f.name)) } : { state: "skill", note: "virou skill ativa" }));
      void qc.invalidateQueries({ queryKey: ["skills"] });
      notify(importSummary(r));
    }
    for (const f of files.filter((x) => !isSkillFile(x.name))) {
      try {
        const url = kind === "agent" ? `/api/agents/${target}/documents` : `/api/conversations/${target}/attachments`;
        const r = await upload<{ id?: string; status?: string; kind?: string; document?: { id: string; status: string } | null }>(url, f);
        const doc = r.document ?? (r.id ? { id: r.id, status: r.status ?? "pending" } : null);
        set(f.name, doc ? { state: doc.status === "pending" ? "lendo" : "pronto", id: doc.id } : { state: "pronto", note: "imagem" });
      } catch (e) {
        set(f.name, { state: "erro", note: full(e as Error) });
      }
    }
    ["documents", "storage", "agentDocs", "agents"].forEach((k) => void qc.invalidateQueries({ queryKey: [k] }));
  };
  const label = (x: Sent) => {
    const live = x.id ? docStatus[x.id] : undefined;
    if (x.state === "lendo" && live) return live === "ready" ? "pronto" : live === "pending" ? "lendo…" : "não legível";
    return x.state === "enviando" ? "enviando…" : x.state === "lendo" ? "lendo…" : x.state;
  };

  return (
    <section className={`grp ${drag ? "dropping" : ""}`}
      onDragOver={(e) => { e.preventDefault(); setDrag(true); }} onDragLeave={() => setDrag(false)}
      onDrop={(e) => { e.preventDefault(); setDrag(false); const f = [...e.dataTransfer.files]; if (f.length) void send(f); }}>
      <h3>Enviar arquivos</h3>
      <div className="field"><label htmlFor="upDest">Para onde</label>
        <select id="upDest" value={dest} onChange={(e) => setDest(e.target.value)}>
          {!agents.length && !convs.length && <option value="">Crie um agente primeiro</option>}
          {agents.length > 0 && <optgroup label="Base de um agente (ele consulta em todas as conversas)">
            {agents.map((a) => <option key={a.id} value={`agent:${a.id}`}>{a.emoji} {a.name}</option>)}</optgroup>}
          {convs.length > 0 && <optgroup label="Uma conversa (vale só nela)">
            {convs.map((c) => <option key={c.id} value={`conv:${c.id}`}>💬 {convTitle(c, agents)}</option>)}</optgroup>}
        </select></div>
      <button type="button" className="dropzone" onClick={() => input.current?.click()} disabled={!target}>
        <b>Arraste os arquivos para cá</b><span>ou clique para escolher · vários de uma vez, até 50 MB cada</span>
        <small>PDF, Word, Excel, CSV, PowerPoint, OpenDocument, RTF, e-mail, EPUB, HTML, Markdown, código, .zip · .skill vira skill</small>
      </button>
      <input ref={input} type="file" hidden multiple onChange={(e) => { const f = [...(e.target.files ?? [])]; e.target.value = ""; if (f.length) void send(f); }} />
      {sent.length > 0 && (
        <ul className="sent">
          {sent.map((x) => {
            const l = label(x);
            return <li key={x.name}><span className="ellip">{x.name}</span><small className={l === "erro" || l === "não legível" ? "warn" : l === "pronto" || l === "skill" ? "okc" : ""}>{x.note && l === "erro" ? x.note : l}</small></li>;
          })}
        </ul>
      )}
    </section>
  );
}

const PLACE = { todos: "Todos", agente: "Base dos agentes", conversa: "Conversas" } as const;
const ONLY = { todos: "Todos", problemas: "Com problema", duplicados: "Duplicados", removidos: "Removidos" } as const;
const STATUS: Record<string, string> = { pending: "lendo…", ready: "pronto", unreadable: "não legível", failed: "falhou" };

export function Files() {
  const qc = useQueryClient();
  const notify = useApp((s) => s.notify);
  const { data: me } = useMe();
  const [q, setQ] = useState("");
  const [place, setPlace] = useState<keyof typeof PLACE>("todos");
  const [only, setOnly] = useState<keyof typeof ONLY>("todos");
  const [origin, setOrigin] = useState<"todos" | "upload" | "agent">("todos");
  const [preview, setPreview] = useState<ManagedDoc | null>(null);
  const { data: st } = useQuery({ queryKey: ["storage"], queryFn: () => ok(api.GET("/api/documents/stats")) });
  const { data: docs = [], isLoading } = useQuery({
    queryKey: ["documents", q, place, only, origin],
    queryFn: () => ok(api.GET("/api/documents", { params: { query: { q: q || undefined, place, only, origin } } })),
  });
  const refresh = () => ["documents", "storage", "messages", "agentDocs"].forEach((k) => void qc.invalidateQueries({ queryKey: [k] }));
  const remove = useMutation({
    mutationFn: (d: ManagedDoc) => ok(api.DELETE("/api/documents/{document_id}", { params: { path: { document_id: d.id } } })),
    onSuccess: (r) => { refresh(); notify(`${(r as { action: string }).action === "apagado" ? "Arquivo apagado" : "Espaço liberado"}.`); },
    onError: (e: Error) => notify(full(e)),
  });
  const cleanup = useMutation({
    mutationFn: (what: "duplicados" | "problemas") => ok(api.POST("/api/documents/cleanup", { params: { query: { what } } })),
    onSuccess: (r) => { const x = r as { files: number; bytes_freed: number }; refresh(); notify(x.files ? `${x.files} arquivo(s) tratados · ${kb(x.bytes_freed)} liberados.` : "Nada a limpar."); },
    onError: (e: Error) => notify(full(e)),
  });
  const pct = st?.quota_bytes ? Math.min(100, (st.bytes / st.quota_bytes) * 100) : 0;
  const ask = (d: ManagedDoc) => {
    const msg = d.place === "agente"
      ? `Apagar "${d.filename}" da base de ${d.place_name}? O agente deixa de consultá-lo.`
      : `Liberar o espaço de "${d.filename}"? A mensagem continua na conversa, mas o arquivo deixa de existir e o agente não o lê mais.`;
    if (confirm(msg)) remove.mutate(d);
  };

  return (
    <>
      <ViewHead title="Arquivos" sub="O que foi enviado e gerado, e quanto ocupa" />
      <div className="view"><div className="vwrap">
        <UploadCard />
        {st && (
          <section className="grp"><h3>Armazenamento</h3>
            <div className="stats">
              <div><b>{kb(st.bytes)}</b><span>{st.quota_bytes ? `de ${kb(st.quota_bytes)}` : "em uso"}</span></div>
              <div><b>{st.files}</b><span>arquivos</span></div>
              <div><b>{st.duplicate_groups}</b><span>{st.duplicate_groups ? `duplicados · ${kb(st.duplicate_bytes)}` : "duplicados"}</span></div>
              <div><b>{st.problems}</b><span>com problema</span></div>
            </div>
            {st.quota_bytes != null && <div className={`meter ${pct >= 100 ? "bad" : pct >= 85 ? "warn" : ""}`} role="meter" aria-valuenow={Math.round(pct)}
              aria-label="Uso da cota"><i style={{ width: `${pct}%` }} /></div>}
            <div className="tbl-wrap"><table className="tbl">
              <thead><tr><th>Onde</th><th>Arquivos</th><th>Tamanho</th></tr></thead>
              <tbody>{st.by_place.map((g) => <tr key={g.key}><td>{g.label}</td><td>{g.files}</td><td>{kb(g.bytes)}</td></tr>)}
                {st.by_kind.length > 0 && <tr><td colSpan={3} className="sub-head">Por tipo</td></tr>}
                {st.by_kind.map((g) => <tr key={g.key}><td>{g.label}</td><td>{g.files}</td><td>{kb(g.bytes)}</td></tr>)}</tbody>
            </table></div>
            <div className="kbact">
              <button className="btn ghost" disabled={!st.duplicate_groups || cleanup.isPending}
                onClick={() => confirm("Remover as cópias repetidas? Fica a mais antiga de cada conteúdo (a da base do agente tem preferência).") && cleanup.mutate("duplicados")}>
                Remover duplicados</button>
              <button className="btn ghost" disabled={!st.problems || cleanup.isPending}
                onClick={() => confirm("Remover os arquivos que falharam ou não puderam ser lidos?") && cleanup.mutate("problemas")}>Limpar com problema</button>
            </div>
            {st.freed_bytes > 0 && <p className="hint">{kb(st.freed_bytes)} já liberados por limpeza.</p>}
          </section>
        )}
        {me?.is_admin && <QuotaCard />}
        <section className="grp"><h3>Lista de arquivos</h3>
          <div className="field"><input type="search" placeholder="Buscar pelo nome" aria-label="Buscar arquivo" value={q} onChange={(e) => setQ(e.target.value)} /></div>
          <div className="filters">
            <select aria-label="Onde" value={place} onChange={(e) => setPlace(e.target.value as keyof typeof PLACE)}>
              {Object.entries(PLACE).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select>
            <select aria-label="Origem" value={origin} onChange={(e) => setOrigin(e.target.value as typeof origin)}>
              <option value="todos">Enviados e gerados</option><option value="upload">Só enviados</option><option value="agent">Só gerados pelos agentes</option></select>
            <select aria-label="Situação" value={only} onChange={(e) => setOnly(e.target.value as keyof typeof ONLY)}>
              {Object.entries(ONLY).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select>
          </div>
          {isLoading ? <p className="muted">Carregando…</p> : !docs.length ? <p className="muted">Nenhum arquivo com esses filtros.</p> : (
            <ul className="files">
              {docs.map((d) => (
                <li key={d.id} className={d.purged ? "gone" : ""}>
                  <div className="ic">{(d.filename.split(".").pop() ?? "ARQ").slice(0, 4).toUpperCase()}</div>
                  <div className="fmeta">
                    <b className="ellip" title={d.filename}>{d.filename}</b>
                    <small>{d.place === "agente" ? "📚" : "💬"} {d.place_name} · {kb(d.size_bytes)} · {new Date(d.created_at).toLocaleDateString("pt-BR")}
                      {d.origin === "agent" && <span className="tag">gerado</span>}
                      {d.duplicates > 0 && !d.purged && <span className="tag warn">{d.duplicates} cópia{d.duplicates > 1 ? "s" : ""}</span>}
                      {d.purged ? <span className="tag">removido</span> : d.status !== "ready" && <span className={`tag ${d.status === "pending" ? "" : "bad"}`}>{STATUS[d.status]}</span>}</small>
                    {d.note && !d.purged && d.status !== "ready" && <small className="warn">{d.note}</small>}
                  </div>
                  {!d.purged && <div className="factions">
                    {canPreview(d.filename) && <button className="btn ghost sm" onClick={() => setPreview(d)}>Ver</button>}
                    <button className="btn ghost sm" onClick={() => void downloadDocument(d.id, d.filename).catch((e: Error) => notify(e.message))}>Baixar</button>
                    <button className="btn danger sm" onClick={() => ask(d)}>{d.place === "agente" ? "Apagar" : "Liberar"}</button>
                  </div>}
                </li>
              ))}
            </ul>
          )}
        </section>
      </div></div>
      {preview && <Preview id={preview.id} filename={preview.filename} onClose={() => setPreview(null)} />}
    </>
  );
}

function QuotaCard() {
  const notify = useApp((s) => s.notify);
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["quota"], queryFn: () => ok(api.GET("/api/admin/storage")) });
  const [mb, setMb] = useState("");
  useEffect(() => setMb(data?.storage_quota_mb?.toString() ?? ""), [data]);
  const save = useMutation({
    mutationFn: () => ok(api.PUT("/api/admin/storage", { body: { storage_quota_mb: mb.trim() ? Number(mb) : null } })),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ["storage"] }); void qc.invalidateQueries({ queryKey: ["quota"] }); notify("Cota salva."); },
    onError: (e: Error) => notify(full(e)),
  });
  return (
    <section className="grp"><h3>Administração · Cota de armazenamento</h3>
      <div className="field"><label htmlFor="qMb">Espaço por usuário (MB)</label>
        <input id="qMb" type="text" inputMode="numeric" placeholder="sem cota" value={mb} onChange={(e) => setMb(e.target.value)} />
        <div className="hint">Vale para PDFs, planilhas e documentos (enviados e gerados). Com a cota cheia, o envio é recusado com aviso.</div></div>
      <div><button className="btn" disabled={save.isPending} onClick={() => save.mutate()}>Salvar cota</button></div>
    </section>
  );
}
