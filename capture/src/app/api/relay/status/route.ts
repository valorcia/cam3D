import { relayKeyConfigured, storageMode } from "@/lib/server/auth";

export const dynamic = "force-dynamic";

export function GET() {
  const mode = storageMode();
  const enabled = mode !== "off" && relayKeyConfigured();
  return Response.json({ enabled, mode: enabled ? mode : "off", reason: enabled ? undefined : mode === "off" ? "stockage non configuré" : "clé d'accès non configurée" });
}
