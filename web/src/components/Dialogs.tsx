import { useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";

import { api, ok, upload, type Doc } from "../api/client";
import { openDm, useAgentDocs, useAgents, useConversations } from "../queries";
import { useApp } from "../store";
import { AgentHub } from "./HubDocs";
import { AgentSkills, importSkillFiles, importSummary, isSkillFile } from "./Skills";
import { Avatar, COLORS, EMOJIS, kb, Modal } from "./ui";

function docLabel(d: Doc, live?: string): string {
  const st = live ?? d.status;
  if (st === "pending") return "lendo…";
  if (st === "failed" || st === "unreadable") return d.note ?? "não legível";
  if (d.kind === "pdf") return `${d.pages ?? d.parts} pág.`;
  if (d.sheets.length) return d.sheets.map((s) => `${s.stored_rows} linhas`).join(" + ");
  return d.parts ? `${d.parts} seç.` : kb(d.size_bytes);
}

export function AgentDialog({ id }: { id?: string }) {
  const qc = useQueryClient();
  const { data: agents = [] } = useAgents();
  const { data: convs = [] } = useConversations();
  const agent = agents.find((a) => a.id === id);
  const { data: docs = [] } = useAgentDocs(id);
  const { setDialog, setView, notify, docStatus } = useApp();
  const [name, setName] = useState(agent?.name ?? "");
  const [emoji, setEmoji] = useState(agent?.emoji ?? EMOJIS[agents.length % EMOJIS.length]!);
  const [color, setColor] = useState(agent?.color ?? COLORS[agents.length % COLORS.length]!);
  const [persona, setPersona] = useState(agent?.persona ?? "");
  const [uploading, setUploading] = useState<string[]>([]);
  const [saving, setSaving] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const close = () => setDialog(null);
  const refresh = () => Promise.all([qc.invalidateQueries({ queryKey: ["agents"] }), qc.invalidateQueries({ queryKey: ["agentDocs", id] })]);

  const save = async () => {
    if (!name.trim()) return notify("Dê um nome ao agente.");
    setSaving(true);
    try {
      if (agent) {
        await ok(api.PATCH("/api/agents/{agent_id}", { params: { path: { agent_id: agent.id } }, body: { name, emoji, color, persona } }));
        await refresh();
        close();
      } else {
        const a = await ok(api.POST("/api/agents", { body: { name, emoji, color, persona } }));
        await qc.invalidateQueries({ queryKey: ["agents"] });
        const c = await openDm(a.id);
        await qc.invalidateQueries({ queryKey: ["conversations"] });
        setDialog({ kind: "agent", id: a.id });           // continua aberto para adicionar arquivos
        setView({ kind: "chat", id: c.id });
        notify("Agente criado. Adicione arquivos à base, se quiser.");
      }
    } catch (e) {
      notify((e as Error).message);
    } finally {
      setSaving(false);
    }
  };

  const addFiles = async (all: File[]) => {
    if (!agent) return;
    const skillFiles = all.filter((f) => isSkillFile(f.name));
    const files = all.filter((f) => !isSkillFile(f.name));
    if (skillFiles.length) {               // .skill não é documento: vira skill e já fica ativa neste agente
      setUploading((u) => [...u, ...skillFiles.map((f) => f.name)]);
      const r = await importSkillFiles(skillFiles);
      if (r.ids.length) {
        const cur = await ok(api.GET("/api/agents/{agent_id}/skills", { params: { path: { agent_id: agent.id } } }));
        await ok(api.PUT("/api/agents/{agent_id}/skills", { params: { path: { agent_id: agent.id } },
          body: { skill_ids: [...new Set([...(cur.skill_ids ?? []), ...r.ids])] } }));
        await Promise.all(["agentSkills", "skills"].map((k) => qc.invalidateQueries({ queryKey: [k] })));
      }
      setUploading((u) => u.filter((n) => !skillFiles.some((f) => f.name === n)));
      notify(`${importSummary(r)} · ativas em ${agent.name}`);
      if (r.fails.length) alert(r.fails.join("\n"));
    }
    for (const f of files) {
      setUploading((u) => [...u, f.name]);
      try {
        await upload(`/api/agents/${agent.id}/documents`, f);
        await refresh();
      } catch (e) {
        notify(`${f.name}: ${(e as Error).message}`);
      } finally {
        setUploading((u) => u.filter((n) => n !== f.name));
      }
    }
  };

  const convertDoc = async (d: Doc) => {
    try {
      const r = await ok(api.POST("/api/documents/{document_id}/as-skill", { params: { path: { document_id: d.id } } }));
      await refresh();
      await Promise.all(["agentSkills", "skills"].map((k) => qc.invalidateQueries({ queryKey: [k] })));
      notify(`${importSummary({ ...r, created: r.created.length, updated: r.updated.length, fails: [] })} · ativa neste agente`);
    } catch (e) {
      notify((e as Error).message);
    }
  };

  const removeDoc = async (d: Doc) => {
    if (!agent) return;
    try {
      await ok(api.DELETE("/api/agents/{agent_id}/documents/{document_id}", { params: { path: { agent_id: agent.id, document_id: d.id } } }));
      await refresh();
    } catch (e) {
      notify((e as Error).message);
    }
  };

  const remove = async () => {
    if (!agent || !confirm(`Excluir ${agent.name}? A conversa individual e os arquivos da base também serão apagados.`)) return;
    try {
      await ok(api.DELETE("/api/agents/{agent_id}", { params: { path: { agent_id: agent.id } } }));
      await Promise.all([qc.invalidateQueries({ queryKey: ["agents"] }), qc.invalidateQueries({ queryKey: ["conversations"] })]);
      close();
      setView({ kind: "welcome" });
    } catch (e) {
      notify((e as Error).message);
    }
  };

  const dm = agent && convs.find((c) => c.kind === "dm" && c.agent_id === agent.id);
  return (
    <Modal title={agent ? "Editar agente" : "Novo agente"} onClose={close}
      footer={<>
        {agent ? <button className="btn danger" onClick={() => void remove()}>Excluir agente</button> : <span />}
        <div className="row-gap">
          {agent && !dm && <button className="btn ghost" onClick={async () => { const c = await openDm(agent.id); close(); setView({ kind: "chat", id: c.id }); }}>Conversar</button>}
          <button className="btn" disabled={saving} onClick={() => void save()}>{agent ? "Salvar" : "Criar agente"}</button>
        </div>
      </>}>
      <div className="field"><label htmlFor="aName">Nome</label><input id="aName" type="text" maxLength={40} value={name} onChange={(e) => setName(e.target.value)} placeholder="Ex.: Analista de PCP" /></div>
      <div className="field"><label>Ícone</label><div className="emojis">{EMOJIS.map((e) => <button key={e} type="button" className={e === emoji ? "on" : ""} onClick={() => setEmoji(e)}>{e}</button>)}</div></div>
      <div className="field"><label>Cor</label><div className="colors">{COLORS.map((c) => <button key={c} type="button" aria-label={`Cor ${c}`} className={c === color ? "on" : ""} style={{ background: c }} onClick={() => setColor(c)} />)}</div></div>
      <div className="field"><label htmlFor="aPer">Personalidade e função</label><textarea id="aPer" maxLength={4000} value={persona} onChange={(e) => setPersona(e.target.value)} placeholder="Ex.: Especialista em contratos. Responde de forma objetiva e cita a cláusula." /></div>
      <div className="field">
        <label>Base de arquivos</label>
        {!agent ? <div className="hint">Crie o agente para adicionar arquivos à base dele.</div> : (
          <>
            <div className="kb">
              {docs.map((d) => (
                <div key={d.id} className="kbitem">
                  <span>{d.kind === "table" ? "📊" : "📄"} {d.filename}</span>
                  <small className={(docStatus[d.id] ?? d.status) === "failed" ? "warn" : ""}>{docLabel(d, docStatus[d.id])}</small>
                  {isSkillFile(d.filename) && <button className="ok" onClick={() => void convertDoc(d)}>Importar como skill</button>}
                  <button onClick={() => void removeDoc(d)}>Remover</button>
                </div>
              ))}
              {uploading.map((n) => <div key={n} className="kbitem"><span>⏳ {n}</span><small>enviando…</small></div>)}
              {!docs.length && !uploading.length && <div className="hint">Nenhum arquivo. O agente responde com conhecimento geral.</div>}
            </div>
            <div className="kbact"><button type="button" className="btn ghost" onClick={() => fileRef.current?.click()}>Adicionar arquivos</button></div>
            <input ref={fileRef} type="file" multiple hidden
              onChange={(e) => { const fs = [...(e.target.files ?? [])]; e.target.value = ""; void addFiles(fs); }} />
            <div className="hint">Até 50 MB cada. Lê PDF, Word, Excel, CSV, PowerPoint, OpenDocument (.odt/.ods/.odp), RTF, e-mail (.eml), Jupyter, EPUB, HTML,
              Markdown, código e .zip com documentos. Arquivos .skill viram skills deste agente. O agente busca, lê e calcula citando a fonte.</div>
          </>
        )}
      </div>
      <div>
        {agent && <AgentHub agentId={agent.id} />}
        {agent ? <AgentSkills agentId={agent.id} /> : <div className="field"><label>Skills do agente</label><div className="hint">Crie o agente para escolher as skills dele.</div></div>}
      </div>
    </Modal>
  );
}

export function GroupDialog({ id }: { id?: string }) {
  const qc = useQueryClient();
  const { data: agents = [] } = useAgents();
  const { data: convs = [] } = useConversations();
  const g = convs.find((c) => c.id === id);
  const { setDialog, setView, notify } = useApp();
  const [name, setName] = useState(g?.name ?? "");
  const [members, setMembers] = useState<string[]>(g?.members ?? []);
  const close = () => setDialog(null);

  const save = async () => {
    if (!name.trim()) return notify("Dê um nome ao grupo.");
    if (!members.length) return notify("Escolha pelo menos um agente.");
    try {
      const c = g
        ? await ok(api.PATCH("/api/conversations/{cid}", { params: { path: { cid: g.id } }, body: { name, members } }))
        : await ok(api.POST("/api/conversations", { body: { kind: "group", name, members, emoji: "👥", color: COLORS[(convs.length + 3) % COLORS.length]! } }));
      await qc.invalidateQueries({ queryKey: ["conversations"] });
      close();
      setView({ kind: "chat", id: c.id });
    } catch (e) {
      notify((e as Error).message);
    }
  };
  const remove = async () => {
    if (!g || !confirm(`Apagar o grupo ${g.name} e todas as mensagens?`)) return;
    try {
      await ok(api.DELETE("/api/conversations/{cid}", { params: { path: { cid: g.id } } }));
      await qc.invalidateQueries({ queryKey: ["conversations"] });
      close();
      setView({ kind: "welcome" });
    } catch (e) {
      notify((e as Error).message);
    }
  };
  return (
    <Modal title={g ? "Dados do grupo" : "Novo grupo"} onClose={close}
      footer={<>{g ? <button className="btn danger" onClick={() => void remove()}>Apagar grupo</button> : <span />}<button className="btn" onClick={() => void save()}>{g ? "Salvar" : "Criar grupo"}</button></>}>
      <div className="field"><label htmlFor="gName">Nome do grupo</label><input id="gName" type="text" maxLength={50} value={name} onChange={(e) => setName(e.target.value)} placeholder="Ex.: Comitê de produção" /></div>
      <div className="field">
        <label>Participantes</label>
        <div className="pick">
          {agents.map((a) => (
            <label key={a.id}>
              <input type="checkbox" checked={members.includes(a.id)} onChange={(e) => setMembers((m) => (e.target.checked ? [...m, a.id] : m.filter((x) => x !== a.id)))} />
              <Avatar emoji={a.emoji} color={a.color} small /><span>{a.name}</span>
            </label>
          ))}
        </div>
        <div className="hint">No grupo, o agente certo responde conforme o assunto. Use @nome para chamar alguém ou "pessoal" para todos.</div>
      </div>
    </Modal>
  );
}
