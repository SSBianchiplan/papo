// Cliente tipado gerado do OpenAPI (src/api/schema.d.ts). Nenhum tipo de API escrito à mão.
import createClient, { type Middleware } from "openapi-fetch";

import { devMode, token } from "../auth";
import type { components, paths } from "./schema";

export type S = components["schemas"];
export type Agent = S["Agent"];
export type Conversation = S["Conversation"];
export type Message = S["Message"];
export type Doc = S["Document"];
export type UserConfig = S["UserConfig"];
export type Me = S["Me"];
export type Run = S["Run"];

export class ApiError extends Error {
  constructor(public status: number, message: string, public hint?: string | null) {
    super(message);
  }
}

async function authHeader(): Promise<Record<string, string>> {
  const t = await token();
  return devMode() ? { "x-dev-user": t.slice(4) } : { Authorization: `Bearer ${t}` };
}

const auth: Middleware = {
  async onRequest({ request }) {
    for (const [k, v] of Object.entries(await authHeader())) request.headers.set(k, v);
    return request;
  },
};

export const api = createClient<paths>({ baseUrl: "" });
api.use(auth);

type Result<T> = { data?: T; error?: unknown; response: Response };

/** Desembrulha resposta: lança ApiError com a mensagem do servidor. */
export async function ok<T>(p: Promise<Result<T>>): Promise<T> {
  const { data, error, response } = await p;
  if (!response.ok) {
    const e = (error ?? {}) as { message?: string; hint?: string; detail?: unknown };
    const msg = e.message ?? (response.status === 422 ? "Dados inválidos." : response.status === 401 ? "Sessão expirada." : "Algo deu errado.");
    throw new ApiError(response.status, msg, e.hint);
  }
  return data as T;
}

/** Upload multipart (fora do gerador: corpo é FormData). */
export async function upload<T>(url: string, file: File): Promise<T> {
  const fd = new FormData();
  fd.append("file", file);
  const r = await fetch(url, { method: "POST", body: fd, headers: await authHeader() });
  const body = (await r.json().catch(() => ({}))) as { message?: string; hint?: string };
  if (!r.ok) throw new ApiError(r.status, body.message ?? "Falha no envio do arquivo.", body.hint);
  return body as T;
}

const imageCache = new Map<string, Promise<string>>();
export function imageUrl(key: string): Promise<string> {
  let p = imageCache.get(key);
  if (!p) {
    p = (async () => {
      const r = await fetch(`/api/images/${key}`, { headers: await authHeader() });
      if (!r.ok) throw new ApiError(r.status, "imagem indisponível");
      return URL.createObjectURL(await r.blob());
    })();
    imageCache.set(key, p);
  }
  return p;
}

export async function downloadExport(): Promise<void> {
  const r = await fetch("/api/export", { headers: await authHeader() });
  if (!r.ok) throw new ApiError(r.status, "Não foi possível exportar.");
  const a = document.createElement("a");
  a.href = URL.createObjectURL(await r.blob());
  a.download = `papo-export-${new Date().toISOString().slice(0, 10)}.json`;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 5000);
}

export { authHeader };

async function documentBlob(id: string): Promise<Blob> {
  const r = await fetch(`/api/documents/${id}/file`, { headers: await authHeader() });
  if (!r.ok) {
    const b = (await r.json().catch(() => ({}))) as { message?: string };
    throw new ApiError(r.status, b.message ?? "Não foi possível abrir o arquivo.");
  }
  return r.blob();
}

export async function downloadDocument(id: string, filename: string): Promise<void> {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(await documentBlob(id));
  a.download = filename;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 5000);
}

export type ManagedDoc = S["ManagedDocument"];
export type StorageStats = S["StorageStats"];
