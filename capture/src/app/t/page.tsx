"use client";
import { useEffect, useState } from "react";
import { ErrorBox, Logo } from "@/components/ui";
import { decodeTransferCode } from "@/lib/crypto";

/** Bridge opened on the computer: hands the transfer code to the local cam3D app.
 *  The code travels in the URL fragment (#…), which browsers never send to the server. */
export default function Transfer() {
  const [code, setCode] = useState("");
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [local, setLocal] = useState("http://127.0.0.1:8765");
  useEffect(() => {
    const c = decodeURIComponent(location.hash.slice(1));
    setCode(c);
    try { setName(decodeTransferCode(c).n); } catch (e: any) { setError(e.message); }
  }, []);
  return (
    <div className="space-y-6 pt-2">
      <Logo />
      <h1 className="text-2xl font-semibold tracking-tight">Récupérer « {name || "scan"} » sur cet ordinateur</h1>
      {error ? <ErrorBox>{error}</ErrorBox> : (
        <>
          <p className="text-sm text-muted">Lancez cam3D sur cet ordinateur, puis ouvrez l’import : les photos seront téléchargées et déchiffrées par cam3D, directement sur votre ordinateur.</p>
          <a className="btn-primary w-full py-3" href={`${local}/import/#${encodeURIComponent(code)}`} data-testid="open-local">Importer dans cam3D</a>
          <details className="text-sm text-muted">
            <summary className="cursor-pointer">cam3D utilise une autre adresse</summary>
            <input className="input mt-2" value={local} onChange={(e) => setLocal(e.target.value.replace(/\/$/, ""))} aria-label="Adresse de cam3D" />
          </details>
          <div className="space-y-1">
            <p className="text-xs text-faint">Ou copiez le code dans cam3D › Depuis le téléphone :</p>
            <textarea readOnly className="input h-20 font-mono text-[10px]" value={code} onFocus={(e) => e.target.select()} />
          </div>
        </>
      )}
    </div>
  );
}
