import { del, list } from "@vercel/blob";
import { storageMode } from "@/lib/server/auth";

export const dynamic = "force-dynamic";

const RETENTION_DAYS = 7;

/** Daily Vercel Cron: encrypted scans are a transit copy, deleted after 7 days. */
export async function GET(request: Request) {
  const secret = process.env.CRON_SECRET;
  if (!secret || request.headers.get("authorization") !== `Bearer ${secret}`) return new Response("Unauthorized", { status: 401 });
  if (storageMode() !== "vercel") return Response.json({ deleted: 0, mode: storageMode() });
  const limit = Date.now() - RETENTION_DAYS * 86400_000;
  let cursor: string | undefined;
  const old: string[] = [];
  do {
    const r = await list({ prefix: "scans/", cursor });
    for (const b of r.blobs) if (new Date(b.uploadedAt).getTime() < limit) old.push(b.url);
    cursor = r.hasMore ? r.cursor : undefined;
  } while (cursor);
  for (let i = 0; i < old.length; i += 500) await del(old.slice(i, i + 500));
  return Response.json({ deleted: old.length });
}
