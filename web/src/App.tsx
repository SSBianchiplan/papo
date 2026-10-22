import { useEffect } from "react";

import { Chat } from "./components/Chat";
import { AgentDialog, GroupDialog } from "./components/Dialogs";
import { Files } from "./components/Files";
import { Flow } from "./components/Flow";
import { Nav } from "./components/Nav";
import { Settings } from "./components/Settings";
import { Sidebar } from "./components/Sidebar";
import { useMe } from "./queries";
import { useApp } from "./store";

function Welcome() {
  const setDialog = useApp((s) => s.setDialog);
  return (
    <div className="welcome"><div className="card">
      <h2>Converse com seus agentes</h2>
      <p>Mande um PDF, Word ou planilha na conversa, ou deixe arquivos na base de cada agente. Eles leem, calculam e respondem citando a página.</p>
      <div className="row-gap center"><button className="btn" onClick={() => setDialog({ kind: "agent" })}>Criar agente</button>
        <button className="btn ghost" onClick={() => setDialog({ kind: "group" })}>Criar grupo</button></div>
    </div></div>
  );
}

export function App() {
  const { view, dialog, toast } = useApp();
  const { data: me, error } = useMe();

  // Botão voltar do Android/PWA: abrir conversa, configuração ou fluxo empilha uma entrada no histórico;
  // voltar fecha o diálogo aberto ou retorna à lista, em vez de sair do app.
  useEffect(() => {
    const inner = view.kind !== "welcome";
    const pushed = (history.state as { papo?: boolean } | null)?.papo === true;
    if (inner && !pushed) history.pushState({ papo: true }, "");
    if (!inner && pushed) history.back();
  }, [view.kind]);
  useEffect(() => {
    const onPop = () => {
      const s = useApp.getState();
      if (s.dialog) {
        s.setDialog(null);
        if (s.view.kind !== "welcome") history.pushState({ papo: true }, "");
      } else if (s.view.kind !== "welcome") s.setView({ kind: "welcome" });
    };
    addEventListener("popstate", onPop);
    return () => removeEventListener("popstate", onPop);
  }, []);

  useEffect(() => {
    if (!me) return;
    const r = document.documentElement;
    if (me.settings.theme === "system") r.removeAttribute("data-theme");
    else r.setAttribute("data-theme", me.settings.theme);
    document.body.style.fontSize = `${me.settings.fontSize}px`;
  }, [me]);

  if (error) return <div className="welcome"><div className="card"><h2>Não foi possível conectar</h2><p>{error.message}</p><button className="btn" onClick={() => location.reload()}>Tentar de novo</button></div></div>;
  if (!me) return <div className="welcome"><div className="card"><p>Carregando…</p></div></div>;

  return (
    <div className={`app ${view.kind !== "welcome" ? "chatting" : ""} ${view.kind === "chat" ? "in-chat" : "tabbed"}`}>
      <Nav />
      <Sidebar />
      <main className="main">
        {view.kind === "chat" ? <Chat id={view.id} key={view.id} /> : view.kind === "settings" ? <Settings /> : view.kind === "flow" ? <Flow /> : view.kind === "files" ? <Files /> : <Welcome />}
      </main>
      {dialog?.kind === "agent" && <AgentDialog id={dialog.id} key={dialog.id ?? "new"} />}
      {dialog?.kind === "group" && <GroupDialog id={dialog.id} key={dialog.id ?? "new"} />}
      {toast && <div className="toast" role="status">{toast}</div>}
    </div>
  );
}
