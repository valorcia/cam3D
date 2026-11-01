"use client";
import { create } from "zustand";
import { api, wsUrl } from "./api";
import type { JobEvent, ServerMessage, SystemInfo, Whoami } from "./types";

interface AppState {
  whoami: Whoami | null;
  authError: number | null;
  system: SystemInfo | null;
  /** live events per job id, from the WebSocket */
  jobEvents: Record<string, JobEvent[]>;
  /** bumps whenever a job starts/finishes so pages can refetch */
  revision: number;
  connected: boolean;
  init: () => Promise<void>;
  seedEvents: (jobId: string, events: JobEvent[]) => void;
}

let socket: WebSocket | null = null;
let retry = 0;

export const useApp = create<AppState>((set, get) => ({
  whoami: null,
  authError: null,
  system: null,
  jobEvents: {},
  revision: 0,
  connected: false,

  async init() {
    if (get().whoami || get().authError) return;
    try {
      const who = await api.whoami();
      set({ whoami: who, authError: null });
      api.system().then((system) => set({ system })).catch(() => undefined);
      connect(set);
    } catch (e: any) {
      set({ authError: e?.status ?? 0 });
    }
  },

  seedEvents(jobId, events) {
    set((s) => (s.jobEvents[jobId]?.length ? s : { jobEvents: { ...s.jobEvents, [jobId]: events } }));
  },
}));

function connect(set: (fn: (s: AppState) => Partial<AppState>) => void) {
  if (typeof window === "undefined" || socket) return;
  socket = new WebSocket(wsUrl("/api/events"));
  socket.onopen = () => { retry = 0; set(() => ({ connected: true })); };
  socket.onclose = () => {
    socket = null;
    set(() => ({ connected: false }));
    const delay = Math.min(10_000, 500 * 2 ** retry++);
    setTimeout(() => connect(set), delay);
  };
  socket.onmessage = (ev) => {
    let msg: ServerMessage;
    try { msg = JSON.parse(ev.data); } catch { return; }
    if (msg.type === "job_event") {
      set((s) => ({ jobEvents: { ...s.jobEvents, [msg.job_id]: [...(s.jobEvents[msg.job_id] ?? []), msg] } }));
      if (msg.status === "started" || msg.status === "finished") set((s) => ({ revision: s.revision + 1 }));
    } else if (msg.type !== "ping") {
      set((s) => ({ revision: s.revision + 1 }));
    }
  };
}
