// Estado de cliente (Zustand). Estado de servidor fica no TanStack Query.
import { create } from "zustand";

export type LiveRun = { runId: string; conversationId: string; agentName: string; text: string; steps: { icon: string; text: string }[] };
export type View = { kind: "welcome" } | { kind: "chat"; id: string } | { kind: "settings"; tab?: string } | { kind: "flow" } | { kind: "files" };

type State = {
  view: View;
  runs: Record<string, LiveRun>;
  docStatus: Record<string, string>;
  online: boolean;
  toast: string | null;
  dialog: null | { kind: "agent"; id?: string } | { kind: "group"; id?: string };
  setView: (v: View) => void;
  setDialog: (d: State["dialog"]) => void;
  /** pedido de menu da conversa vindo do cabeçalho do chat (no celular a lista fica escondida) */
  convMenu: null | { id: string; x: number; y: number };
  openConvMenu: (m: State["convMenu"]) => void;
  runStarted: (r: Omit<LiveRun, "text" | "steps">) => void;
  runDelta: (runId: string, text: string) => void;
  runStep: (runId: string, step: { icon: string; text: string }) => void;
  runFinished: (runId: string) => void;
  setDoc: (id: string, status: string) => void;
  setOnline: (v: boolean) => void;
  notify: (msg: string) => void;
};

let toastTimer: ReturnType<typeof setTimeout> | undefined;

export const useApp = create<State>((set) => ({
  view: { kind: "welcome" },
  runs: {},
  docStatus: {},
  online: false,
  toast: null,
  dialog: null,
  setView: (view) => set({ view }),
  setDialog: (dialog) => set({ dialog }),
  convMenu: null,
  openConvMenu: (convMenu) => set({ convMenu }),
  runStarted: (r) => set((s) => ({ runs: { ...s.runs, [r.runId]: { ...r, text: "", steps: [] } } })),
  runDelta: (id, text) => set((s) => (s.runs[id] ? { runs: { ...s.runs, [id]: { ...s.runs[id], text } } } : s)),
  runStep: (id, step) =>
    set((s) => (s.runs[id] ? { runs: { ...s.runs, [id]: { ...s.runs[id], text: "", steps: [...s.runs[id].steps, step] } } } : s)),
  runFinished: (id) =>
    set((s) => {
      const runs = { ...s.runs };
      delete runs[id];
      return { runs };
    }),
  setDoc: (id, status) => set((s) => ({ docStatus: { ...s.docStatus, [id]: status } })),
  setOnline: (online) => set({ online }),
  notify: (toast) => {
    clearTimeout(toastTimer);
    set({ toast });
    toastTimer = setTimeout(() => set({ toast: null }), 3200);
  },
}));

export const liveFor = (runs: Record<string, LiveRun>, conversationId: string) =>
  Object.values(runs).filter((r) => r.conversationId === conversationId);
