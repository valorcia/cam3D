import { keyOk } from "@/lib/server/auth";

export const dynamic = "force-dynamic";

export function POST(request: Request) {
  return keyOk(request.headers.get("x-relay-key")) ? Response.json({ ok: true }) : Response.json({ ok: false }, { status: 403 });
}
