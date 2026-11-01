"use client";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { IconPhone } from "@/components/Icons";
import { ErrorBox, Spinner } from "@/components/ui";
import { api } from "@/lib/api";

/** Import of a scan captured anywhere with cam3D Capture (encrypted relay).
 *  The code arrives in the URL fragment (never sent to any server) or is pasted. */
export default function ImportPage() {
  const router = useRouter();
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const h = decodeURIComponent(window.location.hash.slice(1));
    if (h.startsWith("c3d1:")) {
      setCode(h);
      history.replaceState(null, "", window.location.pathname); // do not keep the key in the address bar
    }
  }, []);

  async function go(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true); setError(null);
    try {
      const r = await api.relayImport(code.trim());
      router.push(`/project/?id=${r.project.id}&tab=photos`);
    } catch (err: any) { setError(err.message); setBusy(false); }
  }

  return (
    <div className="mx-auto max-w-lg space-y-6">
      <div className="flex items-center gap-3">
        <span className="grid h-10 w-10 place-items-center rounded-xl bg-white/5 text-accent"><IconPhone /></span>
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Depuis le téléphone</h1>
          <p className="text-sm text-muted">Récupérez un scan pris avec cam3D Capture, n’importe où.</p>
        </div>
      </div>
      <form className="card space-y-3 p-5" onSubmit={go}>
        <label className="block text-sm text-muted">Code de transfert (affiché dans le scan, sur le téléphone)
          <textarea className="input mt-1 h-28 font-mono text-xs" value={code} onChange={(e) => setCode(e.target.value)} placeholder="c3d1:…" data-testid="relay-code" spellCheck={false} />
        </label>
        <button className="btn-primary w-full" disabled={busy || !code.trim()} data-testid="relay-import">{busy ? <Spinner /> : "Importer"}</button>
        {error && <ErrorBox>{error}</ErrorBox>}
        <p className="text-xs text-faint">Les photos sont téléchargées depuis le relais puis déchiffrées sur cet ordinateur ; le relais n’a jamais accès à la clé. Les copies chiffrées sont effacées du relais après 7 jours, ou tout de suite depuis le téléphone (« Retirer ce scan du relais »).</p>
      </form>
      <p className="text-sm text-muted">Sans relais : sur le téléphone, « Partager les photos » ou « Télécharger un ZIP », puis glissez les photos ou le ZIP dans un projet.</p>
    </div>
  );
}
