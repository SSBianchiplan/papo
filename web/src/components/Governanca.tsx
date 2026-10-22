// Aba Governança de IA: Consultor de IA, fichas de governança dos agentes (editar, ativar, desativar), opções por conversa,
// Modelo de Camadas (SPEC-GPS-CAMADAS-001) como referência, eventos de gatilho e a rubrica versionada (administrador).
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { api, ApiError, downloadDocument, ok } from "../api/client";
import { useMe } from "../queries";
import { useApp } from "../store";
import { Modal } from "./ui";

const full = (e: Error) => (e instanceof ApiError && e.hint ? `${e.message} ${e.hint}` : e.message);
const NOMES: Record<number, string> = { 1: "Clássica", 2: "Aprendizado de máquina", 3: "Redes neurais", 4: "Deep learning", 5: "Generativa", 6: "Agêntica" };
const VEREDITO: Record<string, string> = { PRONTA_PARA_AVANCAR: "Pronta para avançar", AVANCAR_COM_CONDICOES: "Avançar com condições", NAO_AVANCAR_AINDA: "Não avançar ainda" };
const ESTADO_AV: Record<string, string> = { aguardando_documento: "aguardando proposta", lendo: "lendo", triagem: "triagem", avaliando: "avaliando",
  entrevista: "entrevista", confirmando: "entrevista", calculando: "calculando", parecer: "parecer selado", contestacao: "contestação", rebaixado: "parado (gatilho)" };
const TOOLS = ["listar_documentos", "buscar_nos_documentos", "ler_documento", "analisar_planilha", "buscar_na_conversa", "usar_skill", "hub_buscar", "hub_ler", "gerar_arquivo"];
const WRITE: Record<string, string> = { gerar_arquivo: "escrita_propria" };

type Ferr = { nome: string; tipo: string };
type Ficha = {
  agent_id: string; agent_name: string; kind: string; dono: string; camada_real: number | null; nivel: string; fontes: string[]; ferramentas: Ferr[];
  raio_acao: string; max_iteracoes: number | null; max_custo_conversa_usd: number | null; max_segundos_turno: number | null; aprovacao_humana: string[];
  gatilhos: string[]; canais: string[]; retencao_dias: number; camadas_no_contexto: boolean; uso_interno_evidencia: boolean; excecao_m3: string | null;
  ativo: boolean; versao: number; completa: boolean; faltando: string[]; permissao_matriz: string; atualizado_em: string;
};
type Modelo = { versao: string; camadas: Record<string, string | number>[]; matriz: Record<string, Record<string, string>>; niveis: Record<string, string>;
  gatilhos: Record<string, string>; transversais: { elemento: string; exigencia: string; criterio: string }[] };

const useModelo = () => useQuery({ queryKey: ["gov-modelo"], queryFn: () => ok(api.GET("/api/governanca/modelo")) as Promise<unknown> as Promise<Modelo>, staleTime: Infinity });
const useFichas = () => useQuery({ queryKey: ["gov-fichas"], queryFn: () => ok(api.GET("/api/governanca/fichas")) as Promise<unknown> as Promise<Ficha[]> });

// ----------------------------------------------------------------- Consultor de IA
function ConsultorCard() {
  const qc = useQueryClient();
  const { notify, setView } = useApp();
  const { data: fichas = [] } = useFichas();
  const consultor = fichas.find((f) => f.kind === "consultor");
  const { data: avs = [] } = useQuery({ queryKey: ["gov-avaliacoes"], queryFn: () => ok(api.GET("/api/governanca/consultor/avaliacoes")) as Promise<unknown> as Promise<Record<string, unknown>[]> });
  const ativar = useMutation({
    mutationFn: () => ok(api.POST("/api/governanca/consultor/ativar")) as Promise<unknown> as Promise<{ conversation_id: string }>,
    onSuccess: (r) => { ["gov-fichas", "agents", "conversations"].forEach((k) => void qc.invalidateQueries({ queryKey: [k] })); setView({ kind: "chat", id: r.conversation_id }); },
    onError: (e: Error) => notify(full(e)),
  });
  return (
    <section className="grp"><h3>Consultor de IA</h3>
      <p className="hint">Contato que recebe a proposta de IA (PDF ou Word), classifica a camada real, pergunta só o que faltar no documento e entrega
        parecer com nota determinística, condições e PDF selado. A nota vem da rubrica, nunca do texto da IA (SPEC-GPS-PAPO-CIA-001).</p>
      <p className="note">Onda 1 · uso interno. Gates da spec ainda em aberto: G07 (suíte adversarial), G08 (teste de isolamento em paralelo),
        G10 (conjunto ouro com avaliadores humanos), G12 (conferência automática do PDF), G13 e G14 (tempo e custo p95). O parecer é insumo, não decisão.</p>
      <div className="kbact">
        <button className="btn" disabled={ativar.isPending} onClick={() => ativar.mutate()}>{consultor ? "Abrir conversa com o Consultor" : "Ativar o Consultor de IA"}</button>
        {consultor && <span className={`badge ${consultor.ativo ? "ok" : "bad"}`}>{consultor.ativo ? `ativo · ${consultor.nivel}` : "desativado"}</span>}
      </div>
      {avs.length > 0 && (
        <div className="tbl-wrap"><table className="tbl">
          <thead><tr><th>Proposta</th><th>Situação</th><th>Camada real</th><th>Nota</th><th>Veredito</th><th /></tr></thead>
          <tbody>{avs.map((a) => (
            <tr key={String(a.id)}>
              <td>{String(a.titulo ?? "—")}</td><td>{ESTADO_AV[String(a.estado)] ?? String(a.estado)}</td>
              <td>{a.camada_real ? `${a.camada_real} · ${NOMES[Number(a.camada_real)]}` : "—"}</td>
              <td>{a.nota_geral != null ? `${a.nota_geral} (v${a.parecer_versao})` : "—"}</td>
              <td>{a.veredito ? VEREDITO[String(a.veredito)] : "—"}</td>
              <td><div className="row-gap">
                <button className="btn ghost sm" onClick={() => setView({ kind: "chat", id: String(a.conversation_id) })}>Abrir</button>
                {a.pdf_document_id ? <button className="btn ghost sm" onClick={() => void downloadDocument(String(a.pdf_document_id), `parecer-v${a.parecer_versao}.pdf`)}>PDF</button> : null}
              </div></td>
            </tr>))}</tbody>
        </table></div>
      )}
    </section>
  );
}

// ----------------------------------------------------------------- fichas
function FichaForm({ f, onClose }: { f: Ficha; onClose: () => void }) {
  const qc = useQueryClient();
  const notify = useApp((s) => s.notify);
  const { data: me } = useMe();
  const { data: modelo } = useModelo();
  const [x, setX] = useState<Ficha>(f);
  const set = <K extends keyof Ficha>(k: K, v: Ficha[K]) => setX((o) => ({ ...o, [k]: v }));
  const toggle = (k: "gatilhos" | "canais" | "aprovacao_humana", v: string) => set(k, x[k].includes(v) ? x[k].filter((y) => y !== v) : [...x[k], v]);
  const hasTool = (n: string) => x.ferramentas.some((t) => t.nome === n);
  const toolList = f.kind === "consultor" ? f.ferramentas.map((t) => t.nome) : TOOLS;
  const save = useMutation({
    mutationFn: () => ok(api.PUT("/api/governanca/fichas/{agent_id}", { params: { path: { agent_id: f.agent_id } }, body: {
      dono: x.dono, camada_real: x.camada_real, nivel: x.nivel as "M0", fontes: x.fontes, ferramentas: x.ferramentas as { nome: string; tipo: "leitura" }[],
      raio_acao: x.raio_acao, max_iteracoes: x.max_iteracoes, max_custo_conversa_usd: x.max_custo_conversa_usd, max_segundos_turno: x.max_segundos_turno,
      aprovacao_humana: x.aprovacao_humana, gatilhos: x.gatilhos as "T1"[], canais: x.canais as "direto"[], retencao_dias: x.retencao_dias,
      camadas_no_contexto: x.camadas_no_contexto, uso_interno_evidencia: x.uso_interno_evidencia, excecao_m3: x.excecao_m3 || null, ativo: x.ativo } })),
    onSuccess: () => { ["gov-fichas", "agents"].forEach((k) => void qc.invalidateQueries({ queryKey: [k] })); notify("Ficha salva (nova versão registrada)."); onClose(); },
    onError: (e: Error) => notify(full(e)),
  });
  const perm = modelo && x.camada_real ? modelo.matriz[String(x.camada_real)]?.[x.nivel] : undefined;
  const num = (v: string) => (v.trim() === "" ? null : Number(v.replace(",", ".")));
  return (
    <Modal title={`Ficha de governança · ${f.agent_name}`} onClose={onClose} wide
      footer={<><span className="muted">versão {f.versao} · promoção para M2/M3 só por administrador</span>
        <button className="btn" disabled={save.isPending} onClick={() => save.mutate()}>Salvar ficha</button></>}>
      <div className="ficha-form">
        <div className="row3">
          <div className="field"><label htmlFor="fDono">Dono humano</label><input id="fDono" type="text" value={x.dono} onChange={(e) => set("dono", e.target.value)} />
            <div className="hint">Pessoa que responde por falhas e decide promoção. Sem dono, não ativa.</div></div>
          <div className="field"><label htmlFor="fCam">Camada real</label>
            <select id="fCam" value={x.camada_real ?? ""} onChange={(e) => set("camada_real", e.target.value ? Number(e.target.value) : null)}>
              <option value="">—</option>{[1, 2, 3, 4, 5, 6].map((n) => <option key={n} value={n}>{n} · {NOMES[n]}</option>)}</select>
            <div className="hint">Pelo que o agente faz, não pelo que diz.</div></div>
          <div className="field"><label htmlFor="fNiv">Moderação</label>
            <select id="fNiv" value={x.nivel} onChange={(e) => set("nivel", e.target.value)}>
              {["M0", "M1", "M2", "M3"].map((n) => <option key={n} value={n} disabled={(n === "M2" || n === "M3") && !me?.is_admin && f.nivel !== n}>{n} · {modelo?.niveis[n]?.split(":")[0]}</option>)}</select>
            <div className={`hint ${perm === "Proibido" ? "warn" : ""}`}>Matriz: {perm ?? "—"}</div></div>
        </div>
        {x.nivel === "M3" && x.camada_real === 6 && <div className="field"><label htmlFor="fExc">Exceção aprovada (raio de ação, rollback provado, kill-switch)</label>
          <textarea id="fExc" value={x.excecao_m3 ?? ""} onChange={(e) => set("excecao_m3", e.target.value)} /></div>}
        {x.nivel === "M2" && x.camada_real === 5 && <label className="sw"><span><b>Uso interno com evidência acumulada</b><small>Exigido para M2 na camada generativa.</small></span>
          <input type="checkbox" checked={x.uso_interno_evidencia} onChange={(e) => set("uso_interno_evidencia", e.target.checked)} /><i aria-hidden /></label>}
        <div className="field"><label>Ferramentas (lista fechada)</label>
          <div className="chips">{toolList.map((n) => (
            <label key={n} className={`chipck ${hasTool(n) ? "on" : ""}`}><input type="checkbox" checked={hasTool(n)} disabled={f.kind === "consultor"}
              onChange={() => set("ferramentas", hasTool(n) ? x.ferramentas.filter((t) => t.nome !== n) : [...x.ferramentas, { nome: n, tipo: WRITE[n] ?? "leitura" }])} />
              <code>{n}</code><small>{(x.ferramentas.find((t) => t.nome === n)?.tipo ?? WRITE[n] ?? "leitura").replace("_", " ")}</small></label>))}</div>
          <div className="hint">Ferramenta fora da lista não é oferecida ao modelo; se ele tentar, é recusada e registrada como T8. M0 nunca recebe escrita.</div></div>
        <div className="field"><label htmlFor="fRaio">Raio de ação</label><input id="fRaio" type="text" value={x.raio_acao} onChange={(e) => set("raio_acao", e.target.value)} /></div>
        <div className="row3">
          <div className="field"><label htmlFor="fIt">Máx. iterações por turno</label><input id="fIt" type="text" inputMode="numeric" value={x.max_iteracoes ?? ""} onChange={(e) => set("max_iteracoes", num(e.target.value))} /></div>
          <div className="field"><label htmlFor="fCu">Teto de custo por conversa (US$)</label><input id="fCu" type="text" inputMode="decimal" value={x.max_custo_conversa_usd ?? ""} onChange={(e) => set("max_custo_conversa_usd", num(e.target.value))} /></div>
          <div className="field"><label htmlFor="fSe">Máx. segundos por turno</label><input id="fSe" type="text" inputMode="numeric" value={x.max_segundos_turno ?? ""} onChange={(e) => set("max_segundos_turno", num(e.target.value))} /></div>
        </div>
        <div className="field"><label>Canais</label><div className="chips">
          {[["direto", "Conversa 1:1"], ["grupo", "Grupos"], ["mencao", "Grupos, só quando mencionado"]].map(([k, l]) => (
            <label key={k} className={`chipck ${x.canais.includes(k!) ? "on" : ""}`}><input type="checkbox" checked={x.canais.includes(k!)} onChange={() => toggle("canais", k!)} />{l}</label>))}</div></div>
        <div className="field"><label>Gatilhos de rebaixamento para M1</label><div className="chips">
          {Object.entries(modelo?.gatilhos ?? {}).map(([k, d]) => (
            <label key={k} className={`chipck ${x.gatilhos.includes(k) ? "on" : ""}`} title={d}><input type="checkbox" checked={x.gatilhos.includes(k)} onChange={() => toggle("gatilhos", k)} />
              <b>{k}</b><small>{d}</small></label>))}</div></div>
        <div className="row3">
          <div className="field"><label htmlFor="fRet">Retenção (dias)</label><input id="fRet" type="text" inputMode="numeric" value={x.retencao_dias} onChange={(e) => set("retencao_dias", Number(e.target.value) || 90)} /></div>
          <div className="field"><label htmlFor="fFon">Fontes de dados</label><input id="fFon" type="text" value={x.fontes.join(", ")} onChange={(e) => set("fontes", e.target.value.split(",").map((y) => y.trim()).filter(Boolean))} /></div>
          <div className="field"><label htmlFor="fApr">Exigem aprovação humana</label><input id="fApr" type="text" value={x.aprovacao_humana.join(", ")} onChange={(e) => set("aprovacao_humana", e.target.value.split(",").map((y) => y.trim()).filter(Boolean))} /></div>
        </div>
        <label className="sw"><span><b>Modelo de Camadas no contexto</b><small>O agente conhece a SPEC-GPS-CAMADAS-001 e classifica propostas por ela.</small></span>
          <input type="checkbox" checked={x.camadas_no_contexto} onChange={(e) => set("camadas_no_contexto", e.target.checked)} /><i aria-hidden /></label>
        <label className="sw"><span><b>Ativo</b><small>Só com ficha completa e dono (I4). Inativo não responde em nenhuma conversa.</small></span>
          <input type="checkbox" checked={x.ativo} onChange={(e) => set("ativo", e.target.checked)} /><i aria-hidden /></label>
      </div>
    </Modal>
  );
}

function FichasCard() {
  const qc = useQueryClient();
  const notify = useApp((s) => s.notify);
  const { data: fichas = [] } = useFichas();
  const [edit, setEdit] = useState<Ficha | null>(null);
  const ativo = useMutation({
    mutationFn: ({ id, v }: { id: string; v: boolean }) => ok(api.PATCH("/api/governanca/fichas/{agent_id}/ativo", { params: { path: { agent_id: id }, query: { ativo: v } } })),
    onSuccess: () => ["gov-fichas", "agents"].forEach((k) => void qc.invalidateQueries({ queryKey: [k] })),
    onError: (e: Error) => notify(full(e)),
  });
  return (
    <section className="grp"><h3>Fichas de governança dos agentes</h3>
      <p className="hint">Nenhum agente responde sem ficha completa e ativa. O motor aplica a ficha em código: lista fechada de ferramentas, moderação, teto de custo,
        tempo e iterações por turno, canais e gatilhos T1–T8 (rebaixam para M1 e ficam registrados).</p>
      <div className="tbl-wrap"><table className="tbl fichas">
        <thead><tr><th>Agente</th><th>Camada</th><th>Moderação</th><th>Ficha</th><th>Ativo</th><th /></tr></thead>
        <tbody>{fichas.map((f) => (
          <tr key={f.agent_id} className={f.ativo ? "" : "off"}>
            <td><b>{f.agent_name}</b>{f.kind === "consultor" && <span className="tag">consultor</span>}<br /><small className="muted">dono: {f.dono || "—"} · v{f.versao}</small></td>
            <td>{f.camada_real ? `${f.camada_real} · ${NOMES[f.camada_real]}` : "—"}</td>
            <td><b>{f.nivel}</b><br /><small className="muted">{f.permissao_matriz}</small></td>
            <td>{f.completa ? <span className="badge ok">completa</span> : <span className="badge bad" title={f.faltando.join(", ")}>falta {f.faltando.length}</span>}</td>
            <td><label className="sw mini"><input type="checkbox" checked={f.ativo} onChange={(e) => ativo.mutate({ id: f.agent_id, v: e.target.checked })} /><i aria-hidden /><span className="sr">Ativo</span></label></td>
            <td><button className="btn ghost sm" onClick={() => setEdit(f)}>Editar</button></td>
          </tr>))}</tbody>
      </table></div>
      {edit && <FichaForm f={edit} onClose={() => setEdit(null)} />}
    </section>
  );
}

// ----------------------------------------------------------------- por conversa
export function ConversaGovernanca({ id, onDone }: { id?: string; onDone?: () => void }) {
  const qc = useQueryClient();
  const notify = useApp((s) => s.notify);
  const { data: convs = [] } = useQuery({ queryKey: ["gov-conversas"], queryFn: () => ok(api.GET("/api/governanca/conversas")) as Promise<unknown> as Promise<{ id: string; kind: string; titulo: string; camadas: boolean; consultor: boolean; agent_kind: string | null }[]> });
  const put = useMutation({
    mutationFn: ({ cid, camadas, consultor }: { cid: string; camadas: boolean; consultor: boolean }) =>
      ok(api.PUT("/api/governanca/conversas/{cid}", { params: { path: { cid } }, body: { camadas, consultor } })),
    onSuccess: () => { ["gov-conversas", "conversations"].forEach((k) => void qc.invalidateQueries({ queryKey: [k] })); onDone?.(); },
    onError: (e: Error) => notify(full(e)),
  });
  const list = convs.filter((c) => (!id || c.id === id) && c.agent_kind !== "consultor");
  if (!list.length) return <p className="muted">Nenhuma conversa.</p>;
  return (
    <div className="tbl-wrap"><table className="tbl">
      <thead><tr><th>Conversa</th><th>Modelo de Camadas no contexto</th><th>Consultor de IA (grupos, quando mencionado)</th></tr></thead>
      <tbody>{list.map((c) => (
        <tr key={c.id}><td>{c.kind === "group" ? "👥 " : "💬 "}{c.titulo}</td>
          <td><label className="sw mini"><input type="checkbox" checked={c.camadas} onChange={(e) => put.mutate({ cid: c.id, camadas: e.target.checked, consultor: c.consultor })} /><i aria-hidden /><span className="sr">Camadas</span></label></td>
          <td>{c.kind === "group" ? <label className="sw mini"><input type="checkbox" checked={c.consultor} onChange={(e) => put.mutate({ cid: c.id, camadas: c.camadas, consultor: e.target.checked })} /><i aria-hidden /><span className="sr">Consultor</span></label> : <small className="muted">só em grupos</small>}</td>
        </tr>))}</tbody>
    </table></div>
  );
}

// ----------------------------------------------------------------- modelo de camadas
function ModeloCard() {
  const { data: m } = useModelo();
  const [open, setOpen] = useState<number | null>(null);
  if (!m) return null;
  const ATTR: [string, string][] = [["componentes", "Componentes"], ["sinais", "Sinais de classificação"], ["quando", "Quando usar"],
    ["pergunta", "Pergunta decisiva"], ["teste", "Teste de sucesso"], ["controles", "Controles obrigatórios"], ["alerta", "Sinais de alerta"], ["moderacao", "Moderação máxima"]];
  return (
    <section className="grp"><h3>Modelo de Camadas da IA · v{m.versao}</h3>
      <p className="hint">Referência da SPEC-GPS-CAMADAS-001. Camada não é mérito: a certa é a mínima que resolve o trabalho com a evidência disponível;
        a camada real é a mais alta com sinal confirmado, não a declarada. A IA propõe, o humano decide. Não existe M4.</p>
      <div className="camadas">{m.camadas.map((c) => {
        const n = Number(c.n);
        return (
          <div key={n} className={`camada c${n} ${open === n ? "open" : ""}`}>
            <button className="camada-h" onClick={() => setOpen(open === n ? null : n)} aria-expanded={open === n}>
              <span className="cn">{n}</span><span><b>{String(c.nome)}</b><small>{String(c.definicao)}</small></span><span className="cm">{String(c.moderacao).split(";")[0]}</span></button>
            {open === n && <dl>{ATTR.map(([k, l]) => <div key={k}><dt>{l}</dt><dd>{String(c[k])}</dd></div>)}</dl>}
          </div>);
      })}</div>
      <div className="tbl-wrap"><table className="tbl matriz">
        <thead><tr><th>Camada</th>{["M0", "M1", "M2", "M3"].map((n) => <th key={n} title={m.niveis[n]}>{n}</th>)}</tr></thead>
        <tbody>{Object.entries(m.matriz).map(([k, row]) => (
          <tr key={k}><td>{k} · {NOMES[Number(k)]}</td>{["M0", "M1", "M2", "M3"].map((n) => (
            <td key={n} className={row[n] === "Proibido" ? "proib" : row[n] === "Livre" ? "livre" : "cond"}>{row[n]}</td>))}</tr>))}</tbody>
      </table></div>
      <div className="tbl-wrap"><table className="tbl">
        <thead><tr><th>Elemento transversal</th><th>Exigência mínima</th><th>Critério</th></tr></thead>
        <tbody>{m.transversais.map((t) => <tr key={t.elemento}><td><b>{t.elemento}</b></td><td>{t.exigencia}</td><td>{t.criterio}</td></tr>)}</tbody>
      </table></div>
    </section>
  );
}

function EventosCard() {
  const { data: ev = [] } = useQuery({ queryKey: ["gov-eventos"], queryFn: () => ok(api.GET("/api/governanca/eventos", { params: { query: { limit: 30 } } })) as Promise<unknown> as Promise<Record<string, string | null>[]>, refetchInterval: 30_000 });
  return (
    <section className="grp"><h3>Eventos de governança</h3>
      {!ev.length ? <p className="muted">Nenhum gatilho ou parada registrado.</p> : (
        <div className="tbl-wrap"><table className="tbl">
          <thead><tr><th>Quando</th><th>Código</th><th>Agente</th><th>O que houve</th><th>Moderação</th></tr></thead>
          <tbody>{ev.map((e, i) => (
            <tr key={i}><td>{new Date(String(e.em)).toLocaleString("pt-BR")}</td><td><span className="tag">{e.codigo}</span></td><td>{e.agente ?? "—"}</td>
              <td>{e.detalhe}{e.conversa ? <small className="muted"> · {e.conversa}</small> : null}</td><td>{e.nivel_antes}{e.nivel_depois !== e.nivel_antes ? ` → ${e.nivel_depois}` : ""}</td></tr>))}</tbody>
        </table></div>
      )}
    </section>
  );
}

// ----------------------------------------------------------------- rubrica (admin)
type Crit = { id: string; camada: string | number; texto: string; peso: number; critico: boolean; pergunta: string; respostas_rapidas: string[]; mapa_resposta: Record<string, string> };

function RubricaCard() {
  const qc = useQueryClient();
  const notify = useApp((s) => s.notify);
  const { data: vs = [] } = useQuery({ queryKey: ["gov-rubricas"], queryFn: () => ok(api.GET("/api/governanca/rubricas")) as Promise<unknown> as Promise<{ versao: string; ativa: boolean; nota: string; criada_em: string; definicao: { criterios: Crit[]; veredito: { limiar_pronta: number } } }[]> });
  const ativa = vs.find((v) => v.ativa);
  const [rows, setRows] = useState<Crit[]>([]);
  const [limiar, setLimiar] = useState(75);
  const [nota, setNota] = useState("");
  const [editing, setEditing] = useState(false);
  useEffect(() => { if (ativa) { setRows(ativa.definicao.criterios.map((c) => ({ ...c, mapa_resposta: Object.fromEntries(Object.entries(c.mapa_resposta).map(([k, v]) => [String(k), v])) }))); setLimiar(ativa.definicao.veredito.limiar_pronta); } }, [ativa?.versao]);
  const set = (i: number, patch: Partial<Crit>) => setRows((r) => r.map((c, j) => (j === i ? { ...c, ...patch } : c)));
  const salvar = useMutation({
    mutationFn: () => ok(api.POST("/api/governanca/rubricas", { body: { base: ativa!.versao, criterios: rows.map((c) => ({ ...c, mapa_resposta: c.mapa_resposta as Record<string, "LACUNA"> })), limiar_pronta: limiar, nota, ativar: true } })) as Promise<unknown> as Promise<{ versao: string; tipo: string }>,
    onSuccess: (r) => { void qc.invalidateQueries({ queryKey: ["gov-rubricas"] }); setEditing(false); setNota(""); notify(`Rubrica ${r.versao} (${r.tipo}) publicada e ativa. Pareceres já selados não mudam.`); },
    onError: (e: Error) => notify(full(e)),
  });
  const usar = useMutation({ mutationFn: (v: string) => ok(api.POST("/api/governanca/rubricas/{versao}/ativar", { params: { path: { versao: v } } })),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["gov-rubricas"] }), onError: (e: Error) => notify(full(e)) });
  if (!ativa) return null;
  return (
    <section className="grp"><h3>Administração · Rubrica do Consultor</h3>
      <p className="hint">Versionada como código: mudar texto ou pergunta gera versão patch; peso, crítico, critério novo ou limiar geram versão menor. Avaliação já selada
        nunca é recalculada. IDs são estáveis: critério removido fica obsoleto e não é reaproveitado.</p>
      <div className="row-gap">{vs.map((v) => (
        <span key={v.versao} className={`tag ${v.ativa ? "" : "off"}`} title={v.nota}>{v.versao}{v.ativa ? " · ativa" : ""}
          {!v.ativa && <button className="linkbtn" onClick={() => usar.mutate(v.versao)}>ativar</button>}</span>))}</div>
      {!editing ? <div><button className="btn ghost" onClick={() => setEditing(true)}>Editar critérios ({rows.length})</button></div> : (
        <>
          <div className="tbl-wrap"><table className="tbl edit rub">
            <thead><tr><th>ID</th><th>Critério</th><th>Peso</th><th>Crítico</th><th>Pergunta e respostas rápidas → estado</th></tr></thead>
            <tbody>{rows.map((c, i) => (
              <tr key={c.id}>
                <td><code>{c.id}</code></td>
                <td><input value={c.texto} onChange={(e) => set(i, { texto: e.target.value })} aria-label={`Texto ${c.id}`} /></td>
                <td><select value={c.peso} onChange={(e) => set(i, { peso: Number(e.target.value) })} aria-label={`Peso ${c.id}`}>{[1, 2, 3, 4, 5].map((n) => <option key={n}>{n}</option>)}</select></td>
                <td><input type="checkbox" checked={c.critico} onChange={(e) => set(i, { critico: e.target.checked })} aria-label={`Crítico ${c.id}`} /></td>
                <td><input value={c.pergunta} onChange={(e) => set(i, { pergunta: e.target.value })} aria-label={`Pergunta ${c.id}`} />
                  <div className="resp">{c.respostas_rapidas.map((r, k) => (
                    <span key={k}><input value={r} onChange={(e) => set(i, { respostas_rapidas: c.respostas_rapidas.map((y, z) => (z === k ? e.target.value : y)) })} aria-label={`Resposta ${k + 1}`} />
                      <select value={c.mapa_resposta[String(k)]} onChange={(e) => set(i, { mapa_resposta: { ...c.mapa_resposta, [String(k)]: e.target.value } })} aria-label={`Estado ${k + 1}`}>
                        {["DECLARADO", "NAO_ATENDE", "LACUNA"].map((s) => <option key={s}>{s}</option>)}</select></span>))}</div></td>
              </tr>))}</tbody>
          </table></div>
          <div className="row3">
            <div className="field"><label htmlFor="rLim">Limiar "pronta para avançar"</label><input id="rLim" type="text" inputMode="numeric" value={limiar} onChange={(e) => setLimiar(Number(e.target.value) || 75)} /></div>
            <div className="field" style={{ gridColumn: "span 2" }}><label htmlFor="rNota">O que mudou e por quê</label><input id="rNota" type="text" value={nota} onChange={(e) => setNota(e.target.value)} placeholder="Ex.: C5.1 passa a peso 3 após revisão do conjunto ouro" /></div>
          </div>
          <div className="kbact"><button className="btn" disabled={nota.trim().length < 3 || salvar.isPending} onClick={() => salvar.mutate()}>Publicar nova versão</button>
            <button className="btn ghost" onClick={() => setEditing(false)}>Cancelar</button></div>
        </>
      )}
    </section>
  );
}

export function GovernancaTab() {
  const { data: me } = useMe();
  return (
    <>
      <ConsultorCard />
      <FichasCard />
      <section className="grp"><h3>Por conversa</h3>
        <p className="hint">Liga ou desliga, em cada conversa, o Modelo de Camadas no contexto dos agentes e a participação do Consultor de IA nos grupos.</p>
        <ConversaGovernanca /></section>
      <ModeloCard />
      <EventosCard />
      {me?.is_admin && <RubricaCard />}
    </>
  );
}
