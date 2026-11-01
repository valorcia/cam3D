"use client";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { IconCube } from "@/components/Icons";
import { ErrorBox, Spinner } from "@/components/ui";
import { api } from "@/lib/api";

function guessDeviceName() {
  if (typeof navigator === "undefined") return "Téléphone";
  const ua = navigator.userAgent;
  if (/iPhone/.test(ua)) return "iPhone";
  if (/iPad/.test(ua)) return "iPad";
  if (/Android/.test(ua)) return "Android";
  return "Navigateur";
}

function Pair() {
  const params = useSearchParams();
  const router = useRouter();
  const [code, setCode] = useState(params.get("code") ?? "");
  const [name, setName] = useState("");
  const [state, setState] = useState<"form" | "waiting" | "rejected" | "done">("form");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => { setName(guessDeviceName()); }, []);

  async function submit(e: React.FormEvent) {
    e.preventDefault(); setError(null);
    try {
      const r = await api.pairClaim(code.trim(), name.trim() || "Téléphone");
      setState("waiting");
      const poll = async () => {
        try {
          const s = await api.pairPoll(r.request_id, r.secret);
          if (s.status === "approved") { setState("done"); setTimeout(() => { window.location.href = "/"; }, 600); return; }
          if (s.status === "rejected") { setState("rejected"); return; }
          setTimeout(poll, 1500);
        } catch (err: any) { setError(err.message); setState("form"); }
      };
      poll();
    } catch (err: any) { setError(err.message); }
  }

  return (
    <div className="mx-auto max-w-sm space-y-6 pt-6 text-center">
      <span className="mx-auto grid h-14 w-14 place-items-center rounded-2xl bg-accent-strong/20 text-accent"><IconCube className="h-7 w-7" /></span>
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Connecter ce téléphone</h1>
        <p className="mt-1 text-sm text-muted">Saisissez le code affiché sur l’ordinateur (Paramètres › Connecter un téléphone).</p>
      </div>
      {error && <ErrorBox>{error}</ErrorBox>}
      {state === "form" && (
        <form className="space-y-3 text-left" onSubmit={submit}>
          <label className="block text-sm text-muted">Code à 6 chiffres
            <input className="input mt-1 text-center font-mono text-2xl tracking-[0.4em]" inputMode="numeric" pattern="[0-9]{6}" maxLength={6} value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))} required data-testid="pair-code-input" />
          </label>
          <label className="block text-sm text-muted">Nom de cet appareil
            <input className="input mt-1" value={name} maxLength={60} onChange={(e) => setName(e.target.value)} />
          </label>
          <button className="btn-primary w-full" disabled={code.length !== 6}>Demander l’accès</button>
        </form>
      )}
      {state === "waiting" && <p className="flex items-center justify-center gap-2 text-sm text-muted"><Spinner /> Validez la demande sur l’ordinateur…</p>}
      {state === "rejected" && <ErrorBox>La demande a été refusée sur l’ordinateur.</ErrorBox>}
      {state === "done" && <p className="text-sm text-ok">Téléphone autorisé.</p>}
    </div>
  );
}

export default function PairPage() {
  return <Suspense fallback={<Spinner />}><Pair /></Suspense>;
}
