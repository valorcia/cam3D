/**
 * Encrypted relay client. Photos are encrypted on the phone (crypto.ts) then
 * uploaded either to Vercel Blob (production) or to the local development
 * store (/api/relay/dev). The relay never receives a key or a clear photo.
 */
import { upload } from "@vercel/blob/client";
import { decodeTransferCode, encodeTransferCode, encryptManifest, encryptObject, fromB64url, sha256Hex, type Manifest } from "./crypto";
import { db, settings, type Scan } from "./db";

export interface RelayStatus { enabled: boolean; mode: "vercel" | "local" | "off"; reason?: string }

let statusCache: RelayStatus | null = null;
const LAST = "cam3d.relayStatus";

/** Relay configuration. A failed check (offline) is never cached: the last known
 *  status is used meanwhile, and the next call after reconnection asks again. */
export async function relayStatus(force = false): Promise<RelayStatus> {
  if (statusCache && !force) return statusCache;
  try {
    const r = await fetch("/api/relay/status", { cache: "no-store" });
    if (!r.ok) throw new Error(String(r.status));
    statusCache = await r.json();
    try { localStorage.setItem(LAST, JSON.stringify(statusCache)); } catch { /* ignore */ }
    return statusCache!;
  } catch {
    try {
      const last = localStorage.getItem(LAST);
      if (last) return JSON.parse(last) as RelayStatus;
    } catch { /* ignore */ }
    return { enabled: false, mode: "off", reason: "hors connexion" };
  }
}

if (typeof window !== "undefined") window.addEventListener("online", () => { statusCache = null; });

export async function checkKey(key: string): Promise<boolean> {
  const r = await fetch("/api/relay/check", { method: "POST", headers: { "x-relay-key": key } });
  return r.ok;
}

async function putObject(path: string, data: Uint8Array, overwrite: boolean): Promise<string> {
  const st = await relayStatus();
  const key = settings.relayKey;
  if (st.mode === "local") {
    const r = await fetch(`/api/relay/dev/${path}`, { method: "PUT", headers: { "x-relay-key": key }, body: data as BodyInit });
    if (!r.ok) throw new Error(r.status === 403 ? "Clé d'accès du relais refusée" : `Relais : erreur ${r.status}`);
    return `${location.origin}/api/relay/dev/${path}`;
  }
  if (st.mode !== "vercel") throw new Error("Relais indisponible");
  const blob = await upload(path, new Blob([data as BlobPart], { type: "application/octet-stream" }), {
    access: "public",
    handleUploadUrl: "/api/relay/token",
    contentType: "application/octet-stream",
    clientPayload: JSON.stringify({ key, overwrite }),
  });
  return blob.url;
}

async function deleteRemote(scanId: string, paths?: string[]) {
  await fetch("/api/relay/delete", {
    method: "POST",
    headers: { "Content-Type": "application/json", "x-relay-key": settings.relayKey },
    body: JSON.stringify({ scanId, paths }),
  });
}

const running = new Set<string>();

/** Upload pending photos of a scan, then (re)write its encrypted manifest. Safe to call often. */
export async function syncScan(scanId: string, onProgress?: () => void): Promise<void> {
  if (running.has(scanId) || (typeof navigator !== "undefined" && !navigator.onLine)) return;
  const scan = await db.scan(scanId);
  if (!scan?.relay || !settings.relayKey) return;
  const st = await relayStatus();
  if (!st.enabled) return;
  running.add(scanId);
  try {
    const key = fromB64url(scan.key);
    const photos = await db.photos(scanId);
    let changed = false;
    for (const p of photos) {
      if (p.uploaded) continue;
      const plain = new Uint8Array(await p.blob.arrayBuffer());
      const rel = `${p.id}.bin`;
      const sealed = await encryptObject(key, rel, plain);
      await putObject(`scans/${scan.id}/${rel}`, sealed, false);
      await db.putPhoto({ ...p, uploaded: true, sha256: p.sha256 ?? (await sha256Hex(plain)) });
      changed = true;
      onProgress?.();
    }
    const now = await db.photos(scanId);
    if (changed || scan.manifestCount !== now.filter((p) => p.uploaded).length || !scan.manifestUrl) {
      const m: Manifest = {
        v: 1, name: scan.name, created: scan.created, updated: Date.now(),
        photos: now.filter((p) => p.uploaded).map((p) => ({ path: `${p.id}.bin`, name: p.name, size: p.size, sha256: p.sha256!, type: p.type })),
      };
      const url = await putObject(`scans/${scan.id}/manifest.bin`, await encryptManifest(key, m), true);
      await db.putScan({ ...scan, manifestUrl: url, manifestCount: m.photos.length });
      onProgress?.();
    }
  } finally {
    running.delete(scanId);
  }
}

export async function removePhotoRemote(scan: Scan, photoId: string) {
  await deleteRemote(scan.id, [`${photoId}.bin`]);
  await db.putScan({ ...scan, manifestCount: -1 }); // force a new manifest at next sync
}

export async function removeScanRemote(scan: Scan) {
  await deleteRemote(scan.id);
  // relay switched off for this scan, otherwise the next sync would upload everything again
  await db.putScan({ ...scan, relay: false, manifestUrl: undefined, manifestCount: undefined });
  for (const p of await db.photos(scan.id)) await db.putPhoto({ ...p, uploaded: false });
}

export function transferCode(scan: Scan): string | null {
  if (!scan.manifestUrl) return null;
  return encodeTransferCode(scan.manifestUrl, fromB64url(scan.key), scan.name);
}

export { decodeTransferCode };
