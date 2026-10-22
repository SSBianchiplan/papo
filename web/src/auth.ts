// Login OIDC (Keycloak) com PKCE. Configuração lida em runtime de /config.json para a mesma imagem servir qualquer domínio.
import { User, UserManager, WebStorageStateStore } from "oidc-client-ts";

export type RuntimeConfig = { authMode: "oidc" | "dev"; authority: string; clientId: string };

let manager: UserManager | null = null;
let cfg: RuntimeConfig = { authMode: "oidc", authority: "", clientId: "papo-web" };
let user: User | null = null;

export async function loadConfig(): Promise<RuntimeConfig> {
  try {
    const r = await fetch("/config.json", { cache: "no-store" });
    if (r.ok) cfg = { ...cfg, ...((await r.json()) as Partial<RuntimeConfig>) };
  } catch {
    /* sem config.json: usa variáveis de build */
  }
  if (import.meta.env.VITE_AUTH_MODE) cfg.authMode = import.meta.env.VITE_AUTH_MODE;
  if (import.meta.env.VITE_OIDC_AUTHORITY) cfg.authority = import.meta.env.VITE_OIDC_AUTHORITY;
  if (import.meta.env.VITE_OIDC_CLIENT_ID) cfg.clientId = import.meta.env.VITE_OIDC_CLIENT_ID;
  return cfg;
}

function mgr(): UserManager {
  if (!manager) {
    manager = new UserManager({
      authority: cfg.authority,
      client_id: cfg.clientId,
      redirect_uri: `${location.origin}/`,
      post_logout_redirect_uri: `${location.origin}/`,
      response_type: "code",
      scope: "openid profile email",
      automaticSilentRenew: true,
      userStore: new WebStorageStateStore({ store: sessionStorage }),
    });
    manager.events.addUserLoaded((u) => {
      user = u;
    });
    manager.events.addSilentRenewError(() => void mgr().signinRedirect());
  }
  return manager;
}

/** Garante sessão. Retorna false enquanto redireciona para o login. */
export async function ensureLogin(): Promise<boolean> {
  if (cfg.authMode === "dev") {
    let dev = localStorage.getItem("papo.devUser");
    if (!dev) {
      dev = prompt("Modo desenvolvimento: nome do usuário de teste") || "dev";
      localStorage.setItem("papo.devUser", dev);
    }
    return true;
  }
  const params = new URLSearchParams(location.search);
  if (params.has("code") && params.has("state")) {
    user = await mgr().signinRedirectCallback();
    history.replaceState(null, "", location.pathname);
    return true;
  }
  user = await mgr().getUser();
  if (!user || user.expired) {
    await mgr().signinRedirect();
    return false;
  }
  return true;
}

export async function token(): Promise<string> {
  if (cfg.authMode === "dev") return `dev:${localStorage.getItem("papo.devUser") ?? "dev"}`;
  if (!user || user.expired) user = await mgr().signinSilent().catch(() => null);
  if (!user) {
    await mgr().signinRedirect();
    throw new Error("sessão expirada");
  }
  return user.access_token;
}

export async function logout(): Promise<void> {
  if (cfg.authMode === "dev") {
    localStorage.removeItem("papo.devUser");
    location.reload();
    return;
  }
  await mgr().signoutRedirect();
}

export const devMode = () => cfg.authMode === "dev";
