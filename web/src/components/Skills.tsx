// Skills: biblioteca (upload de SKILL.md/.zip, ativar, compartilhar, ver, apagar) e escolha por agente e por conversa.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import { api, ApiError, ok, upload, type S } from "../api/client";
import { useMe } from "../queries";
import { useApp } from "../store";
import { kb, Modal } from "./ui";

type Skill = S["SkillOut"];
const full = (e: Error) => (e instanceof ApiError && e.hint ? `${e.message} ${e.hint}` : e.message);
export const isSkillFile = (name: string) => /\.skill$/i.test(name);

/** Importa .skill/.zip/SKILL.md. Devolve os ids (novos e atualizados) para ativar em seguida. */
export async function importSkillFiles(files: File[]): Promise<{ created: number; updated: number; ids: string[]; fails: string[] }> {
  let created = 0, updated = 0;
  const ids: string[] = [], fails: string[] = [];
  for (const f of files) {
    try {
      const r = await upload<S["SkillUploadResult"]>("/api/skills", f);
      created += r.created.length;
      updated += r.updated.length;
      ids.push(...(r.ids ?? []));
    } catch (e) {
      fails.push(`${f.name}: ${(e as Error).message}`);
    }
  }
  return { created, updated, ids, fails };
}

export const importSummary = (r: { created: number; updated: number; fails: string[] }) =>
  [r.created && `${r.created} skill(s) nova(s)`, r.updated && `${r.updated} atualizada(s)`, r.fails.length && `${r.fails.length} com erro`].filter(Boolean).join(" · ") || "Nada importado.";

export const useSkills = () => useQuery({ queryKey: ["skills"], queryFn: () => ok(api.GET("/api/skills")) });

function SkillView({ id, onClose }: { id: string; onClose: () => void }) {
  const { data } = useQuery({ queryKey: ["skill", id], queryFn: () => ok(api.GET("/api/skills/{skill_id}", { params: { path: { skill_id: id } } })) });
  return (
    <Modal title={data ? `${data.name} · v${data.version}` : "Skill"} onClose={onClose} wide footer={<span className="muted">{data?.description}</span>}>
      {!data ? <p className="muted" style={{ padding: 16 }}>Carregando…</p> : (
        <div className="skill-view">
          {data.file_paths.length > 0 && <p className="hint">Arquivos de referência: {data.file_paths.map((p) => <code key={p}>{p}</code>)}</p>}
          <pre className="preview-text">{data.body}</pre>
        </div>
      )}
    </Modal>
  );
}

export function SkillsSection() {
  const qc = useQueryClient();
  const notify = useApp((s) => s.notify);
  const { data: me } = useMe();
  const { data: skills = [], isLoading } = useSkills();
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const [view, setView] = useState<string | null>(null);
  const [all, setAll] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const refresh = () => void qc.invalidateQueries({ queryKey: ["skills"] });
  const patch = useMutation({
    mutationFn: ({ id, body }: { id: string; body: S["SkillPatch"] }) => ok(api.PATCH("/api/skills/{skill_id}", { params: { path: { skill_id: id } }, body })),
    onSuccess: refresh, onError: (e: Error) => notify(full(e)),
  });
  const del = useMutation({
    mutationFn: (id: string) => ok(api.DELETE("/api/skills/{skill_id}", { params: { path: { skill_id: id } } })),
    onSuccess: () => { refresh(); notify("Skill apagada."); }, onError: (e: Error) => notify(full(e)),
  });
  const [drag, setDrag] = useState(false);
  const send = async (files: File[]) => {
    setBusy(true);
    const r = await importSkillFiles(files);
    setBusy(false);
    refresh();
    notify(importSummary(r));
    if (r.fails.length) alert(r.fails.join("\n"));
  };
  const found = skills.filter((s) => !q || `${s.name} ${s.description}`.toLowerCase().includes(q.toLowerCase()));
  const shown = all || q ? found : found.slice(0, 8);
  const mine = skills.filter((s) => s.mine);

  return (
    <section className={`grp ${drag ? "dropping" : ""}`} id="skills"
      onDragOver={(e) => { e.preventDefault(); setDrag(true); }} onDragLeave={() => setDrag(false)}
      onDrop={(e) => { e.preventDefault(); setDrag(false); const f = [...e.dataTransfer.files]; if (f.length) void send(f); }}>
      <h3>Skills</h3>
      <p className="hint">Pacotes de instruções no formato das skills do Claude: um <code>SKILL.md</code> com <code>name</code> e <code>description</code> no
        cabeçalho, ou um <code>.zip</code>/<code>.skill</code> com várias pastas (cada uma com o seu <code>SKILL.md</code> e referências). Ative cada skill nos
        agentes ou numa conversa; o agente lê a descrição e carrega a skill quando a tarefa combina. Enviar de novo uma skill com o mesmo nome cria uma versão nova.</p>
      <div className="kbact">
        <button className="btn" disabled={busy} onClick={() => input.current?.click()}>{busy ? "Importando…" : "Enviar skills"}</button>
        <input ref={input} type="file" hidden multiple accept=".md,.markdown,.zip,.skill"
          onChange={(e) => { const f = [...(e.target.files ?? [])]; e.target.value = ""; if (f.length) void send(f); }} />
        <span className="muted">ou arraste os arquivos para cá · {mine.length} suas{skills.length > mine.length ? ` · ${skills.length - mine.length} compartilhada(s)` : ""}</span>
      </div>
      {skills.length > 6 && <div className="field"><input type="search" placeholder="Buscar skill" aria-label="Buscar skill" value={q} onChange={(e) => setQ(e.target.value)} /></div>}
      {isLoading ? <p className="muted">Carregando…</p> : !skills.length ? <p className="muted">Nenhuma skill ainda.</p> : (
        <ul className="skills">
          {shown.map((s: Skill) => (
            <li key={s.id} className={s.enabled ? "" : "off"}>
              <div className="smeta">
                <b>{s.name}</b> <small className="muted">v{s.version} · {kb(s.size_bytes)}{s.files ? ` · ${s.files} arquivo(s)` : ""}</small>
                {s.shared && <span className="tag">{s.mine ? "compartilhada" : "da casa"}</span>}
                <p>{s.description}</p>
                <small className="muted">{s.agents ? `em ${s.agents} agente(s)` : "em nenhum agente"}{s.conversations ? ` · ${s.conversations} conversa(s)` : ""}</small>
              </div>
              <div className="sact">
                {s.mine && <label className="sw mini"><input type="checkbox" checked={s.enabled} onChange={(e) => patch.mutate({ id: s.id, body: { enabled: e.target.checked } })} /><i aria-hidden /><span className="sr">Ativa</span></label>}
                <button className="btn ghost sm" onClick={() => setView(s.id)}>Ver</button>
                {s.mine && me?.is_admin && <button className="btn ghost sm" onClick={() => patch.mutate({ id: s.id, body: { shared: !s.shared } })}>{s.shared ? "Parar de compartilhar" : "Compartilhar com todos"}</button>}
                {s.mine && <button className="btn danger sm" onClick={() => confirm(`Apagar a skill "${s.name}"? Ela sai de todos os agentes e conversas.`) && del.mutate(s.id)}>Apagar</button>}
              </div>
            </li>
          ))}
        </ul>
      )}
      {!q && found.length > 8 && <div><button className="btn ghost" onClick={() => setAll(!all)}>{all ? "Mostrar menos" : `Mostrar todas (${found.length})`}</button></div>}
      {view && <SkillView id={view} onClose={() => setView(null)} />}
    </section>
  );
}

/** Lista de skills marcáveis, usada no diálogo do agente e no da conversa. */
export function SkillChecklist({ value, onChange }: { value: string[]; onChange: (ids: string[]) => void }) {
  const { data: skills = [] } = useSkills();
  const usable = skills.filter((s) => s.enabled);
  if (!usable.length) return <p className="hint">Nenhuma skill ativa. Envie em Configuração → Skills.</p>;
  return (
    <div className="pick">
      {usable.map((s) => (
        <label key={s.id} title={s.description}>
          <input type="checkbox" checked={value.includes(s.id)} onChange={(e) => onChange(e.target.checked ? [...value, s.id] : value.filter((x) => x !== s.id))} />
          <span><b>{s.name}</b><small className="muted"> — {s.description.slice(0, 90)}{s.description.length > 90 ? "…" : ""}</small></span>
        </label>
      ))}
    </div>
  );
}

/** Skills do agente: carrega e salva junto com o diálogo do agente. */
export function AgentSkills({ agentId }: { agentId: string }) {
  const notify = useApp((s) => s.notify);
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["agentSkills", agentId], queryFn: () => ok(api.GET("/api/agents/{agent_id}/skills", { params: { path: { agent_id: agentId } } })) });
  const [ids, setIds] = useState<string[]>([]);
  useEffect(() => setIds(data?.skill_ids ?? []), [data]);
  const save = useMutation({
    mutationFn: (next: string[]) => ok(api.PUT("/api/agents/{agent_id}/skills", { params: { path: { agent_id: agentId } }, body: { skill_ids: next } })),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ["agentSkills", agentId] }); void qc.invalidateQueries({ queryKey: ["skills"] }); },
    onError: (e: Error) => notify(full(e)),
  });
  return (
    <div className="field"><label>Skills do agente</label>
      <SkillChecklist value={ids} onChange={(n) => { setIds(n); save.mutate(n); }} />
    </div>
  );
}

export function ConversationSkills({ id, title, onClose }: { id: string; title: string; onClose: () => void }) {
  const notify = useApp((s) => s.notify);
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["convSkills", id], queryFn: () => ok(api.GET("/api/conversations/{cid}/skills", { params: { path: { cid: id } } })) });
  const [ids, setIds] = useState<string[] | null>(null);
  useEffect(() => { if (data && ids === null) setIds(data.skill_ids ?? []); }, [data, ids]);
  const save = useMutation({
    mutationFn: () => ok(api.PUT("/api/conversations/{cid}/skills", { params: { path: { cid: id } }, body: { skill_ids: ids ?? [] } })),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ["convSkills", id] }); void qc.invalidateQueries({ queryKey: ["skills"] }); notify("Skills da conversa salvas."); onClose(); },
    onError: (e: Error) => notify(full(e)),
  });
  return (
    <Modal title={`Skills · ${title}`} onClose={onClose}
      footer={<><span className="muted">Valem para todos os agentes desta conversa, além das skills de cada agente.</span>
        <button className="btn" disabled={save.isPending || ids === null} onClick={() => save.mutate()}>Salvar</button></>}>
      {ids === null ? <p className="muted">Carregando…</p> : <SkillChecklist value={ids} onChange={setIds} />}
    </Modal>
  );
}
