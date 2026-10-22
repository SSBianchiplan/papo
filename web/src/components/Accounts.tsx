// Gestão de contas (multiusuário): administradores criam, ativam/desativam, trocam senha e excluem contas;
// só o master promove ou rebaixa administradores. Cada conta continua vendo só os próprios dados.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api, ApiError, ok, type S } from "../api/client";
import { useMe } from "../queries";
import { useApp } from "../store";
import { ContextMenu, Modal, type MenuItem, type MenuState } from "./ui";

type Account = S["AccountOut"];
type Secret = S["AccountSecret"];

const full = (e: Error) => (e instanceof ApiError && e.hint ? `${e.message} ${e.hint}` : e.message);
const usd = (v: number) => new Intl.NumberFormat("pt-BR", { style: "currency", currency: "USD", maximumFractionDigits: v > 0 && v < 1 ? 4 : 2 }).format(v);
const mb = (b: number) => (b >= 1e9 ? `${(b / 1e9).toFixed(1)} GB` : b >= 1e6 ? `${(b / 1e6).toFixed(1)} MB` : b >= 1e3 ? `${Math.round(b / 1e3)} KB` : `${b} B`);
const when = (d: string | null | undefined) => (d ? new Date(d).toLocaleDateString("pt-BR", { day: "2-digit", month: "short", year: "numeric" }) : "nunca");
const initials = (n: string) => n.split(/\s+/).filter(Boolean).slice(0, 2).map((p) => p[0]!.toUpperCase()).join("") || "?";
const HUES = ["#1DAA61", "#2D6CDF", "#8E44AD", "#D35400", "#C0392B", "#16A085", "#B7950B", "#5D6D7E"];
const hue = (s: string) => HUES[[...s].reduce((a, c) => a + c.charCodeAt(0), 0) % HUES.length];

function SecretBox({ s, onClose, title }: { s: Secret; onClose: () => void; title: string }) {
  const notify = useApp((x) => x.notify);
  const copy = () => void navigator.clipboard?.writeText(`Papo: https://papo.gplansis.com\nUsuário: ${s.account.username}\nSenha temporária: ${s.temp_password}`)
    .then(() => notify("Acesso copiado."));
  return (
    <Modal title={title} onClose={onClose} footer={<><span className="muted">A senha aparece só agora.</span><button className="btn" onClick={copy}>Copiar acesso</button></>}>
      <p className="muted">Envie para <b>{s.account.name}</b>. No primeiro acesso o Papo pede para trocar a senha.</p>
      <dl className="secret">
        <dt>Endereço</dt><dd>papo.gplansis.com</dd>
        <dt>Usuário</dt><dd>{s.account.username}</dd>
        <dt>Senha temporária</dt><dd><code>{s.temp_password}</code></dd>
      </dl>
    </Modal>
  );
}

function NewAccount({ master, onClose, onDone }: { master: boolean; onClose: () => void; onDone: (s: Secret) => void }) {
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [admin, setAdmin] = useState(false);
  const [err, setErr] = useState("");
  const qc = useQueryClient();
  const m = useMutation({
    mutationFn: () => ok(api.POST("/api/admin/accounts", { body: { name: name.trim(), email: email.trim(), is_admin: admin } })),
    onSuccess: (s) => { void qc.invalidateQueries({ queryKey: ["accounts"] }); onDone(s); },
    onError: (e: Error) => setErr(full(e)),
  });
  const valid = name.trim() && /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email.trim());
  return (
    <Modal title="Nova conta" onClose={onClose} footer={<><button className="btn ghost" onClick={onClose}>Cancelar</button>
      <button className="btn" disabled={!valid || m.isPending} onClick={() => m.mutate()}>{m.isPending ? "Criando…" : "Criar conta"}</button></>}>
      <div className="field"><label htmlFor="acc-n">Nome</label><input id="acc-n" type="text" value={name} maxLength={120} onChange={(e) => setName(e.target.value)} /></div>
      <div className="field"><label htmlFor="acc-e">E-mail (é o usuário de acesso)</label>
        <input id="acc-e" type="text" inputMode="email" autoCapitalize="none" value={email} onChange={(e) => setEmail(e.target.value)} /></div>
      <label className="sw"><div><b>Administrador</b><small>{master ? "Gerencia contas, chave da IA, custos e o sistema." : "Só o master cria administradores."}</small></div>
        <input type="checkbox" checked={admin} disabled={!master} onChange={(e) => setAdmin(e.target.checked)} /><i /></label>
      {err && <p className="note">{err}</p>}
    </Modal>
  );
}

export function AccountsPanel() {
  const { data: me } = useMe();
  const qc = useQueryClient();
  const notify = useApp((s) => s.notify);
  const { data: list = [], error, isLoading } = useQuery({ queryKey: ["accounts"], queryFn: () => ok(api.GET("/api/admin/accounts")) });
  const [q, setQ] = useState("");
  const [creating, setCreating] = useState(false);
  const [secret, setSecret] = useState<{ s: Secret; title: string } | null>(null);
  const [menu, setMenu] = useState<MenuState>(null);
  if (!me) return null;
  const master = me.is_master;
  const refresh = () => void qc.invalidateQueries({ queryKey: ["accounts"] });
  const run = async (p: Promise<unknown>, msg: string) => { try { await p; refresh(); notify(msg); } catch (e) { notify(full(e as Error)); } };
  const patch = (a: Account, body: S["AccountPatch"], msg: string) =>
    run(ok(api.PATCH("/api/admin/accounts/{kid}", { params: { path: { kid: a.id } }, body })), msg);

  const isSelf = (a: Account) => a.papo_id === me.id;
  const openMenu = (a: Account, x: number, y: number) => {
    const items: MenuItem[] = [];
    const lockedAdmin = a.is_admin && !master;
    if (!a.is_master && !isSelf(a) && !lockedAdmin)
      items.push({ icon: a.enabled ? "⏸️" : "▶️", label: a.enabled ? "Desativar acesso" : "Reativar acesso",
        onSelect: () => void patch(a, { enabled: !a.enabled }, a.enabled ? "Acesso desativado e sessões encerradas." : "Acesso reativado.") });
    if (master && !a.is_master)
      items.push({ icon: a.is_admin ? "⬇️" : "⭐", label: a.is_admin ? "Remover administrador" : "Tornar administrador",
        onSelect: () => void patch(a, { is_admin: !a.is_admin }, a.is_admin ? "Agora é usuário comum." : "Agora é administrador.") });
    if ((!a.is_admin || master || isSelf(a)) && (!a.is_master || isSelf(a)))
      items.push({ icon: "🔑", label: "Gerar senha temporária", onSelect: async () => {
        try { setSecret({ s: await ok(api.POST("/api/admin/accounts/{kid}/password", { params: { path: { kid: a.id } } })), title: "Nova senha temporária" }); refresh(); }
        catch (e) { notify(full(e as Error)); } } });
    if (a.email) items.push({ icon: "📋", label: "Copiar e-mail", onSelect: () => void navigator.clipboard?.writeText(a.email ?? "").then(() => notify("E-mail copiado.")) });
    if (!a.is_master && !isSelf(a) && !lockedAdmin) items.push("sep", { icon: "🗑️", label: "Excluir conta e dados", danger: true, onSelect: () => {
      if (!confirm(`Excluir a conta de ${a.name}? Apaga o acesso e todos os agentes, conversas e arquivos dela. Não há como desfazer.`)) return;
      void run(ok(api.DELETE("/api/admin/accounts/{kid}", { params: { path: { kid: a.id } } })), "Conta excluída.");
    } });
    if (items.length) setMenu({ x, y, items });
  };

  const shown = list.filter((a) => !q || `${a.name} ${a.email ?? ""} ${a.username}`.toLowerCase().includes(q.toLowerCase()));
  const active = list.filter((a) => a.enabled).length;
  const admins = list.filter((a) => a.is_admin).length;
  return (
    <>
      <section className="grp">
        <div className="acc-head">
          <div><h3>Contas</h3><p className="muted">Cada pessoa tem os próprios agentes, conversas e arquivos. Ninguém vê o conteúdo de outra conta, nem os administradores.</p></div>
          <button className="btn" onClick={() => setCreating(true)}>Nova conta</button>
        </div>
        <div className="stats">
          <div><b>{list.length}</b><span>contas</span></div>
          <div><b>{active}</b><span>ativas</span></div>
          <div><b>{admins}</b><span>administradores</span></div>
          <div><b>{usd(list.reduce((s, a) => s + a.month_cost_usd, 0))}</b><span>IA no mês</span></div>
        </div>
        <label className="search"><input type="search" placeholder="Buscar por nome ou e-mail" aria-label="Buscar conta" value={q} onChange={(e) => setQ(e.target.value)} /></label>
        {error && <p className="note">{full(error)}</p>}
        {isLoading && <p className="muted">Carregando…</p>}
        <ul className="accs">
          {shown.map((a) => (
            <li key={a.id} className={a.enabled ? "" : "off"}>
              <div className="av acc-av" style={{ background: hue(a.username) }} aria-hidden>{initials(a.name)}</div>
              <div className="acc-meta">
                <div className="acc-n"><b>{a.name}</b>
                  {a.is_master ? <span className="tag master">Master</span> : a.is_admin ? <span className="tag adm">Admin</span> : null}
                  {isSelf(a) && <span className="tag">você</span>}
                  {!a.enabled && <span className="tag bad">desativada</span>}
                  {a.must_change_password && a.enabled && <span className="tag warn">aguardando 1º acesso</span>}
                </div>
                <small>{a.email ?? a.username}</small>
                <small className="acc-st">{a.papo_id ? `${a.conversations} conversas · ${a.agents} agentes · ${a.documents} arquivos (${mb(a.bytes)}) · ${usd(a.month_cost_usd)} no mês · último uso ${when(a.last_activity)}`
                  : "ainda não entrou no Papo"}</small>
              </div>
              <button className="iconbtn" aria-label={`Opções de ${a.name}`} onClick={(e) => { const r = e.currentTarget.getBoundingClientRect(); openMenu(a, r.right, r.bottom + 4); }}>⋯</button>
            </li>
          ))}
        </ul>
        <p className="hint">{master ? "Você é o master: só você promove ou rebaixa administradores. Ninguém desativa ou exclui a conta master."
          : "Administradores gerenciam contas comuns. Promover, rebaixar ou excluir administradores é só do master."}</p>
      </section>
      <ContextMenu menu={menu} onClose={() => setMenu(null)} />
      {creating && <NewAccount master={master} onClose={() => setCreating(false)} onDone={(s) => { setCreating(false); setSecret({ s, title: "Conta criada" }); }} />}
      {secret && <SecretBox s={secret.s} title={secret.title} onClose={() => setSecret(null)} />}
    </>
  );
}
