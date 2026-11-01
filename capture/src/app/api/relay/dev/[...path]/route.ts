import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { keyOk, MAX_OBJECT_BYTES, OBJECT_RE, storageMode } from "@/lib/server/auth";
import { DEV_ROOT } from "@/lib/server/devstore";

export const dynamic = "force-dynamic";

function target(parts: string[]): string | null {
  const p = parts.join("/");
  return storageMode() === "local" && OBJECT_RE.test(p) ? path.join(DEV_ROOT, p) : null;
}

export async function PUT(request: Request, ctx: { params: Promise<{ path: string[] }> }) {
  const f = target((await ctx.params).path);
  if (!f) return new Response("Not found", { status: 404 });
  if (!keyOk(request.headers.get("x-relay-key"))) return new Response("Forbidden", { status: 403 });
  const data = new Uint8Array(await request.arrayBuffer());
  if (data.length > MAX_OBJECT_BYTES) return new Response("Too large", { status: 413 });
  await mkdir(path.dirname(f), { recursive: true });
  await writeFile(f, data);
  return Response.json({ ok: true });
}

export async function GET(_: Request, ctx: { params: Promise<{ path: string[] }> }) {
  const f = target((await ctx.params).path);
  if (!f) return new Response("Not found", { status: 404 });
  try {
    return new Response(await readFile(f), { headers: { "Content-Type": "application/octet-stream" } });
  } catch {
    return new Response("Not found", { status: 404 });
  }
}
