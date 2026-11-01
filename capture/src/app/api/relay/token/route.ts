import { handleUpload, type HandleUploadBody } from "@vercel/blob/client";
import { keyOk, MAX_OBJECT_BYTES, OBJECT_RE, storageMode } from "@/lib/server/auth";

export const dynamic = "force-dynamic";

/** Issues short-lived upload tokens for ENCRYPTED objects only, to holders of the relay access key. */
export async function POST(request: Request) {
  if (storageMode() !== "vercel") return Response.json({ error: "Relais non configuré" }, { status: 503 });
  const body = (await request.json()) as HandleUploadBody;
  try {
    const result = await handleUpload({
      body,
      request,
      onBeforeGenerateToken: async (pathname, clientPayload) => {
        const { key, overwrite } = JSON.parse(clientPayload || "{}");
        if (!keyOk(key)) throw new Error("Clé d'accès du relais refusée");
        const m = OBJECT_RE.exec(pathname);
        if (!m) throw new Error("Chemin refusé");
        const isManifest = m[2] === "manifest";
        return {
          allowedContentTypes: ["application/octet-stream"],
          maximumSizeInBytes: isManifest ? 2 * 1024 * 1024 : MAX_OBJECT_BYTES,
          addRandomSuffix: false,
          allowOverwrite: isManifest && !!overwrite,
          cacheControlMaxAge: 60,
          validUntil: Date.now() + 10 * 60 * 1000,
        };
      },
    });
    return Response.json(result);
  } catch (e) {
    return Response.json({ error: (e as Error).message }, { status: 403 });
  }
}
