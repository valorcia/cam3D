"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { ErrorBox, Logo } from "@/components/ui";
import { settings } from "@/lib/db";
import { checkKey, relayStatus, type RelayStatus } from "@/lib/relay";

export default function Settings() {
  const [key, setKey] = useState("");
  const [state, setState] = useState<"idle" | "ok" | "bad" | "checking">("idle");
  const [relay, setRelay] = useState<RelayStatus | null>(null);
  const [usage, setUsage] = useState<string>("");
  const [persisted, setPersisted] = useState<boolean | null>(null);

  useEffect(() => {
    setKey(settings.relayKey);
    relayStatus(true).then(setRelay);
    navigator.storage?.estimate?.().then((e) => setUsage(`${((e.usage ?? 0) / 1e6).toFixed(0)} Mo utilisés sur ce téléphone`)).catch(() => undefined);
    navigator.storage?.persisted?.().then(setPersisted).catch(() => undefined);
  }, []);

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setState("checking");
    const ok = await checkKey(key.trim()).catch(() => false);
    if (ok) settings.relayKey = key.trim();
    setState(ok ? "ok" : "bad");
  }

  return (
    <div className="space-y-6">
      <header className="flex items-center justify-between"><Logo /><Link href="/" className="text-sm text-muted">Terminé</Link></header>
      <h1 className="text-xl font-semibold">Réglages</h1>

      <section className="card space-y-3 p-4">
        <h2 className="font-medium">Relais chiffré</h2>
        <p className="text-sm text-muted">Le relais transporte des copies <b>chiffrées sur ce téléphone</b> de vos photos jusqu’à votre ordinateur. Ni le relais ni personne d’autre ne peut les voir : la clé de chaque scan reste sur ce téléphone et n’est transmise que dans le code de transfert. Les copies sont effacées automatiquement après 7 jours.</p>
        {relay && !relay.enabled && <ErrorBox>Relais indisponible : {relay.reason}.</ErrorBox>}
        <form onSubmit={save} className="space-y-2">
          <label className="block text-sm text-muted">Clé d’accès du relais (fournie lors de l’installation)
            <input className="input mt-1 font-mono" value={key} onChange={(e) => { setKey(e.target.value); setState("idle"); }} autoComplete="off" spellCheck={false} data-testid="relay-key" />
          </label>
          <button className="btn-primary w-full" disabled={!key.trim() || state === "checking"} data-testid="relay-key-save">Vérifier et enregistrer</button>
          {state === "ok" && <p className="text-sm text-ok" data-testid="relay-key-ok">Clé acceptée.</p>}
          {state === "bad" && <p className="text-sm text-danger">Clé refusée par le relais.</p>}
        </form>
      </section>

      <section className="card space-y-2 p-4 text-sm text-muted">
        <h2 className="font-medium text-text">Stockage sur ce téléphone</h2>
        <p>{usage}</p>
        <p>{persisted ? "Stockage protégé contre l’effacement automatique." : "Ajoutez l’application à l’écran d’accueil pour éviter que le navigateur efface les photos (Safari : Partager › Sur l’écran d’accueil)."}</p>
      </section>
    </div>
  );
}
