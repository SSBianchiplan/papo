import { useApp } from "../store";
import { Icon } from "./ui";

type Tab = "welcome" | "files" | "flow" | "settings";
const TABS: { kind: Tab; label: string; icon: () => React.JSX.Element }[] = [
  { kind: "welcome", label: "Conversas", icon: Icon.chat },
  { kind: "files", label: "Arquivos", icon: Icon.folder },
  { kind: "flow", label: "Fluxo", icon: Icon.flow },
  { kind: "settings", label: "Configuração", icon: Icon.gear },
];

/** Navegação principal: coluna à esquerda no computador, barra flutuante embaixo no celular (como o WhatsApp). */
export function Nav() {
  const { view, setView } = useApp();
  const cur: Tab = view.kind === "chat" ? "welcome" : view.kind;
  return (
    <nav className="nav" aria-label="Seções">
      {TABS.map((t) => (
        <button key={t.kind} className={cur === t.kind ? "on" : ""} aria-current={cur === t.kind ? "page" : undefined} title={t.label}
          onClick={() => setView({ kind: t.kind })}>
          <t.icon /><span>{t.label}</span>
        </button>
      ))}
    </nav>
  );
}
