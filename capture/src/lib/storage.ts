/** Browser storage of the photos (IndexedDB): keep it, and know how much room is left. */

export interface StorageInfo { usage: number; quota: number; persisted: boolean | null }

/** Asks the browser not to evict the photos under storage pressure (Safari otherwise may, after a while). */
export async function ensurePersistent(): Promise<boolean | null> {
  try {
    const s = navigator.storage;
    if (!s?.persist) return null;
    if (await s.persisted?.()) return true;
    return await s.persist();
  } catch { return null; }
}

export async function storageInfo(): Promise<StorageInfo | null> {
  try {
    const s = navigator.storage;
    if (!s?.estimate) return null;
    const e = await s.estimate();
    return { usage: e.usage ?? 0, quota: e.quota ?? 0, persisted: (await s.persisted?.()) ?? null };
  } catch { return null; }
}

export function formatBytes(n: number): string {
  if (n >= 1e9) return `${(n / 1e9).toLocaleString("fr-FR", { maximumFractionDigits: 1 })} Go`;
  if (n >= 1e6) return `${Math.round(n / 1e6).toLocaleString("fr-FR")} Mo`;
  return `${Math.max(0, Math.round(n / 1e3)).toLocaleString("fr-FR")} ko`;
}

/** Room left, below which a continuous scan is stopped before writes start failing. */
export const LOW_STORAGE_BYTES = 300e6;
