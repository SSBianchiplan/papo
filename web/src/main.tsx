import "@fontsource/manrope/400.css";
import "@fontsource/manrope/600.css";
import "@fontsource/manrope/700.css";
import "./styles.css";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./App";
import { ApiError } from "./api/client";
import { ensureLogin, loadConfig } from "./auth";
import { connectRealtime } from "./realtime";

const qc = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      refetchOnWindowFocus: true,
      retry: (n, e) => !(e instanceof ApiError && e.status < 500) && n < 2,
    },
  },
});

function registerServiceWorker() {
  if (!import.meta.env.PROD || !("serviceWorker" in navigator)) return;
  addEventListener("load", () => void navigator.serviceWorker.register("/sw.js").catch(() => undefined));
}

async function boot() {
  registerServiceWorker();
  await loadConfig();
  if (!(await ensureLogin())) return;          // redirecionando para o login
  connectRealtime(qc);
  createRoot(document.getElementById("root")!).render(
    <StrictMode><QueryClientProvider client={qc}><App /></QueryClientProvider></StrictMode>,
  );
}
void boot();
