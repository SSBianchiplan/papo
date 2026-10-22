// WebSocket de eventos com reconexão. Token vai na primeira mensagem, nunca na URL.
import type { QueryClient } from "@tanstack/react-query";

import type { Message } from "./api/client";
import { token } from "./auth";
import { useApp } from "./store";

type Ev = { type: string; data: Record<string, string> };

export function connectRealtime(qc: QueryClient): () => void {
  let ws: WebSocket | null = null;
  let stop = false;
  let backoff = 1000;
  const st = useApp.getState;

  const handle = (ev: Ev) => {
    const d = ev.data ?? {};
    switch (ev.type) {
      case "ready":
        st().setOnline(true);
        backoff = 1000;
        void qc.invalidateQueries();              // reconectou: sincroniza o que pode ter passado
        break;
      case "message.created":
        void qc.invalidateQueries({ queryKey: ["messages", d.conversation_id] });
        void qc.invalidateQueries({ queryKey: ["conversations"] });
        break;
      case "receipt":
        qc.setQueryData<Message[]>(["messages", d.conversation_id], (old) =>
          old?.map((m) => (m.id === d.message_id ? { ...m, status: d.state as Message["status"] } : m)),
        );
        break;
      case "run.started":
        st().runStarted({ runId: d.run_id!, conversationId: d.conversation_id!, agentName: d.agent_name! });
        void qc.invalidateQueries({ queryKey: ["conversations"] });
        break;
      case "run.delta":
        st().runDelta(d.run_id!, d.text ?? "");
        break;
      case "run.step":
        st().runStep(d.run_id!, { icon: d.icon ?? "•", text: d.text ?? "" });
        break;
      case "run.finished":
        void qc.invalidateQueries({ queryKey: ["messages", d.conversation_id] }).then(() => st().runFinished(d.run_id!));
        void qc.invalidateQueries({ queryKey: ["conversations"] });
        void qc.invalidateQueries({ queryKey: ["runs"] });
        void qc.invalidateQueries({ queryKey: ["me"] });
        break;
      case "document.updated":
        st().setDoc(d.document_id!, d.status!);
        if (d.agent_id) void qc.invalidateQueries({ queryKey: ["agentDocs", d.agent_id] });
        if (d.agent_id) void qc.invalidateQueries({ queryKey: ["agents"] });
        if (d.conversation_id) void qc.invalidateQueries({ queryKey: ["messages", d.conversation_id] });
        void qc.invalidateQueries({ queryKey: ["documents"] });     // tela Arquivos: status lendo → pronto
        void qc.invalidateQueries({ queryKey: ["storage"] });
        break;
    }
  };

  const open = async () => {
    if (stop) return;
    const proto = location.protocol === "https:" ? "wss" : "ws";
    ws = new WebSocket(`${proto}://${location.host}/api/ws`);
    ws.onopen = async () => ws?.send(JSON.stringify({ token: await token() }));
    ws.onmessage = (m) => {
      try {
        handle(JSON.parse(String(m.data)) as Ev);
      } catch {
        /* evento malformado: ignora */
      }
    };
    ws.onclose = () => {
      st().setOnline(false);
      if (stop) return;
      setTimeout(() => void open(), backoff);
      backoff = Math.min(backoff * 2, 30000);
    };
  };
  void open();
  return () => {
    stop = true;
    ws?.close();
  };
}
