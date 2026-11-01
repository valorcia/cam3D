import { del, list } from "@vercel/blob";
import { rm } from "node:fs/promises";
import path from "node:path";
import { keyOk, SCAN_RE, storageMode } from "@/lib/server/auth";
import { DEV_ROOT } from "@/lib/server/devstore";

export const dynamic = "force-dynamic";

/** Deletes a whole scan (or some of its objects) from the relay. */
export async function POST(request: Request) {
  if (!keyOk(request.headers.get("x-relay-key"))) return Response.json({ error: "Clé refusée" }, { status: 403 });
  const { scanId, paths } = (await request.json()) as { scanId: string; paths?: string[] };
  if (!SCAN_RE.test(scanId || "")) return Response.json({ error: "Scan invalide" }, { status: 400 });
  const names = paths?.filter((p) => /^[0-9a-f]{32}\.bin$/.test(p));
  const mode = storageMode();
  if (mode === "local") {
    if (names) for (const n of names) await rm(path.join(DEV_ROOT, "scans", scanId, n), { force: true });
    else await rm(path.join(DEV_ROOT, "scans", scanId), { recursive: true, force: true });
    return Response.json({ deleted: true });
  }
  if (mode !== "vercel") return Response.json({ error: "Relais non configuré" }, { status: 503 });
  const prefix = `scans/${scanId}/`;
  let cursor: string | undefined;
  const urls: string[] = [];
  do {
    const r = await list({ prefix, cursor });
    for (const b of r.blobs) if (!names || names.includes(b.pathname.slice(prefix.length))) urls.push(b.url);
    cursor = r.hasMore ? r.cursor : undefined;
  } while (cursor);
  if (urls.length) await del(urls);
  return Response.json({ deleted: urls.length });
}
