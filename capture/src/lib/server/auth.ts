import { timingSafeEqual } from "node:crypto";

/** The relay is closed unless RELAY_ACCESS_KEY is configured (fail closed). */
export function relayKeyConfigured(): boolean {
  return (process.env.RELAY_ACCESS_KEY ?? "").length >= 16;
}

export function keyOk(given: string | null | undefined): boolean {
  const want = process.env.RELAY_ACCESS_KEY ?? "";
  if (want.length < 16 || !given) return false;
  const a = Buffer.from(want), b = Buffer.from(given);
  return a.length === b.length && timingSafeEqual(a, b);
}

export function storageMode(): "vercel" | "local" | "off" {
  if (process.env.RELAY_STORAGE === "local" && !process.env.VERCEL) return "local"; // development / tests only
  return process.env.BLOB_READ_WRITE_TOKEN || process.env.BLOB_STORE_ID ? "vercel" : "off";
}

export const SCAN_RE = /^[0-9a-f]{32}$/;
export const OBJECT_RE = /^scans\/([0-9a-f]{32})\/([0-9a-f]{32}|manifest)\.bin$/;
export const MAX_OBJECT_BYTES = 40 * 1024 * 1024;
