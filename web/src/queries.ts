// Consultas e mutações do servidor.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, ok, type Agent, type Conversation, type Doc, type Me, type Message, type UserConfig } from "./api/client";
import { useApp } from "./store";

export const useMe = () => useQuery({ queryKey: ["me"], queryFn: () => ok(api.GET("/api/me")) });
export const useAgents = () => useQuery({ queryKey: ["agents"], queryFn: () => ok(api.GET("/api/agents")) });
export const useConversations = () => useQuery({ queryKey: ["conversations"], queryFn: () => ok(api.GET("/api/conversations")) });
export const useRuns = () => useQuery({ queryKey: ["runs"], queryFn: () => ok(api.GET("/api/runs", { params: { query: { limit: 10 } } })) });

export const useMessages = (cid: string) =>
  useQuery({
    queryKey: ["messages", cid],
    queryFn: () => ok(api.GET("/api/conversations/{cid}/messages", { params: { path: { cid }, query: { limit: 80 } } })),
  });

export const useAgentDocs = (agentId: string | undefined) =>
  useQuery({
    queryKey: ["agentDocs", agentId],
    enabled: !!agentId,
    queryFn: () => ok(api.GET("/api/agents/{agent_id}/documents", { params: { path: { agent_id: agentId! } } })),
  });

export function useSettings() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (s: UserConfig) => ok(api.PUT("/api/settings", { body: s })),
    onMutate: (s) => {
      qc.setQueryData<Me>(["me"], (old) => (old ? { ...old, settings: s } : old));
    },
    onError: (e: Error) => {
      useApp.getState().notify(e.message);
      void qc.invalidateQueries({ queryKey: ["me"] });
    },
  });
}

export function useSend(cid: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { body: string; document_id?: string | null; image_key?: string | null }) =>
      ok(api.POST("/api/conversations/{cid}/messages", { params: { path: { cid } }, body })),
    onSuccess: (m: Message) => {
      qc.setQueryData<Message[]>(["messages", cid], (old) => (old && !old.some((x) => x.id === m.id) ? [...old, m] : old));
      qc.setQueryData<Conversation[]>(["conversations"], (old) => old?.map((c) => (c.id === cid ? { ...c, active_run: true, last_message: m } : c)));
    },
    onError: (e: Error) => useApp.getState().notify(e.message),
  });
}

export const cancelRun = (cid: string) => ok(api.POST("/api/conversations/{cid}/cancel", { params: { path: { cid } } }));

export async function openDm(agentId: string): Promise<Conversation> {
  return ok(api.POST("/api/conversations", { body: { kind: "dm", agent_id: agentId, emoji: "👥", color: "#5B6B8C" } }));
}

export type { Agent, Doc };
