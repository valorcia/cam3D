"use client";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { IconCube } from "@/components/Icons";
import { Spinner } from "@/components/ui";
import { api } from "@/lib/api";

type Os = "ios" | "android" | "other";

function detectOs(): Os {
  const ua = navigator.userAgent;
  if (/iPhone|iPad|iPod/.test(ua) || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1)) return "ios";
  if (/Android/.test(ua)) return "android";
  return "other";
}

const STEPS: Record<Os, string[]> = {
  ios: [
    "Touchez « Télécharger le certificat » puis « Autoriser ».",
    "Ouvrez Réglages › Général › VPN et gestion de l’appareil › cam3D local CA › Installer.",
    "Ouvrez Réglages › Général › Informations › Réglages des certificats, et activez « cam3D local CA ».",
    "Revenez ici et touchez « Continuer en connexion sécurisée ».",
  ],
  android: [
    "Touchez « Télécharger le certificat ».",
    "Ouvrez Paramètres › Sécurité › Plus de paramètres › Chiffrement et identifiants › Installer un certificat › Certificat CA, puis choisissez cam3d-ca.crt.",
    "Revenez ici et touchez « Continuer en connexion sécurisée ».",
  ],
  other: ["Téléchargez le certificat et ajoutez-le aux autorités de confiance de cet appareil, puis continuez en connexion sécurisée."],
};

function Setup() {
  const params = useSearchParams();
  const code = params.get("code") ?? "";
  const next = params.get("next") ?? "";
  const [tls, setTls] = useState<Awaited<ReturnType<typeof api.tls>> | null>(null);
  const [os, setOs] = useState<Os>("other");
  useEffect(() => { setOs(detectOs()); api.tls().then(setTls).catch(() => setTls({ enabled: false, https_port: null, http_port: null, ca: null })); }, []);

  const q = `?code=${encodeURIComponent(code)}${next ? `&next=${encodeURIComponent(next)}` : ""}`;
  const httpsUrl = tls?.enabled && typeof window !== "undefined" ? `https://${window.location.hostname}:${tls.https_port}/pair/${q}` : null;

  if (!tls) return <div className="grid place-items-center pt-20"><Spinner /></div>;
  return (
    <div className="mx-auto max-w-md space-y-6 pt-2">
      <div className="text-center">
        <span className="mx-auto grid h-14 w-14 place-items-center rounded-2xl bg-accent-strong/20 text-accent"><IconCube className="h-7 w-7" /></span>
        <h1 className="mt-3 text-2xl font-semibold tracking-tight">Connecter ce téléphone</h1>
        <p className="mt-1 text-sm text-muted">Les photos restent sur votre réseau local et sont transférées directement vers votre ordinateur.</p>
      </div>
      {tls.enabled && httpsUrl ? (
        <section className="card space-y-3 p-5">
          <h2 className="font-medium">Recommandé : appareil photo intégré</h2>
          <p className="text-sm text-muted">Pour utiliser la caméra dans cette page, le téléphone doit faire confiance au certificat de votre ordinateur (à faire une seule fois).</p>
          <ol className="list-decimal space-y-1.5 pl-5 text-sm">{STEPS[os].map((s) => <li key={s}>{s}</li>)}</ol>
          <a className="btn-ghost w-full" href="/api/tls/ca.crt" data-testid="download-ca">Télécharger le certificat</a>
          <a className="btn-primary w-full" href={httpsUrl} data-testid="continue-https">Continuer en connexion sécurisée</a>
          {tls.ca && <p className="break-all text-[10px] text-faint">Empreinte SHA-256 (à comparer avec celle affichée sur l’ordinateur) : {tls.ca.fingerprint_sha256}</p>}
          <p className="text-[11px] text-faint">Ce certificat ne peut garantir que des adresses de réseau local : il ne permet pas d’intercepter vos autres connexions.</p>
        </section>
      ) : (
        <p className="rounded-xl bg-white/5 p-3 text-sm text-muted">La connexion sécurisée n’est pas activée sur l’ordinateur : vous pourrez utiliser l’appareil photo du téléphone et la galerie.</p>
      )}
      <section className="card space-y-3 p-5">
        <h2 className="font-medium">Sans certificat</h2>
        <p className="text-sm text-muted">Fonctionne tout de suite : l’appareil photo natif du téléphone (pleine résolution) et la galerie.</p>
        <a className="btn-ghost w-full" href={`/pair/${q}`} data-testid="continue-http">Continuer sans certificat</a>
      </section>
    </div>
  );
}

export default function SetupPage() {
  return <Suspense fallback={<Spinner />}><Setup /></Suspense>;
}
