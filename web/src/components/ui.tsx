import { useEffect, useLayoutEffect, useRef, useState, type MouseEvent as RMouseEvent, type ReactNode, type TouchEvent as RTouchEvent } from "react";

import { imageUrl } from "../api/client";

export const COLORS = ["#1F8A70", "#2D6CDF", "#8E44AD", "#D35400", "#C0392B", "#16A085", "#7F8C3A", "#B03A74"];
export const EMOJIS = ["🤖", "🧠", "📊", "🛠️", "📚", "💼", "⚙️", "🧪", "🗂️", "🏭", "📈", "🧾", "🎯", "💬", "🦉", "🚀"];

const P = { fill: "none", stroke: "currentColor", strokeWidth: 2, strokeLinecap: "round" as const, strokeLinejoin: "round" as const };
export const Icon = {
  menu: () => <svg viewBox="0 0 24 24" {...P}><path d="M4 7h16M4 12h16M4 17h16" /></svg>,
  chat: () => <svg viewBox="0 0 24 24" {...P}><path d="M4 18.5l1.3-3.6A7.8 7.8 0 1112 20a8 8 0 01-3.7-.9L4 18.5z" /></svg>,
  search: () => <svg viewBox="0 0 24 24" {...P}><circle cx="11" cy="11" r="6.5" /><path d="M20 20l-4.2-4.2" /></svg>,
  dots: () => <svg viewBox="0 0 24 24" fill="currentColor"><circle cx="5.5" cy="12" r="1.9" /><circle cx="12" cy="12" r="1.9" /><circle cx="18.5" cy="12" r="1.9" /></svg>,
  pin: () => <svg viewBox="0 0 24 24" fill="currentColor"><path d="M15.6 3.3l5.1 5.1-2 .6-3.4 3.4.4 4.5-1.7 1.7-3.6-3.6-4.9 4.9-1.1-1.1 4.9-4.9-3.6-3.6 1.7-1.7 4.5.4 3.4-3.4z" /></svg>,
  back: () => <svg viewBox="0 0 24 24" {...P}><path d="M15 5l-7 7 7 7" /></svg>,
  plus: () => <svg viewBox="0 0 24 24" {...P}><path d="M12 5v14M5 12h14" /></svg>,
  group: () => <svg viewBox="0 0 24 24" {...P}><circle cx="9" cy="8" r="3.5" /><path d="M2.5 20c.6-3.6 3.2-5.5 6.5-5.5s5.9 1.9 6.5 5.5M19 8v6M16 11h6" /></svg>,
  flow: () => <svg viewBox="0 0 24 24" {...P}><circle cx="6" cy="5" r="2.5" /><circle cx="18" cy="12" r="2.5" /><circle cx="6" cy="19" r="2.5" /><path d="M8.5 5H12a3 3 0 013 3v1.5M15 14.5V16a3 3 0 01-3 3H8.5" /></svg>,
  gear: () => <svg viewBox="0 0 24 24" {...P}><circle cx="12" cy="12" r="3" /><path d="M12 2v3M12 19v3M4.2 4.2l2.1 2.1M17.7 17.7l2.1 2.1M2 12h3M19 12h3M4.2 19.8l2.1-2.1M17.7 6.3l2.1-2.1" /></svg>,
  clip: () => <svg viewBox="0 0 24 24" {...P}><path d="M20 11.5l-8.2 8.2a5 5 0 01-7.1-7.1l8.5-8.5a3.3 3.3 0 014.7 4.7l-8.5 8.5a1.7 1.7 0 01-2.4-2.4l7.8-7.8" /></svg>,
  send: () => <svg viewBox="0 0 24 24" fill="currentColor"><path d="M3.4 20.4l17.4-7.5c.8-.4.8-1.5 0-1.8L3.4 3.6c-.7-.3-1.4.3-1.3 1l.9 5.8c.1.5.5.9 1 .9L13 12l-9 .7c-.5 0-.9.4-1 .9l-.9 5.8c-.1.7.6 1.3 1.3 1z" /></svg>,
  stop: () => <svg viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="6" width="12" height="12" rx="2" /></svg>,
  close: () => <svg viewBox="0 0 24 24" {...P}><path d="M6 6l12 12M18 6L6 18" /></svg>,
  folder: () => <svg viewBox="0 0 24 24" {...P}><path d="M3 7a2 2 0 012-2h4l2 2h8a2 2 0 012 2v8a2 2 0 01-2 2H5a2 2 0 01-2-2z" /></svg>,
  more: () => <svg viewBox="0 0 24 24" fill="currentColor"><circle cx="12" cy="5" r="2" /><circle cx="12" cy="12" r="2" /><circle cx="12" cy="19" r="2" /></svg>,
};

export function Ticks({ status }: { status: string | null | undefined }) {
  if (!status) return null;
  if (status === "sent")
    return <svg className="ticks" viewBox="0 0 17 11" {...P} strokeWidth={1.6} aria-label="enviada"><path d="M1.5 6l3.2 3.2L11 2.5" /></svg>;
  return (
    <svg className={`ticks ${status === "read" ? "read" : ""}`} viewBox="0 0 17 11" {...P} strokeWidth={1.6} aria-label={status === "read" ? "lida" : "entregue"}>
      <path d="M1 6l3.2 3.2L10.5 2.5" /><path d="M6.5 8.6l.6.6L15.5 2.5" />
    </svg>
  );
}

export function Avatar({ emoji, color, small }: { emoji: string; color: string; small?: boolean }) {
  return <div className={`av ${small ? "sm" : ""}`} style={{ background: color }} aria-hidden>{emoji}</div>;
}

export function Modal({ title, onClose, children, footer, wide }: { title: string; onClose: () => void; children: ReactNode; footer: ReactNode; wide?: boolean }) {
  const ref = useRef<HTMLDivElement>(null);
  const closeRef = useRef(onClose);
  closeRef.current = onClose;
  // Só na abertura: onClose muda a cada render, e refocar o primeiro campo a cada tecla jogava o texto para o campo errado.
  useEffect(() => {
    const k = (e: KeyboardEvent) => e.key === "Escape" && closeRef.current();
    document.addEventListener("keydown", k);
    ref.current?.querySelector<HTMLElement>("input,textarea")?.focus();
    return () => document.removeEventListener("keydown", k);
  }, []);
  return (
    <div className="scrim on" onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div className={`modal ${wide ? "wide" : ""}`} role="dialog" aria-modal="true" aria-label={title} ref={ref}>
        <header><h3>{title}</h3><button className="iconbtn" onClick={onClose} aria-label="Fechar"><Icon.close /></button></header>
        <div className="body">{children}</div>
        <footer>{footer}</footer>
      </div>
    </div>
  );
}

export function AuthImage({ k, onOpen }: { k: string; onOpen: (src: string) => void }) {
  const [src, setSrc] = useState<string | null>(null);
  useEffect(() => {
    let alive = true;
    imageUrl(k).then((u) => alive && setSrc(u)).catch(() => alive && setSrc(""));
    return () => { alive = false; };
  }, [k]);
  if (src === "") return <div className="file"><div className="ic">IMG</div><div className="fs">imagem indisponível</div></div>;
  return src ? <img className="pic" src={src} alt="Imagem enviada" onClick={() => onOpen(src)} /> : <div className="pic ph" />;
}

export const hhmm = (t: string) => new Date(t).toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
export const listTime = (t: string) => {
  const d = new Date(t);
  return d.toDateString() === new Date().toDateString() ? hhmm(t) : d.toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit" });
};
export const dayLabel = (t: string) => {
  const d = new Date(t), n = new Date(), y = new Date(n);
  y.setDate(n.getDate() - 1);
  if (d.toDateString() === n.toDateString()) return "Hoje";
  if (d.toDateString() === y.toDateString()) return "Ontem";
  return d.toLocaleDateString("pt-BR", { day: "2-digit", month: "long", year: d.getFullYear() === n.getFullYear() ? undefined : "numeric" });
};
export const kb = (n: number) => (n < 1024 ? `${n} B` : n < 1048576 ? `${(n / 1024).toFixed(0)} KB` : `${(n / 1048576).toFixed(1)} MB`);
export const isMobile = () => matchMedia("(max-width:760px)").matches;

export type MenuItem = { label: string; icon?: string; danger?: boolean; onSelect: () => void } | "sep";
export type MenuState = { x: number; y: number; items: MenuItem[] } | null;

/** Menu de contexto: clique direito no computador, toque longo no celular. Fecha com Esc, clique fora ou rolagem. */
export function ContextMenu({ menu, onClose }: { menu: MenuState; onClose: () => void }) {
  const ref = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState<{ x: number; y: number } | null>(null);
  useEffect(() => {
    if (!menu) return;
    const close = () => onClose();
    const key = (e: KeyboardEvent) => {
      if (e.key === "Escape") return onClose();
      if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
      e.preventDefault();
      const btns = [...(ref.current?.querySelectorAll<HTMLButtonElement>("button") ?? [])];
      const i = btns.indexOf(document.activeElement as HTMLButtonElement);
      btns[(i + (e.key === "ArrowDown" ? 1 : -1) + btns.length) % btns.length]?.focus();
    };
    addEventListener("keydown", key);
    addEventListener("resize", close);
    addEventListener("scroll", close, true);
    return () => { removeEventListener("keydown", key); removeEventListener("resize", close); removeEventListener("scroll", close, true); };
  }, [menu, onClose]);
  useLayoutEffect(() => {
    if (!menu || !ref.current) return setPos(null);
    const r = ref.current.getBoundingClientRect();
    setPos({ x: Math.max(8, Math.min(menu.x, innerWidth - r.width - 8)), y: Math.max(8, Math.min(menu.y, innerHeight - r.height - 8)) });
    ref.current.querySelector<HTMLButtonElement>("button")?.focus();
  }, [menu]);
  if (!menu) return null;
  return (
    <div className="ctx-scrim" onMouseDown={onClose} onContextMenu={(e) => { e.preventDefault(); onClose(); }}>
      <div ref={ref} className="ctx" role="menu" style={{ left: pos?.x ?? menu.x, top: pos?.y ?? menu.y, visibility: pos ? "visible" : "hidden" }}
        onMouseDown={(e) => e.stopPropagation()}>
        {menu.items.map((it, i) => it === "sep" ? <hr key={i} /> : (
          <button key={i} role="menuitem" className={it.danger ? "danger" : ""} onClick={() => { onClose(); it.onSelect(); }}>
            <span aria-hidden>{it.icon ?? ""}</span>{it.label}
          </button>
        ))}
      </div>
    </div>
  );
}

/** Liga clique direito e toque longo (500 ms) a um elemento. */
export function useContextTrigger(open: (x: number, y: number) => void) {
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const fired = useRef(false);
  const start = useRef<{ x: number; y: number } | null>(null);
  const cancel = () => { clearTimeout(timer.current); start.current = null; };
  return {
    onContextMenu: (e: RMouseEvent) => { e.preventDefault(); cancel(); open(e.clientX, e.clientY); },
    onTouchStart: (e: RTouchEvent) => {
      const t = e.touches[0]; if (!t) return;
      fired.current = false; start.current = { x: t.clientX, y: t.clientY };
      timer.current = setTimeout(() => { fired.current = true; navigator.vibrate?.(15); open(t.clientX, t.clientY); }, 500);
    },
    onTouchMove: (e: RTouchEvent) => {
      const t = e.touches[0];
      if (t && start.current && Math.hypot(t.clientX - start.current.x, t.clientY - start.current.y) > 10) cancel();
    },
    onTouchEnd: (e: RTouchEvent) => { cancel(); if (fired.current) e.preventDefault(); },   // não abre a conversa depois do toque longo
  };
}

/** Tema efetivo (preferência do usuário ou do sistema), para as pré-visualizações seguirem o app. */
export const currentTheme = (): "light" | "dark" => {
  const t = document.documentElement.getAttribute("data-theme");
  return t === "dark" || t === "light" ? t : matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
};
