// Fluxo do sistema: desenho das peças do Papo e do worker, com o estado de cada uma lido ao vivo (atualiza a cada 15 s).
import { useQuery } from "@tanstack/react-query";

import { useState } from "react";

import { api, ok } from "../api/client";
import { Modal } from "./ui";

type Check = { ok: boolean; ms?: number; error?: string; queue?: number; worker_seen?: boolean; version?: string };
type Sys = {
  checks: Record<string, Check>;
  ai: { key_source: string; workspace: boolean; models_checked_at: string | null; models: Record<string, string> };
  hub_sources: { name: string; label: string; kind: string; enabled: boolean; status: string; last_error: string | null; file_count: number }[];
  runs_24h: Record<string, { n: number; avg_s: number | null }>;
  docs_24h: Record<string, number>;
};
type State = "ok" | "bad" | "warn" | "idle";
type Node = { id: string; x: number; y: number; w: number; h: number; title: string; sub: string; state: State };
const W = 150, H = 56;

function nodes(d: Sys | undefined): Node[] {
  const c = d?.checks ?? {};
  const st = (k: string): State => (!d ? "idle" : c[k]?.ok ? "ok" : "bad");
  const ms = (k: string) => (c[k]?.ok ? `${c[k]?.ms} ms` : c[k]?.error ? "fora do ar" : "…");
  const worker: State = !d ? "idle" : c.redis?.worker_seen ? "ok" : "bad";
  const ai: State = !d ? "idle" : d.ai.key_source === "nenhuma" ? "bad" : d.ai.models_checked_at ? "ok" : "warn";
  const runs = d?.runs_24h ?? {};
  const failed = runs.failed?.n ?? 0, done = runs.done?.n ?? 0;
  const src = (kind: string) => d?.hub_sources.filter((s) => s.kind === kind) ?? [];
  const srcState = (kind: string): State => { const l = src(kind); return !d ? "idle" : !l.length ? "idle" : l.every((s) => s.status === "ok") ? "ok" : l.some((s) => s.status === "erro") ? "bad" : "warn"; };
  const srcSub = (kind: string) => { const l = src(kind); return l.length ? `${l.reduce((a, s) => a + s.file_count, 0)} arquivos` : "não cadastrada"; };
  return [
    { id: "client", x: 16, y: 222, w: 132, h: H, title: "Navegador", sub: "PWA · celular e PC", state: "ok" },
    { id: "caddy", x: 176, y: 222, w: 132, h: H, title: "Caddy", sub: "TLS · papo.gplansis.com", state: d ? "ok" : "idle" },
    { id: "web", x: 344, y: 70, w: W, h: H, title: "Web (nginx)", sub: "app React + CSP", state: d ? "ok" : "idle" },
    { id: "api", x: 344, y: 222, w: W, h: H, title: "API (FastAPI)", sub: "regras, RLS, WebSocket", state: d ? "ok" : "idle" },
    { id: "auth", x: 344, y: 374, w: W, h: H, title: "Keycloak", sub: "login /auth (OIDC)", state: d ? "ok" : "idle" },
    { id: "postgres", x: 560, y: 46, w: W, h: H, title: "PostgreSQL", sub: ms("postgres"), state: st("postgres") },
    { id: "redis", x: 560, y: 170, w: W, h: H, title: "Redis · fila", sub: d ? `${c.redis?.queue ?? 0} na fila · ${ms("redis")}` : "…", state: st("redis") },
    { id: "storage", x: 560, y: 294, w: W, h: H, title: "Armazenamento", sub: `RustFS · ${ms("storage")}`, state: st("storage") },
    { id: "worker", x: 784, y: 166, w: 196, h: 64, title: "Worker (arq)", sub: d ? `24 h: ${done} ok · ${failed} falhas` : "…", state: worker === "ok" && failed > done ? "warn" : worker },
    { id: "ai", x: 784, y: 46, w: 196, h: H, title: "IA · Anthropic", sub: d ? (d.ai.key_source === "nenhuma" ? "sem chave" : d.ai.models_checked_at ? "chave testada" : "chave não testada") : "…", state: ai },
    { id: "hubgw", x: 784, y: 330, w: 196, h: H, title: "Gateway do hub", sub: `só leitura · ${ms("hubgw")}`, state: st("hubgw") },
    { id: "local", x: 560, y: 472, w: 136, h: H, title: "pastas :ro", sub: srcSub("local"), state: srcState("local") },
    { id: "remote", x: 712, y: 472, w: 136, h: H, title: "leitor TLS", sub: srcSub("remote"), state: srcState("remote") },
    { id: "sftp", x: 864, y: 472, w: 116, h: H, title: "Site · SFTP", sub: srcSub("sftp"), state: srcState("sftp") },
  ];
}

type Side = "r" | "l" | "t" | "b";
const EDGES: [string, string, string, "solid" | "dash", Side, Side][] = [
  ["client", "caddy", "HTTPS", "solid", "r", "l"], ["caddy", "web", "/", "solid", "r", "l"], ["caddy", "api", "/api", "solid", "r", "l"],
  ["caddy", "auth", "/auth", "solid", "r", "l"],
  ["api", "postgres", "SQL + RLS", "solid", "r", "l"], ["api", "redis", "jobs e eventos", "solid", "r", "l"], ["api", "storage", "arquivos", "solid", "r", "l"],
  ["redis", "worker", "fila", "dash", "r", "l"], ["worker", "postgres", "grava", "dash", "t", "r"], ["worker", "ai", "respostas", "solid", "t", "b"],
  ["worker", "hubgw", "ler hub", "solid", "b", "t"], ["api", "hubgw", "prévia", "dash", "b", "l"],
  ["hubgw", "local", "", "solid", "b", "t"], ["hubgw", "remote", "", "solid", "b", "t"], ["hubgw", "sftp", "", "solid", "b", "t"],
];

const LABEL: Record<State, string> = { ok: "no ar", bad: "com falha", warn: "atenção", idle: "sem dado" };

function anchor(n: Node, side: Side, shift = 0): [number, number] {
  return side === "r" ? [n.x + n.w, n.y + n.h / 2] : side === "l" ? [n.x, n.y + n.h / 2]
    : side === "t" ? [n.x + n.w / 2 + shift, n.y] : [n.x + n.w / 2 + shift, n.y + n.h];
}

function edge(a: Node, b: Node, from: Side, to: Side): { d: string; mx: number; my: number } {
  const shift = a.id === "worker" && from === "t" && b.id === "postgres" ? -60 : 0;   // tira a saída do worker do caminho da seta da IA
  const [sx, sy] = anchor(a, from, shift);
  const [ex, ey] = anchor(b, to);
  if (a.id === "api" && b.id === "hubgw") {                       // por baixo do armazenamento, sem cruzar caixa
    return { d: `M${sx},${sy} C${sx},${sy + 120} ${ex - 140},${ey} ${ex},${ey}`, mx: sx + 120, my: sy + 100 };
  }
  const horizontal = from === "r" || from === "l";
  const c1 = horizontal ? `${(sx + ex) / 2},${sy}` : `${sx},${(sy + ey) / 2}`;
  const c2 = horizontal ? `${(sx + ex) / 2},${ey}` : (to === "r" ? `${(sx + ex) / 2 + 60},${ey}` : `${ex},${(sy + ey) / 2}`);
  return { d: `M${sx},${sy} C${c1} ${c2} ${ex},${ey}`, mx: (sx + ex) / 2, my: (sy + ey) / 2 };
}

export function SystemFlowSection() {
  const { data, error, dataUpdatedAt } = useQuery({ queryKey: ["system"], queryFn: () => ok(api.GET("/api/admin/system")) as Promise<unknown>,
    refetchInterval: 15_000 });
  const d = data as Sys | undefined;
  const ns = nodes(d);
  const by = Object.fromEntries(ns.map((n) => [n.id, n]));
  const runs = d?.runs_24h ?? {};
  const [big, setBig] = useState(false);
  const svg = (
    <div className="flowsvg">
        <svg viewBox="0 0 1000 548" role="img" aria-label="Diagrama do fluxo do sistema com o estado de cada peça">
          <defs>
            <marker id="arr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
              <path d="M0,0 L10,5 L0,10 z" className="fs-arrow" /></marker>
          </defs>
          <rect x="330" y="40" width="178" height="410" rx="16" className="fs-zone" /><text x="342" y="58" className="fs-zone-t">borda (rede edge)</text>
          <rect x="546" y="18" width="178" height="352" rx="16" className="fs-zone" /><text x="558" y="36" className="fs-zone-t">dados (rede interna)</text>
          <rect x="546" y="444" width="446" height="96" rx="16" className="fs-zone hub" /><text x="558" y="462" className="fs-zone-t">Docs do hub · lidos na origem, sem cópia</text>
          {EDGES.map(([a, b, label, kind, f, t]) => {
            const e = edge(by[a]!, by[b]!, f, t);
            return (
              <g key={`${a}-${b}`}>
                <path d={e.d} className={`fs-edge ${kind}`} markerEnd="url(#arr)" />
                {label && <text x={e.mx} y={e.my - 6} className="fs-elabel" textAnchor="middle">{label}</text>}
              </g>
            );
          })}
          {ns.map((n) => (
            <g key={n.id} className={`fs-node ${n.state}`}>
              <title>{`${n.title}: ${LABEL[n.state]} · ${n.sub}`}</title>
              <rect x={n.x} y={n.y} width={n.w} height={n.h} rx="12" />
              <circle cx={n.x + 14} cy={n.y + 18} r="5" className="fs-dot" />
              <text x={n.x + 26} y={n.y + 22} className="fs-t">{n.title}</text>
              <text x={n.x + 12} y={n.y + 42} className="fs-s">{n.sub}</text>
            </g>
          ))}
        </svg>
      </div>
  );
  return (
    <section className="grp" id="fluxo-sistema"><h3>Fluxo do sistema</h3>
      <p className="hint">Como uma mensagem anda pelo Papo: o navegador fala com a API pelo Caddy; a API grava no banco e põe a resposta na fila; o worker
        pega da fila, chama a IA e, quando o agente precisa, lê os Docs do hub pelo gateway (só leitura). Estado lido agora
        {dataUpdatedAt ? ` · ${new Date(dataUpdatedAt).toLocaleTimeString("pt-BR")}` : ""}; atualiza a cada 15 s.</p>
      {error && <p className="note">{(error as Error).message}</p>}
      <div className="kbact"><button className="btn ghost sm" onClick={() => setBig(true)}>Tela cheia</button></div>
      {svg}
      {big && <Modal title="Fluxo do sistema" onClose={() => setBig(false)} wide footer={<span className="muted">Estado ao vivo · atualiza a cada 15 s</span>}>
        <div className="flow-big">{svg}</div></Modal>}
      <ul className="fs-list">
        {ns.map((n) => <li key={n.id} className={n.state}><span className="fs-pill">{n.state === "ok" ? "●" : n.state === "bad" ? "✕" : n.state === "warn" ? "!" : "○"} {LABEL[n.state]}</span><b>{n.title}</b><small>{n.sub}</small></li>)}
      </ul>
      {d && (
        <div className="tbl-wrap"><table className="tbl">
          <thead><tr><th>Últimas 24 h</th><th>Quantidade</th><th>Tempo médio</th></tr></thead>
          <tbody>
            {["done", "failed", "cancelled", "running", "queued"].filter((k) => runs[k]).map((k) => (
              <tr key={k}><td>{{ done: "Respostas concluídas", failed: "Respostas com falha", cancelled: "Interrompidas", running: "Em andamento", queued: "Na fila" }[k]}</td>
                <td>{runs[k]!.n}</td><td>{runs[k]!.avg_s != null ? `${runs[k]!.avg_s} s` : "—"}</td></tr>))}
            {Object.entries(d.docs_24h).map(([k, n]) => <tr key={`d${k}`}><td>Arquivos lidos ({{ ready: "prontos", failed: "falharam", unreadable: "ilegíveis", pending: "lendo" }[k] ?? k})</td><td>{n}</td><td>—</td></tr>)}
            <tr><td>Modelos em uso</td><td colSpan={2}>Rápido {d.ai.models.quick} · Padrão {d.ai.models.default} · Avançado {d.ai.models.complex}</td></tr>
          </tbody>
        </table></div>
      )}
    </section>
  );
}
