/**
 * End-to-end encryption of a scan before it leaves the phone.
 *
 * - one random AES-GCM-256 key per scan, generated on the phone, never sent to the relay;
 * - each object (photo or manifest) = "C3D1" (4 bytes) || IV (12 random bytes) || ciphertext+tag;
 * - the object's relative path (e.g. "3fa4….bin", "manifest.bin") is the GCM additional data,
 *   so an encrypted file cannot be swapped with another one of the same scan;
 * - the transfer code carries the manifest URL and the key: whoever has the code can read the
 *   scan, the relay alone cannot. Format: "c3d1:" + base64url(JSON {m, k, n}).
 * The PC side (backend/cam3d/server/relay.py) implements the same format.
 */
export const MAGIC = new Uint8Array([0x43, 0x33, 0x44, 0x31]); // "C3D1"

const enc = new TextEncoder();
const dec = new TextDecoder();

export function b64url(bytes: Uint8Array): string {
  let s = "";
  for (let i = 0; i < bytes.length; i++) s += String.fromCharCode(bytes[i]);
  return btoa(s).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

export function fromB64url(s: string): Uint8Array {
  const b = atob(s.replace(/-/g, "+").replace(/_/g, "/") + "===".slice((s.length + 3) % 4));
  const out = new Uint8Array(b.length);
  for (let i = 0; i < b.length; i++) out[i] = b.charCodeAt(i);
  return out;
}

export function hex(bytes: Uint8Array): string {
  return Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
}

export function randomHex(nBytes: number): string {
  return hex(crypto.getRandomValues(new Uint8Array(nBytes)));
}

export function newKey(): Uint8Array {
  return crypto.getRandomValues(new Uint8Array(32));
}

async function importKey(raw: Uint8Array): Promise<CryptoKey> {
  return crypto.subtle.importKey("raw", raw as BufferSource, { name: "AES-GCM" }, false, ["encrypt", "decrypt"]);
}

export async function sha256Hex(data: Uint8Array): Promise<string> {
  return hex(new Uint8Array(await crypto.subtle.digest("SHA-256", data as BufferSource)));
}

export async function encryptObject(key: Uint8Array, path: string, plain: Uint8Array, iv?: Uint8Array): Promise<Uint8Array> {
  const nonce = iv ?? crypto.getRandomValues(new Uint8Array(12));
  const k = await importKey(key);
  const ct = new Uint8Array(await crypto.subtle.encrypt({ name: "AES-GCM", iv: nonce as BufferSource, additionalData: enc.encode(path) }, k, plain as BufferSource));
  const out = new Uint8Array(4 + 12 + ct.length);
  out.set(MAGIC, 0);
  out.set(nonce, 4);
  out.set(ct, 16);
  return out;
}

export async function decryptObject(key: Uint8Array, path: string, blob: Uint8Array): Promise<Uint8Array> {
  if (blob.length < 16 + 16 || !MAGIC.every((b, i) => blob[i] === b)) throw new Error("Objet chiffré invalide");
  const k = await importKey(key);
  const pt = await crypto.subtle.decrypt({ name: "AES-GCM", iv: blob.slice(4, 16) as BufferSource, additionalData: enc.encode(path) }, k, blob.slice(16) as BufferSource);
  return new Uint8Array(pt);
}

export interface ManifestPhoto { path: string; name: string; size: number; sha256: string; type: string }
export interface Manifest { v: 1; name: string; created: number; updated: number; photos: ManifestPhoto[] }

export async function encryptManifest(key: Uint8Array, m: Manifest): Promise<Uint8Array> {
  return encryptObject(key, "manifest.bin", enc.encode(JSON.stringify(m)));
}

export async function decryptManifest(key: Uint8Array, blob: Uint8Array): Promise<Manifest> {
  return JSON.parse(dec.decode(await decryptObject(key, "manifest.bin", blob)));
}

export interface TransferCode { m: string; k: string; n: string }

export function encodeTransferCode(manifestUrl: string, key: Uint8Array, name: string): string {
  return "c3d1:" + b64url(enc.encode(JSON.stringify({ m: manifestUrl, k: b64url(key), n: name } satisfies TransferCode)));
}

export function decodeTransferCode(code: string): TransferCode {
  const c = code.trim().replace(/^.*#/, "");
  if (!c.startsWith("c3d1:")) throw new Error("Code de transfert invalide");
  const t = JSON.parse(dec.decode(fromB64url(c.slice(5)))) as TransferCode;
  if (!t.m || !t.k || fromB64url(t.k).length !== 32) throw new Error("Code de transfert incomplet");
  return t;
}
