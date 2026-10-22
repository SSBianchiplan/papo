// Consumo e custos de IA (todo usuário) e administração da chave, orçamento e preços (papel papo-admin).
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { api, ApiError, ok, type S } from "../api/client";
import { useApp } from "../store";

type Usage = S["Usage"];
type Price = S["PriceOut"];

const usd = (v: number) =>
  new Intl.NumberFormat("pt-BR", { style: "currency", currency: "USD", minimumFractionDigits: 2, maximumFractionDigits: v > 0 && v < 1 ? 4 : 2 }).format(v);
const tok = (n: number) => (n >= 1e6 ? `${(n / 1e6).toLocaleString("pt-BR", { maximumFractionDigits: 1 })} mi` : n >= 1e4 ? `${Math.round(n / 1e3)} mil` : n.toLocaleString("pt-BR"));
const full = (e: Error) => (e instanceof ApiError && e.hint ? `${e.message} ${e.hint}` : e.message);
const dia = (d: string) => new Date(`${d}T12:00:00`).toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit" });

/** Custo por dia: uma série, barras finas com topo arredondado, dica ao passar o dedo ou o mouse. */
function DailyBars({ days }: { days: Usage["days"] }) {
  const [hover, setHover] = useState<number | null>(null);
  const max = Math.max(...days.map((d) => d.cost_usd), 0);
  const h = hover !== null ? days[hover] : null;
  if (max === 0) return <p className="muted">Sem consumo no período.</p>;
  return (
    <figure className="bars" aria-label="Custo por dia">
      <div className="bars-tip" aria-live="polite">
        {h ? <><b>{dia(h.day)}</b> · {usd(h.cost_usd)} · {tok(h.input_tokens + h.output_tokens)} tokens</> : <span className="muted">Toque numa barra para ver o dia</span>}
      </div>
      <div className="bars-plot" onMouseLeave={() => setHover(null)}>
        <span className="bars-max">{usd(max)}</span>
        {days.map((d, i) => (
          <button key={d.day} type="button" className={`bar ${hover === i ? "on" : ""}`} aria-label={`${dia(d.day)}: ${usd(d.cost_usd)}`}
            onMouseEnter={() => setHover(i)} onFocus={() => setHover(i)} onClick={() => setHover(i)}>
            <i style={{ height: `${d.cost_usd ? Math.max(2, (d.cost_usd / max) * 100) : 0}%` }} />
          </button>
        ))}
      </div>
      <div className="bars-axis"><span>{dia(days[0]!.day)}</span><span>{dia(days[days.length - 1]!.day)}</span></div>
    </figure>
  );
}

function Meter({ value, max, alertPct, label }: { value: number; max: number; alertPct?: number; label: string }) {
  const pct = max > 0 ? Math.min(100, (value / max) * 100) : 0;
  const state = pct >= 100 ? "bad" : alertPct && pct >= alertPct ? "warn" : "ok";
  return (
    <div>
      <div className="opt"><b>{label}</b>
        <span className={`meter-label ${state}`}>{state === "bad" ? "⛔ " : state === "warn" ? "⚠️ " : ""}{Math.round(pct)}%</span></div>
      <div className={`meter ${state}`} role="meter" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(pct)} aria-label={label}><i style={{ width: `${pct}%` }} /></div>
    </div>
  );
}

function ModelTable({ rows }: { rows: Usage["by_model"] }) {
  if (!rows.length) return null;
  return (
    <table className="tbl">
      <thead><tr><th>Modelo</th><th>Entrada</th><th>Saída</th><th>Custo</th></tr></thead>
      <tbody>{rows.map((m) => <tr key={m.model}><td>{m.label}</td><td>{tok(m.input_tokens)}</td><td>{tok(m.output_tokens)}</td><td>{usd(m.cost_usd)}</td></tr>)}</tbody>
    </table>
  );
}

export function UsagePanel() {
  const { data: u } = useQuery({ queryKey: ["usage"], queryFn: () => ok(api.GET("/api/usage", { params: { query: { days: 30 } } })) });
  if (!u) return null;
  return (
    <section className="grp"><h3>Meu consumo de IA</h3>
      <div className="stats">
        <div><b>{tok(u.today_tokens)}</b><span>tokens hoje</span></div>
        <div><b>{usd(u.month_cost_usd)}</b><span>no mês</span></div>
        <div><b>{usd(u.total_cost_usd)}</b><span>30 dias</span></div>
        <div><b>{tok(u.total_tokens)}</b><span>tokens em 30 dias</span></div>
      </div>
      {u.daily_limit > 0 && <Meter value={u.today_tokens} max={u.daily_limit} alertPct={80} label={`Limite diário: ${tok(u.daily_limit)} tokens`} />}
      <DailyBars days={u.days} />
      <ModelTable rows={u.by_model} />
      <p className="hint">Estimativa pelos preços públicos da Anthropic por milhão de tokens. A fatura oficial é a do Console da Anthropic.</p>
    </section>
  );
}

function KeyCard({ st }: { st: S["AiStatus"] }) {
  const qc = useQueryClient();
  const notify = useApp((s) => s.notify);
  const [key, setKey] = useState("");
  const [ws, setWs] = useState(st.workspace_id ?? "");
  const [test, setTest] = useState<S["KeyTest"] | null>(null);
  useEffect(() => setWs(st.workspace_id ?? ""), [st.workspace_id]);
  const done = (s: S["AiStatus"]) => qc.setQueryData(["admin-ai"], s);
  const save = useMutation({
    mutationFn: () => ok(api.PUT("/api/admin/ai/key", { body: { api_key: key.trim(), workspace_id: ws.trim() || null } })),
    onSuccess: (s) => { done(s); setKey(""); setTest(null); notify("Chave salva. Clique em Testar."); },
    onError: (e: Error) => notify(full(e)),
  });
  const saveWs = useMutation({
    mutationFn: () => ok(api.PUT("/api/admin/ai", { body: { workspace_id: ws.trim() || null, monthly_budget_usd: st.monthly_budget_usd ?? null, alert_pct: st.alert_pct, daily_token_limit: st.daily_token_limit ?? null } })),
    onSuccess: (s) => { done(s); notify("Workspace salvo."); },
    onError: (e: Error) => notify(full(e)),
  });
  const remove = useMutation({
    mutationFn: () => ok(api.DELETE("/api/admin/ai/key")),
    onSuccess: (s) => { done(s); setTest(null); notify("Chave do painel removida."); },
    onError: (e: Error) => notify(full(e)),
  });
  const run = useMutation({ mutationFn: () => ok(api.POST("/api/admin/ai/test")),
    onSuccess: (t) => { setTest(t); void qc.invalidateQueries({ queryKey: ["admin-ai"] }); }, onError: (e: Error) => notify(full(e)) });
  const source = { painel: "cadastrada aqui", servidor: "do arquivo .env do servidor", nenhuma: "nenhuma" }[st.key_source];
  return (
    <section className="grp"><h3>Administração · Chave da IA</h3>
      <div className="opt"><div><b>Chave em uso</b><small>{st.key_hint ? <code>{st.key_hint}</code> : "—"} · {source}</small></div>
        <span className={`badge ${st.key_source === "nenhuma" ? "bad" : "ok"}`}>{st.key_source === "nenhuma" ? "sem chave" : "configurada"}</span></div>
      <div className="field"><label htmlFor="kKey">Nova chave da Anthropic</label>
        <input id="kKey" type="password" autoComplete="off" spellCheck={false} placeholder="sk-ant-…" value={key} onChange={(e) => setKey(e.target.value)} />
        <div className="hint">{st.secrets_ready ? "Guardada cifrada no banco; depois de salva, só o começo e o fim aparecem aqui." : "O servidor está sem SECRETS_KEY: a chave não pode ser gravada pelo painel."}</div></div>
      <div className="field"><label htmlFor="kWs">ID do workspace</label>
        <input id="kWs" type="text" spellCheck={false} placeholder="wrkspc_…" value={ws} onChange={(e) => setWs(e.target.value)} />
        <div className="hint">Obrigatório para chaves que não pertencem a um workspace só. É o ID, não o nome: começa com <code>wrkspc_</code>. No Console: Settings → Workspaces → abra o workspace.</div></div>
      <div className="kbact">
        <button className="btn" disabled={!key.trim() || !st.secrets_ready || save.isPending} onClick={() => save.mutate()}>Salvar chave</button>
        <button className="btn ghost" disabled={saveWs.isPending || ws.trim() === (st.workspace_id ?? "")} onClick={() => saveWs.mutate()}>Salvar workspace</button>
        <button className="btn ghost" disabled={st.key_source === "nenhuma" || run.isPending} onClick={() => run.mutate()}>{run.isPending ? "Testando…" : "Testar"}</button>
        {st.key_source === "painel" && <button className="btn danger" onClick={() => confirm("Remover a chave cadastrada no painel?") && remove.mutate()}>Remover</button>}
      </div>
      {test && <div className={`note ${test.ok ? "okn" : "badn"}`} role="status"><b>{test.ok ? "✓ " : "✕ "}{test.message}</b>{test.detail && <div className="muted">{test.detail}</div>}</div>}
    </section>
  );
}

function BudgetCard({ st }: { st: S["AiStatus"] }) {
  const qc = useQueryClient();
  const notify = useApp((s) => s.notify);
  const [budget, setBudget] = useState(st.monthly_budget_usd?.toString() ?? "");
  const [alert, setAlert] = useState(String(st.alert_pct));
  const [daily, setDaily] = useState(st.daily_token_limit?.toString() ?? "");
  const num = (s: string) => (s.trim() === "" ? null : Number(s.replace(",", ".")));
  const save = useMutation({
    mutationFn: () => ok(api.PUT("/api/admin/ai", { body: { workspace_id: st.workspace_id ?? null, monthly_budget_usd: num(budget), alert_pct: Number(alert) || 80, daily_token_limit: num(daily) } })),
    onSuccess: (s) => { qc.setQueryData(["admin-ai"], s); void qc.invalidateQueries({ queryKey: ["me"] }); void qc.invalidateQueries({ queryKey: ["usage"] }); notify("Limites salvos."); },
    onError: (e: Error) => notify(full(e)),
  });
  return (
    <section className="grp"><h3>Administração · Orçamento e limites</h3>
      {st.monthly_budget_usd != null
        ? <Meter value={st.month_cost_usd} max={st.monthly_budget_usd} alertPct={st.alert_pct} label={`Gasto do mês: ${usd(st.month_cost_usd)} de ${usd(st.monthly_budget_usd)}`} />
        : <p className="muted">Gasto do mês: <b>{usd(st.month_cost_usd)}</b> · sem teto definido.</p>}
      <div className="row3">
        <div className="field"><label htmlFor="bBud">Teto mensal (US$)</label><input id="bBud" type="text" inputMode="decimal" placeholder="sem teto" value={budget} onChange={(e) => setBudget(e.target.value)} />
          <div className="hint">Atingido o teto, os agentes param até o mês seguinte.</div></div>
        <div className="field"><label htmlFor="bAl">Avisar em (%)</label><input id="bAl" type="text" inputMode="numeric" value={alert} onChange={(e) => setAlert(e.target.value)} /></div>
        <div className="field"><label htmlFor="bDay">Tokens por usuário por dia</label><input id="bDay" type="text" inputMode="numeric" placeholder={`padrão: ${st.server_daily_limit.toLocaleString("pt-BR")}`} value={daily} onChange={(e) => setDaily(e.target.value)} />
          <div className="hint">0 = sem limite. Vazio = padrão do servidor.</div></div>
      </div>
      <div><button className="btn" disabled={save.isPending} onClick={() => save.mutate()}>Salvar limites</button></div>
    </section>
  );
}

function PricesCard({ prices }: { prices: Price[] }) {
  const qc = useQueryClient();
  const notify = useApp((s) => s.notify);
  const [rows, setRows] = useState<Price[]>(prices);
  useEffect(() => setRows(prices), [prices]);
  const set = (i: number, k: keyof Price, v: string) =>
    setRows((r) => r.map((p, j) => (j === i ? { ...p, [k]: k.endsWith("mtok") ? Number(v.replace(",", ".")) || 0 : v } : p)));
  const save = useMutation({
    mutationFn: () => ok(api.PUT("/api/admin/prices", { body: rows.filter((r) => r.model.trim()) })),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ["admin-ai"] }); void qc.invalidateQueries({ queryKey: ["usage"] }); void qc.invalidateQueries({ queryKey: ["admin-usage"] }); notify("Preços salvos."); },
    onError: (e: Error) => notify(full(e)),
  });
  return (
    <section className="grp"><h3>Administração · Preços por modelo</h3>
      <p className="hint">US$ por milhão de tokens. O modelo casa pelo começo do nome: <code>claude-haiku-4-5</code> vale para <code>claude-haiku-4-5-20251001</code>.</p>
      <div className="tbl-wrap"><table className="tbl edit">
        <thead><tr><th>Modelo (ID)</th><th>Nome</th><th>Entrada</th><th>Saída</th><th /></tr></thead>
        <tbody>{rows.map((p, i) => (
          <tr key={i}>
            <td><input aria-label="ID do modelo" value={p.model} onChange={(e) => set(i, "model", e.target.value)} /></td>
            <td><input aria-label="Nome" value={p.label} onChange={(e) => set(i, "label", e.target.value)} /></td>
            <td><input aria-label="Entrada" inputMode="decimal" value={p.input_usd_mtok} onChange={(e) => set(i, "input_usd_mtok", e.target.value)} /></td>
            <td><input aria-label="Saída" inputMode="decimal" value={p.output_usd_mtok} onChange={(e) => set(i, "output_usd_mtok", e.target.value)} /></td>
            <td><button className="iconbtn x" aria-label="Remover modelo" onClick={() => setRows((r) => r.filter((_, j) => j !== i))}>×</button></td>
          </tr>))}</tbody>
      </table></div>
      <div className="kbact">
        <button className="btn ghost" onClick={() => setRows((r) => [...r, { model: "", label: "", input_usd_mtok: 0, output_usd_mtok: 0 }])}>Adicionar modelo</button>
        <button className="btn" disabled={save.isPending} onClick={() => save.mutate()}>Salvar preços</button>
      </div>
    </section>
  );
}

function AllUsageCard() {
  const { data: u } = useQuery({ queryKey: ["admin-usage"], queryFn: () => ok(api.GET("/api/admin/usage", { params: { query: { days: 30 } } })) });
  if (!u) return null;
  return (
    <section className="grp"><h3>Administração · Consumo de todos (30 dias)</h3>
      <div className="stats">
        <div><b>{usd(u.month_cost_all_usd)}</b><span>no mês</span></div>
        <div><b>{usd(u.total_cost_usd)}</b><span>30 dias</span></div>
        <div><b>{tok(u.total_tokens)}</b><span>tokens</span></div>
        <div><b>{u.by_user.length}</b><span>usuários</span></div>
      </div>
      <DailyBars days={u.days} />
      <ModelTable rows={u.by_model} />
      {u.by_user.length > 0 && (
        <div className="tbl-wrap"><table className="tbl">
          <thead><tr><th>Usuário</th><th>Hoje</th><th>30 dias</th><th>Custo</th></tr></thead>
          <tbody>{u.by_user.map((x) => <tr key={x.user_id}><td title={x.email ?? ""}>{x.name}</td><td>{tok(x.today_tokens)}</td><td>{tok(x.input_tokens + x.output_tokens)}</td><td>{usd(x.cost_usd)}</td></tr>)}</tbody>
        </table></div>
      )}
    </section>
  );
}

const TIER_LABEL: Record<string, string> = { quick: "Rápido", default: "Padrão", complex: "Avançado", router: "Roteador dos grupos" };
const TIER_HINT: Record<string, string> = {
  quick: "Respostas quase na hora. Bom para perguntas simples.",
  default: "O nível que vem marcado para todos.",
  complex: "Análises difíceis. Mais caro.",
  router: "Escolhe quem responde num grupo. Basta um modelo barato.",
};

function ModelsCard({ st }: { st: S["AiStatus"] }) {
  const qc = useQueryClient();
  const notify = useApp((s) => s.notify);
  const [pick, setPick] = useState<Record<string, string>>({});
  useEffect(() => setPick(Object.fromEntries(Object.entries(st.models_panel).map(([k, v]) => [k, v ?? ""]))), [st.models_panel]);
  const changed = ["quick", "default", "complex", "router"].some((t) => (pick[t] ?? "") !== ((st.models_panel as Record<string, string | null>)[t] ?? ""));
  const save = useMutation({
    mutationFn: () => ok(api.PUT("/api/admin/models", { body: Object.fromEntries(Object.entries(pick).map(([k, v]) => [k, v || null])) })),
    onSuccess: (s) => { qc.setQueryData(["admin-ai"], s); void qc.invalidateQueries({ queryKey: ["me"] }); notify("Modelos salvos. Valem na próxima mensagem."); },
    onError: (e: Error) => notify(full(e)),
  });
  // exato primeiro; senão o prefixo mais longo (claude-sonnet-5-5 não pode cair em claude-sonnet-5)
  const label = (id: string) => (st.catalog.find((m) => m.model === id)
    ?? st.catalog.filter((m) => id.startsWith(`${m.model}-`)).sort((a, b) => b.model.length - a.model.length)[0])?.label ?? id;
  return (
    <section className="grp"><h3>Administração · Modelos</h3>
      <p className="hint">Escolha o modelo de cada nível. Os usuários escolhem o nível em Configuração → Agentes; trocar aqui vale na próxima mensagem, sem reiniciar.</p>
      <div className="tier-grid">
        {["quick", "default", "complex", "router"].map((t) => (
          <div className="field" key={t}>
            <label htmlFor={`tier-${t}`}>{TIER_LABEL[t]}</label>
            <select id={`tier-${t}`} value={pick[t] ?? ""} onChange={(e) => setPick((p) => ({ ...p, [t]: e.target.value }))}>
              <option value="">Padrão do servidor · {label(st.models_env[t] ?? "")}</option>
              {st.catalog.map((m) => (
                <option key={m.model} value={m.model} disabled={m.available === false}>
                  {m.label} · {usd(m.input_usd_mtok)} / {usd(m.output_usd_mtok)}{m.available === false ? " · indisponível na conta" : ""}
                </option>
              ))}
            </select>
            <div className="hint">{TIER_HINT[t]} Em uso: <b>{label(st.models[t] ?? "")}</b></div>
          </div>
        ))}
      </div>
      <div><button className="btn" disabled={!changed || save.isPending} onClick={() => save.mutate()}>Salvar modelos</button></div>
      <div className="tbl-wrap"><table className="tbl">
        <thead><tr><th>Modelo</th><th>Entrada</th><th>Saída</th><th>Na conta</th><th>Em uso</th></tr></thead>
        <tbody>{st.catalog.map((m) => (
          <tr key={m.model}>
            <td><b>{m.label}</b><br /><code>{m.model}</code></td>
            <td>{usd(m.input_usd_mtok)}</td><td>{usd(m.output_usd_mtok)}</td>
            <td>{m.available == null ? <span className="av-no" title="Rode Testar na chave para consultar">—</span> : m.available ? <span className="av-ok">✓ sim</span> : <span className="av-no">✕ não</span>}</td>
            <td>{m.used_by.map((t) => <span key={t} className="tag">{TIER_LABEL[t]}</span>)}</td>
          </tr>))}</tbody>
      </table></div>
      <p className="hint">Preço em US$ por milhão de tokens (entrada / saída). A coluna "Na conta" é preenchida pelo botão Testar da chave
        {st.models_checked_at ? `; última consulta em ${new Date(st.models_checked_at).toLocaleString("pt-BR")}` : ""}.</p>
    </section>
  );
}

export function AdminPanel() {
  const { data: st, error } = useQuery({ queryKey: ["admin-ai"], queryFn: () => ok(api.GET("/api/admin/ai")) });
  if (error) return <section className="grp"><h3>Administração</h3><p className="muted">{error.message}</p></section>;
  if (!st) return null;
  return (
    <>
      <KeyCard st={st} />
      <ModelsCard st={st} />
      <BudgetCard st={st} key={`${st.monthly_budget_usd}-${st.alert_pct}-${st.daily_token_limit}`} />
      <PricesCard prices={st.prices} />
      <AllUsageCard />
    </>
  );
}
