import type { Job, Project, ProjectDetail, SystemInfo, Whoami, Photo, ExportFile } from "./types";

/** Empty in production (UI served by the API itself); set in development. */
export const API_BASE = (process.env.NEXT_PUBLIC_API_BASE ?? "").replace(/\/$/, "");

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, { credentials: "include", ...init });
  } catch {
    throw new ApiError(0, "Serveur cam3D injoignable. Vérifiez que l'application est lancée sur l'ordinateur.");
  }
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = typeof body.detail === "string" ? body.detail : (body.rejected?.[0]?.error ?? JSON.stringify(body.detail ?? body));
    } catch { /* not JSON */ }
    throw new ApiError(res.status, detail);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

const json = (method: string, body?: unknown): RequestInit => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: body === undefined ? undefined : JSON.stringify(body),
});

export const url = (path: string) => `${API_BASE}${path}`;

export function wsUrl(path: string): string {
  if (API_BASE) return API_BASE.replace(/^http/, "ws") + path;
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${window.location.host}${path}`;
}

export const api = {
  whoami: () => request<Whoami>("/api/whoami"),
  system: (refresh = false) => request<SystemInfo>(`/api/system${refresh ? "?refresh=true" : ""}`),

  projects: (archived = false) => request<Project[]>(`/api/projects?archived=${archived}`),
  project: (id: string) => request<ProjectDetail>(`/api/projects/${id}`),
  createProject: (name: string) => request<Project>("/api/projects", json("POST", { name })),
  updateProject: (id: string, patch: { name?: string; archived?: boolean }) =>
    request<Project>(`/api/projects/${id}`, json("PATCH", patch)),
  duplicateProject: (id: string) => request<Project>(`/api/projects/${id}/duplicate`, json("POST")),
  deleteProject: (id: string) => request<{ deleted: string }>(`/api/projects/${id}?confirm=true`, { method: "DELETE" }),

  deletePhoto: (id: string, name: string) =>
    request<{ deleted: string }>(`/api/projects/${id}/photos/${encodeURIComponent(name)}`, { method: "DELETE" }),

  reconstruct: (id: string, profile: string, formats: string[], resume = false) =>
    request<Job>(`/api/projects/${id}/reconstruct`, json("POST", { profile, formats, resume })),
  requestExport: (id: string, formats: string[]) =>
    request<Job>(`/api/projects/${id}/exports`, json("POST", { formats })),
  exports: (id: string) => request<ExportFile[]>(`/api/projects/${id}/exports`),
  job: (jid: string) => request<Job>(`/api/jobs/${jid}`),
  projectJobs: (id: string) => request<Job[]>(`/api/projects/${id}/jobs`),
  cancelJob: (jid: string) => request<Job>(`/api/jobs/${jid}/cancel`, json("POST")),
  retryJob: (jid: string) => request<Job>(`/api/jobs/${jid}/retry`, json("POST")),
  logs: (id: string) => request<{ name: string; size_bytes: number }[]>(`/api/projects/${id}/logs`),
  log: async (id: string, name: string, tail = 400) => {
    const res = await fetch(url(`/api/projects/${id}/logs/${name}?tail=${tail}`), { credentials: "include" });
    if (!res.ok) throw new ApiError(res.status, "Journal indisponible");
    return res.text();
  },
  putThumbnail: (id: string, blob: Blob) =>
    request<{ ok: boolean }>(`/api/projects/${id}/thumbnail.jpg`, { method: "PUT", body: blob }),

  pairSession: (next = "") =>
    request<{ id: string; code: string; expires_at: number; urls: string[]; https_urls: string[]; secure: boolean }>(
      `/api/pair/sessions${next ? `?next=${encodeURIComponent(next)}` : ""}`, json("POST")),
  tls: () => request<{ enabled: boolean; https_port: number | null; http_port: number | null; ca: { fingerprint_sha256: string; not_after: string } | null }>("/api/tls"),
  pairPending: () => request<{ id: string; device_name: string; created_at: number }[]>("/api/pair/pending"),
  pairApprove: (rid: string) => request(`/api/pair/requests/${rid}/approve`, json("POST")),
  pairReject: (rid: string) => request(`/api/pair/requests/${rid}/reject`, json("POST")),
  pairClaim: (code: string, device_name: string) =>
    request<{ request_id: string; secret: string; status: string }>("/api/pair/claim", json("POST", { code, device_name })),
  pairPoll: (rid: string, secret: string) =>
    request<{ status: string; token?: string }>(`/api/pair/requests/${rid}?secret=${encodeURIComponent(secret)}`),
  devices: () => request<{ id: string; name: string; created_at: number; expires_at: number; last_seen: number | null }[]>("/api/devices"),
  revokeDevice: (id: string) => request(`/api/devices/${id}`, { method: "DELETE" }),
};

/** Upload a video; the server extracts frames in a background job (returned). */
export function uploadVideo(projectId: string, file: File, onProgress?: (f: number) => void): Promise<Job> {
  return new Promise((resolve, reject) => {
    const form = new FormData();
    form.append("file", file, file.name);
    const xhr = new XMLHttpRequest();
    xhr.open("POST", url(`/api/projects/${projectId}/video`));
    xhr.withCredentials = true;
    xhr.upload.onprogress = (e) => { if (e.lengthComputable && onProgress) onProgress(e.loaded / e.total); };
    xhr.onerror = () => reject(new ApiError(0, "Transfert interrompu : vérifiez la connexion au réseau local."));
    xhr.onload = () => {
      let body: any = null;
      try { body = JSON.parse(xhr.responseText); } catch { /* ignore */ }
      if (xhr.status >= 200 && xhr.status < 300) resolve(body);
      else reject(new ApiError(xhr.status, body?.detail ?? `Erreur ${xhr.status}`));
    };
    xhr.send(form);
  });
}

/** Upload with real byte-level progress (fetch has no upload progress). */
export function uploadPhotos(
  projectId: string,
  files: File[],
  onProgress?: (fraction: number) => void,
): Promise<{ added: Photo[]; rejected: { file: string; error: string }[]; photo_count?: number }> {
  return new Promise((resolve, reject) => {
    const form = new FormData();
    for (const f of files) form.append("files", f, f.name);
    const xhr = new XMLHttpRequest();
    xhr.open("POST", url(`/api/projects/${projectId}/photos`));
    xhr.withCredentials = true;
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable && onProgress) onProgress(e.loaded / e.total);
    };
    xhr.onerror = () => reject(new ApiError(0, "Transfert interrompu : vérifiez la connexion au réseau local."));
    xhr.onload = () => {
      let body: any = null;
      try { body = JSON.parse(xhr.responseText); } catch { /* ignore */ }
      if (xhr.status >= 200 && xhr.status < 300) resolve(body);
      else if (body?.rejected) resolve(body);
      else reject(new ApiError(xhr.status, body?.detail ?? `Erreur ${xhr.status}`));
    };
    xhr.send(form);
  });
}
