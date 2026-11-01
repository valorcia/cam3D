import { describe, expect, it } from "vitest";
import vector from "./__fixtures__/vector.json";
import { decodeTransferCode, decryptManifest, decryptObject, encodeTransferCode, encryptManifest, encryptObject, hex, newKey, sha256Hex } from "./crypto";

const fromHex = (h: string) => new Uint8Array(h.match(/../g)!.map((x) => parseInt(x, 16)));

describe("crypto (format shared with the PC, backend/cam3d/server/relay.py)", () => {
  it("produces exactly the Python test vector", async () => {
    const blob = await encryptObject(fromHex(vector.key_hex), vector.path, new TextEncoder().encode(vector.plain_utf8), fromHex(vector.iv_hex));
    expect(hex(blob)).toBe(vector.blob_hex);
    const plain = await decryptObject(fromHex(vector.key_hex), vector.path, fromHex(vector.blob_hex));
    expect(new TextDecoder().decode(plain)).toBe(vector.plain_utf8);
    expect(await sha256Hex(plain)).toBe(vector.sha256);
  });

  it("rejects a wrong key, a wrong path (swapped file) and tampering", async () => {
    const key = newKey();
    const data = crypto.getRandomValues(new Uint8Array(5000));
    const blob = await encryptObject(key, "a.bin", data);
    await expect(decryptObject(newKey(), "a.bin", blob)).rejects.toThrow();
    await expect(decryptObject(key, "b.bin", blob)).rejects.toThrow();
    const bad = blob.slice(); bad[100] ^= 1;
    await expect(decryptObject(key, "a.bin", bad)).rejects.toThrow();
    expect(Array.from(await decryptObject(key, "a.bin", blob))).toEqual(Array.from(data));
  });

  it("round-trips the manifest and the transfer code", async () => {
    const key = newKey();
    const m = { v: 1 as const, name: "Chaise", created: 1, updated: 2, photos: [{ path: "x.bin", name: "IMG_1.jpg", size: 3, sha256: "ab", type: "image/jpeg" }] };
    expect(await decryptManifest(key, await encryptManifest(key, m))).toEqual(m);
    const code = encodeTransferCode("https://abc.public.blob.vercel-storage.com/scans/ff/manifest.bin", key, "Chaise");
    expect(code.startsWith("c3d1:")).toBe(true);
    const t = decodeTransferCode(`https://capture.example/t/#${code}`);
    expect(t.n).toBe("Chaise");
    expect(() => decodeTransferCode("n'importe quoi")).toThrow();
  });
});
