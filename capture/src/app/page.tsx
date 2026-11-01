"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { Logo } from "@/components/ui";
import { b64url, newKey, randomHex } from "@/lib/crypto";
import { db, settings, type Scan } from "@/lib/db";
import { relayStatus, type RelayStatus } from "@/lib/relay";
import { useOnline } from "@/lib/useOnline";

interface Row { scan: Scan; count: number; uploaded: number; thumb: string | null }

export default function Home() {
  const router = useRouter();
  const online = useOnline();
  const [rows, setRows] = useState<Row[] | null>(null);
  const [relay, setRelay] = useState<RelayStatus | null>(null);
  const [hasKey, setHasKey] = useState(false);

  useEffect(() => {
    let urls: string[] = [];
    (async () => {
      const scans = await db.scans();
      const out: Row[] = [];
      for (const s of scans) {
        const photos = await db.photos(s.id);
        const thumb = photos[0] ? URL.createObjectURL(photos[0].blob) : null;
        if (thumb) urls.push(thumb);
        out.push({ scan: s, count: photos.length, uploaded: photos.filter((p) => p.uploaded).length, thumb });
      }
      setRows(out);
    })();
    setHasKey(!!settings.relayKey);
    relayStatus().then(setRelay);
    return () => urls.forEach(URL.revokeObjectURL);
  }, []);

  async function newScan() {
    const id = randomHex(16);
    const name = `Scan du ${new Date().toLocaleDateString("fr-FR", { day: "numeric", month: "long" })} ${new Date().toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" })}`;
    await db.putScan({ id, name, created: Date.now(), key: b64url(newKey()), relay: true });
    router.push(`/scan/?id=${id}`);
  }

  return (
    <div className="space-y-6">
      <header className="flex items-center justify-between">
        <Logo />
        <Link href="/settings/" className="text-sm text-muted hover:text-text">Réglages</Link>
      </header>

      <section className="space-y-2">
        <h1 className="text-2xl font-semibold tracking-tight">Capturez, où que vous soyez.</h1>
        <p className="text-sm text-muted">Les photos sont gardées sur ce téléphone et, si le relais est activé, envoyées chiffrées. Vous les récupérerez ensuite dans cam3D sur votre ordinateur pour la reconstruction 3D.</p>
      </section>

      <div className="flex flex-wrap gap-2 text-xs">
        <span className={`chip ${online ? "bg-ok/10 text-ok" : "bg-warn/10 text-warn"}`} data-testid="online">{online ? "En ligne" : "Hors connexion : capture possible"}</span>
        {relay && (relay.enabled && hasKey
          ? <span className="chip bg-ok/10 text-ok">Relais chiffré actif</span>
          : <Link href="/settings/" className="chip bg-white/10 text-muted">Relais {relay.enabled ? "à configurer" : "indisponible"} ›</Link>)}
      </div>

      <button className="btn-primary w-full py-4 text-base" onClick={newScan} data-testid="new-scan">Nouveau scan</button>

      <section className="space-y-3">
        <h2 className="text-sm font-medium text-muted">Mes scans</h2>
        {rows === null ? null : rows.length === 0 ? (
          <p className="rounded-xl bg-white/5 p-4 text-sm text-muted">Aucun scan pour l’instant.</p>
        ) : rows.map(({ scan, count, uploaded, thumb }) => (
          <Link key={scan.id} href={`/scan/?id=${scan.id}`} className="card flex items-center gap-3 p-3" data-testid="scan-row">
            <span className="h-14 w-14 shrink-0 overflow-hidden rounded-lg bg-white/5">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              {thumb && <img src={thumb} alt="" className="h-full w-full object-cover" />}
            </span>
            <span className="min-w-0 flex-1">
              <span className="block truncate font-medium">{scan.name}</span>
              <span className="block text-xs text-muted">{count} photo{count > 1 ? "s" : ""}{scan.relay && count ? ` · ${uploaded}/${count} chiffrées en ligne` : ""}</span>
            </span>
          </Link>
        ))}
      </section>
    </div>
  );
}
