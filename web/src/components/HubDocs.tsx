// Docs do hub: fontes (VPS e site), gráficos do catálogo, navegação com prévia e download direto da origem, e vínculo com agentes.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { api, ApiError, authHeader, ok, type S } from "../api/client";
import { useMe } from "../queries";
import { useApp } from "../store";
import { currentTheme, kb, Modal } from "./ui";

type Source = S["SourceOut"];
type HubFile = S["HubFile"];
const full = (e: Error) => (e instanceof ApiError && e.hint ? `${e.message} ${e.hint}` : e.message);
const KIND = { local: "Pastas desta VPS", remote: "Leitor em outra VPS", sftp: "SFTP (site / hospedagem)" } as const;
const STATUS: Record<string, string> = { ok: "no ar", erro: "com erro", nova: "não testada" };

/** Barras horizontais de uma série: comprimento = quantidade, rótulo com o número ao lado (sem depender de cor). */
function HBars({ title, rows, unit = "arquivos" }: { title: string; rows: { key: string; files: number; bytes: number }[]; unit?: string }) {
  const max = Math.max(1, ...rows.map((r) => r.files));
  if (!rows.length) return null;
  return (
    <figure className="hbars" aria-label={title}>
      <figcaption>{title}</figcaption>
      {rows.map((r) => (
        <div key={r.key} className="hbar" title={`${r.key}: ${r.files} ${unit} · ${kb(r.bytes)}`}>
          <span className="hk ellip">{r.key}</span>
          <span className="ht"><i style={{ width: `${(r.files / max) * 100}%` }} /></span>
          <span className="hv">{r.files}</span>
        </div>
      ))}
    </figure>
  );
}

async function hubRaw(sourceId: string, path: string): Promise<void> {
  const r = await fetch(`/api/hub/file/raw?source_id=${sourceId}&path=${encodeURIComponent(path)}`, { headers: await authHeader() });
  if (!r.ok) throw new ApiError(r.status, ((await r.json().catch(() => ({}))) as { message?: string }).message ?? "Não foi possível baixar.");
  const a = document.createElement("a");
  a.href = URL.createObjectURL(await r.blob());
  a.download = path.split("/").pop() ?? "arquivo";
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 5000);
}

function HubPreview({ f, onClose }: { f: HubFile; onClose: () => void }) {
  const notify = useApp((s) => s.notify);
  const { data, error } = useQuery({
    queryKey: ["hubpreview", f.source_id, f.path],
    queryFn: () => ok(api.GET("/api/hub/file/preview", { params: { query: { source_id: f.source_id, path: f.path, theme: currentTheme() } } })),
    staleTime: 0, gcTime: 0,                    // não guarda: cada abertura lê de novo na origem
  });
  const page = data?.html;
  return (
    <Modal title={f.path.split("/").pop() ?? f.path} onClose={onClose} wide
      footer={<><span className="muted ellip">{f.source} · {f.path} · lido agora na origem</span>
        <button className="btn" onClick={() => void hubRaw(f.source_id, f.path).catch((e: Error) => notify(e.message))}>Baixar</button></>}>
      {error ? <p className="muted" style={{ padding: 16 }}>{(error as Error).message}</p> : !page ? <p className="muted" style={{ padding: 16 }}>Lendo na origem…</p>
        : <iframe className="preview-frame" title={f.path} sandbox="" srcDoc={page} />}
    </Modal>
  );
}

type Kind = Source["kind"];
const EMPTY = { name: "", label: "", kind: "local" as Kind, roots: "opt,www", url: "https://203.0.113.30:8743", cert_pem: "", host: "", port: 22,
  user: "", root: "domains/gplansis.com/public_html", secret: "", extensions: "", enabled: true, visible_all: false };

function SourceForm({ initial, onClose }: { initial?: Source; onClose: () => void }) {
  const qc = useQueryClient();
  const notify = useApp((s) => s.notify);
  const c = (initial?.config ?? {}) as Record<string, unknown>;
  const [f, setF] = useState(() => initial ? {
    ...EMPTY, name: initial.name, label: initial.label, kind: initial.kind, roots: ((c.roots as string[]) ?? []).join(","),
    url: String(c.url ?? EMPTY.url), host: String(c.host ?? ""), port: Number(c.port ?? 22), user: String(c.user ?? ""), root: String(c.root ?? "."),
    extensions: initial.extensions.join(","), enabled: initial.enabled, visible_all: initial.visible_all } : EMPTY);
  const set = (k: keyof typeof EMPTY, v: unknown) => setF((x) => ({ ...x, [k]: v }));
  const save = useMutation({
    mutationFn: () => {
      const body = { name: f.name.trim(), label: f.label.trim(), kind: f.kind, roots: f.roots.split(",").map((x) => x.trim()).filter(Boolean),
        url: f.kind === "remote" ? f.url.trim() : null, cert_pem: f.cert_pem.trim() || null, host: f.kind === "sftp" ? f.host.trim() : null,
        port: Number(f.port) || 22, user: f.kind === "sftp" ? f.user.trim() : null, root: f.root.trim() || ".", secret: f.secret || null,
        extensions: f.extensions.trim() ? f.extensions.split(",").map((x) => x.trim()).filter(Boolean) : undefined,
        enabled: f.enabled, visible_all: f.visible_all };
      return initial ? ok(api.PUT("/api/hub/sources/{source_id}", { params: { path: { source_id: initial.id } }, body }))
        : ok(api.POST("/api/hub/sources", { body }));
    },
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ["hubsources"] }); notify("Fonte salva. Clique em Testar e depois em Indexar."); onClose(); },
    onError: (e: Error) => notify(full(e)),
  });
  return (
    <Modal title={initial ? `Fonte · ${initial.label}` : "Nova fonte do hub"} onClose={onClose}
      footer={<><span className="muted">Só leitura. Token e senha ficam cifrados.</span><button className="btn" disabled={save.isPending} onClick={() => save.mutate()}>Salvar</button></>}>
      <div className="field"><label htmlFor="hsLabel">Nome de exibição</label><input id="hsLabel" type="text" value={f.label} onChange={(e) => set("label", e.target.value)} placeholder="Ex.: servidor · sistemas" /></div>
      <div className="field"><label htmlFor="hsName">Identificador</label><input id="hsName" type="text" value={f.name} onChange={(e) => set("name", e.target.value.toLowerCase())} placeholder="servidor1" />
        <div className="hint">Letras minúsculas, números e hífen.</div></div>
      <div className="field"><label htmlFor="hsKind">Tipo</label>
        <select id="hsKind" value={f.kind} onChange={(e) => set("kind", e.target.value)}>{Object.entries(KIND).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></div>
      {f.kind === "local" && <div className="field"><label htmlFor="hsRoots">Pastas</label><input id="hsRoots" type="text" value={f.roots} onChange={(e) => set("roots", e.target.value)} />
        <div className="hint">Nomes montados no gateway: <code>opt</code> (/opt) e <code>www</code> (/var/www).</div></div>}
      {f.kind === "remote" && <>
        <div className="field"><label htmlFor="hsUrl">Endereço do leitor</label><input id="hsUrl" type="text" value={f.url} onChange={(e) => set("url", e.target.value)} /></div>
        <div className="field"><label htmlFor="hsCert">Certificado do leitor (cert.pem)</label>
          <textarea id="hsCert" value={f.cert_pem} onChange={(e) => set("cert_pem", e.target.value)} placeholder={initial ? "fixado — cole outro só para trocar" : "-----BEGIN CERTIFICATE-----"} /></div>
        <div className="field"><label htmlFor="hsTok">Token do leitor</label><input id="hsTok" type="password" autoComplete="off" value={f.secret} onChange={(e) => set("secret", e.target.value)} placeholder={initial?.has_secret ? "guardado — preencha só para trocar" : ""} /></div>
      </>}
      {f.kind === "sftp" && <>
        <div className="row3">
          <div className="field"><label htmlFor="hsHost">Servidor</label><input id="hsHost" type="text" value={f.host} onChange={(e) => set("host", e.target.value)} placeholder="45.132.157.26" /></div>
          <div className="field"><label htmlFor="hsPort">Porta</label><input id="hsPort" type="text" inputMode="numeric" value={f.port} onChange={(e) => set("port", e.target.value)} /></div>
          <div className="field"><label htmlFor="hsUser">Usuário</label><input id="hsUser" type="text" value={f.user} onChange={(e) => set("user", e.target.value)} /></div>
        </div>
        <div className="field"><label htmlFor="hsPw">Senha</label><input id="hsPw" type="password" autoComplete="off" value={f.secret} onChange={(e) => set("secret", e.target.value)} placeholder={initial?.has_secret ? "guardada — preencha só para trocar" : ""} /></div>
        <div className="field"><label htmlFor="hsRoot">Pasta raiz</label><input id="hsRoot" type="text" value={f.root} onChange={(e) => set("root", e.target.value)} />
          <div className="hint">A chave do servidor é fixada no primeiro teste; se mudar depois, a leitura é recusada.</div></div>
      </>}
      <div className="field"><label htmlFor="hsExt">Extensões lidas</label><input id="hsExt" type="text" value={f.extensions} onChange={(e) => set("extensions", e.target.value)} placeholder="padrão: pdf, md, docx, xlsx, csv, pptx, odt, rtf, epub, txt, skill…" />
        <div className="hint">Segredos (.env, chaves, pastas de backup, node_modules, .git) nunca são lidos, seja qual for a extensão.</div></div>
      <label className="sw"><span><b>Ativa</b><small>Desativada: some do índice dos agentes e não é reindexada.</small></span>
        <input type="checkbox" checked={f.enabled} onChange={(e) => set("enabled", e.target.checked)} /><i aria-hidden /></label>
      <label className="sw"><span><b>Visível para todos os usuários</b><small>Desligado: só administradores veem e ligam aos agentes.</small></span>
        <input type="checkbox" checked={f.visible_all} onChange={(e) => set("visible_all", e.target.checked)} /><i aria-hidden /></label>
    </Modal>
  );
}

export function HubDocsSection() {
  const qc = useQueryClient();
  const notify = useApp((s) => s.notify);
  const { data: me } = useMe();
  const admin = !!me?.is_admin;
  const { data: sources = [] } = useQuery({ queryKey: ["hubsources"], queryFn: () => ok(api.GET("/api/hub/sources")) });
  const { data: st } = useQuery({ queryKey: ["hubstats"], queryFn: () => ok(api.GET("/api/hub/stats")), enabled: sources.length > 0 });
  const [q, setQ] = useState("");
  const [src, setSrc] = useState("");
  const [ext, setExt] = useState("");
  const [form, setForm] = useState<Source | "new" | null>(null);
  const [preview, setPreview] = useState<HubFile | null>(null);
  const [debounced, setDebounced] = useState("");
  useEffect(() => { const t = setTimeout(() => setDebounced(q), 300); return () => clearTimeout(t); }, [q]);
  const { data: files = [], isFetching } = useQuery({
    queryKey: ["hubfiles", debounced, src, ext], enabled: sources.length > 0,
    queryFn: () => ok(api.GET("/api/hub/files", { params: { query: { q: debounced || undefined, source: src || undefined, ext: ext || undefined, limit: 200 } } })),
  });
  const refresh = () => ["hubsources", "hubstats", "hubfiles"].forEach((k) => void qc.invalidateQueries({ queryKey: [k] }));
  const act = useMutation({
    mutationFn: async ({ s, op }: { s: Source; op: "test" | "index" | "delete" }) => {
      const params = { path: { source_id: s.id } };
      if (op === "test") return ok(api.POST("/api/hub/sources/{source_id}/test", { params }));
      if (op === "index") return ok(api.POST("/api/hub/sources/{source_id}/index", { params }));
      return ok(api.DELETE("/api/hub/sources/{source_id}", { params }));
    },
    onSuccess: (r, { s, op }) => {
      refresh();
      const x = r as Record<string, unknown> | undefined;
      notify(op === "test" ? (x?.ok ? `${s.label}: conectada.` : `${s.label}: ${String(x?.error ?? "falhou")}`)
        : op === "index" ? `${s.label}: ${String(x?.files)} arquivos no índice.` : "Fonte removida.");
    },
    onError: (e: Error) => { refresh(); notify(full(e)); },
  });

  if (!admin && !sources.length) return null;
  return (
    <section className="grp" id="hub"><h3>Docs do hub</h3>
      <p className="hint">Arquivos dos sistemas do hub GPlanSiS lidos <b>direto na origem</b>: o Papo guarda só o índice (nome, pasta, tamanho, data);
        prévia, download e leitura pelos agentes buscam o arquivo na hora e não deixam cópia. Ligue fontes ou pastas a um agente no diálogo dele.</p>
      <div className="hub-sources">
        {sources.map((s) => (
          <div key={s.id} className={`hsrc ${s.status}`}>
            <div className="hsrc-top"><b>{s.label}</b><span className={`badge ${s.status === "ok" ? "ok" : s.status === "erro" ? "bad" : ""}`}>{s.status === "erro" ? "⚠ " : ""}{STATUS[s.status]}</span></div>
            <small className="muted">{KIND[s.kind as keyof typeof KIND] ?? s.kind}{s.visible_all ? " · todos veem" : ""}{!s.enabled ? " · desativada" : ""}</small>
            <div className="hsrc-num"><b>{s.file_count}</b> arquivos · {kb(s.total_bytes)}</div>
            <small className="muted">{s.last_scan_at ? `índice de ${new Date(s.last_scan_at).toLocaleString("pt-BR")}` : "ainda não indexada"}</small>
            {s.last_error && <small className="warn">{s.last_error}</small>}
            {admin && <div className="kbact">
              <button className="btn ghost sm" disabled={act.isPending} onClick={() => act.mutate({ s, op: "test" })}>Testar</button>
              <button className="btn ghost sm" disabled={act.isPending} onClick={() => act.mutate({ s, op: "index" })}>Indexar</button>
              <button className="btn ghost sm" onClick={() => setForm(s)}>Editar</button>
              <button className="btn danger sm" onClick={() => confirm(`Remover a fonte "${s.label}"? Só o índice sai; nada é apagado na origem.`) && act.mutate({ s, op: "delete" })}>Remover</button>
            </div>}
          </div>
        ))}
        {admin && <button className="hsrc add" onClick={() => setForm("new")}><b>+ Nova fonte</b><small>VPS, leitor remoto ou SFTP</small></button>}
      </div>
      {st && st.files > 0 && (
        <>
          <div className="stats">
            <div><b>{st.files}</b><span>arquivos no índice</span></div>
            <div><b>{kb(st.bytes)}</b><span>na origem (nada copiado)</span></div>
            <div><b>{st.by_source.length}</b><span>fontes</span></div>
            <div><b>{st.by_ext.length}</b><span>tipos</span></div>
          </div>
          <div className="hub-charts">
            <HBars title="Arquivos por tipo" rows={st.by_ext.map((r) => ({ key: `.${r.key}`, files: r.files, bytes: r.bytes }))} />
            <HBars title="Sistemas com mais documentos" rows={st.by_folder.slice(0, 10)} />
          </div>
        </>
      )}
      {sources.length > 0 && (
        <>
          <div className="field"><input type="search" placeholder="Buscar por nome ou pasta (ex.: peoples manual)" aria-label="Buscar nos docs do hub" value={q} onChange={(e) => setQ(e.target.value)} /></div>
          <div className="filters">
            <select aria-label="Fonte" value={src} onChange={(e) => setSrc(e.target.value)}><option value="">Todas as fontes</option>{sources.map((s) => <option key={s.id} value={s.id}>{s.label}</option>)}</select>
            <select aria-label="Tipo" value={ext} onChange={(e) => setExt(e.target.value)}><option value="">Todos os tipos</option>{(st?.by_ext ?? []).map((e) => <option key={e.key} value={e.key}>.{e.key} ({e.files})</option>)}</select>
            <span className="muted">{isFetching ? "buscando…" : `${files.length}${files.length === 200 ? "+" : ""} arquivo(s)`}</span>
          </div>
          <ul className="files">
            {files.map((f) => (
              <li key={`${f.source_id}:${f.path}`}>
                <div className="ic">{f.ext.slice(0, 4).toUpperCase()}</div>
                <div className="fmeta"><b className="ellip" title={f.path}>{f.path.split("/").pop()}</b>
                  <small className="ellip">{f.source} · {f.path.split("/").slice(0, -1).join("/")} · {kb(f.size_bytes)} · {new Date(f.mtime).toLocaleDateString("pt-BR")}</small></div>
                <div className="factions">
                  <button className="btn ghost sm" onClick={() => setPreview(f)}>Ver</button>
                  <button className="btn ghost sm" onClick={() => void hubRaw(f.source_id, f.path).catch((e: Error) => notify(e.message))}>Baixar</button>
                </div>
              </li>
            ))}
          </ul>
        </>
      )}
      {form && <SourceForm initial={form === "new" ? undefined : form} onClose={() => setForm(null)} />}
      {preview && <HubPreview f={preview} onClose={() => setPreview(null)} />}
    </section>
  );
}

/** No diálogo do agente: quais fontes (e pastas) do hub ele lê. */
export function AgentHub({ agentId }: { agentId: string }) {
  const qc = useQueryClient();
  const notify = useApp((s) => s.notify);
  const { data: sources = [] } = useQuery({ queryKey: ["hubsources"], queryFn: () => ok(api.GET("/api/hub/sources")) });
  const { data } = useQuery({ queryKey: ["agentHub", agentId], queryFn: () => ok(api.GET("/api/hub/agents/{agent_id}", { params: { path: { agent_id: agentId } } })) });
  const [links, setLinks] = useState<{ source_id: string; prefix: string }[]>([]);
  useEffect(() => setLinks((data?.links ?? []).map((l) => ({ source_id: l.source_id, prefix: l.prefix ?? "" }))), [data]);
  const save = useMutation({
    mutationFn: (next: typeof links) => ok(api.PUT("/api/hub/agents/{agent_id}", { params: { path: { agent_id: agentId } }, body: { links: next } })),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["agentHub", agentId] }),
    onError: (e: Error) => notify(full(e)),
  });
  const usable = sources.filter((s) => s.enabled);
  if (!usable.length) return null;
  const has = (id: string) => links.find((l) => l.source_id === id);
  const update = (next: typeof links) => { setLinks(next); save.mutate(next); };
  return (
    <div className="field"><label>Docs do hub</label>
      <div className="pick">
        {usable.map((s) => {
          const l = has(s.id);
          return (
            <div key={s.id} className="hub-link">
              <label><input type="checkbox" checked={!!l} onChange={(e) => update(e.target.checked ? [...links, { source_id: s.id, prefix: "" }] : links.filter((x) => x.source_id !== s.id))} />
                <span><b>{s.label}</b><small className="muted"> — {s.file_count} arquivos</small></span></label>
              {l && <input type="text" aria-label={`Pasta de ${s.label}`} placeholder="todas as pastas (ou ex.: opt/peoples)" defaultValue={l.prefix}
                onBlur={(e) => { const v = e.target.value.trim(); if (v !== l.prefix) update(links.map((x) => (x.source_id === s.id ? { ...x, prefix: v } : x))); }} />}
            </div>
          );
        })}
      </div>
      <div className="hint">O agente procura e lê esses arquivos na origem quando a pergunta envolve os sistemas.</div>
    </div>
  );
}
