"use client";
import { useEffect, useState } from "react";
import { IconPhone, IconTrash } from "@/components/Icons";
import { ErrorBox, Spinner } from "@/components/ui";
import { api, url } from "@/lib/api";
import { useApp } from "@/lib/store";

type Session = { id: string; code: string; expires_at: number; urls: string[]; secure: boolean };

export default function Settings() {
  const { system, whoami } = useApp();
  const [session, setSession] = useState<Session | null>(null);
  const [pending, setPending] = useState<{ id: string; device_name: string }[]>([]);
  const [devices, setDevices] = useState<{ id: string; name: string; last_seen: number | null; expires_at: number }[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [left, setLeft] = useState(0);

  const loadDevices = () => api.devices().then(setDevices).catch(() => undefined);
  useEffect(() => { if (whoami?.role === "desktop") loadDevices(); }, [whoami]);

  useEffect(() => {
    if (!session) return;
    const t = setInterval(async () => {
      setLeft(Math.max(0, Math.round(session.expires_at - Date.now() / 1000)));
      try { setPending(await api.pairPending()); } catch { /* ignore */ }
    }, 1500);
    return () => clearInterval(t);
  }, [session]);

  if (whoami?.role === "device") return <ErrorBox>Les paramètres se gèrent depuis l’ordinateur.</ErrorBox>;

  async function decide(id: string, ok: boolean) {
    try { ok ? await api.pairApprove(id) : await api.pairReject(id); } catch (e: any) { setError(e.message); }
    setPending((p) => p.filter((x) => x.id !== id));
    if (ok) { loadDevices(); setSession(null); }
  }

  const hw = system?.hardware;
  const t = system?.tools;
  const row = (label: string, value: React.ReactNode, ok?: boolean) => (
    <div className="flex items-start justify-between gap-4 border-b border-line py-2.5 text-sm last:border-0">
      <span className="text-muted">{label}</span>
      <span className={`text-right ${ok === false ? "text-danger" : ok ? "text-ok" : ""}`}>{value}</span>
    </div>
  );

  return (
    <div className="space-y-8">
      <h1 className="text-2xl font-semibold tracking-tight">Paramètres</h1>
      {error && <ErrorBox>{error}</ErrorBox>}

      <section className="card space-y-4 p-5">
        <div className="flex items-center gap-3">
          <span className="grid h-10 w-10 place-items-center rounded-xl bg-white/5 text-accent"><IconPhone /></span>
          <div>
            <h2 className="font-medium">Connecter un téléphone</h2>
            <p className="text-sm text-muted">Le téléphone doit être sur le même réseau Wi-Fi que cet ordinateur.</p>
          </div>
        </div>
        {!session ? (
          <button className="btn-primary" onClick={() => api.pairSession().then((s) => { setSession(s); setLeft(Math.round(s.expires_at - Date.now() / 1000)); }).catch((e) => setError(e.message))} data-testid="pair-start">
            Afficher le QR code
          </button>
        ) : (
          <div className="grid gap-6 sm:grid-cols-[220px_1fr]">
            {session.urls[0] ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img src={url(`/api/pair/qr.svg?url=${encodeURIComponent(session.urls[0])}`)} alt="QR code d’appairage" className="w-full rounded-xl bg-white p-3" />
            ) : <ErrorBox>Aucune adresse réseau local détectée.</ErrorBox>}
            <div className="space-y-3 text-sm">
              <p>Scannez le QR code avec l’appareil photo du téléphone, ou ouvrez :</p>
              {session.urls.map((u) => <code key={u} className="block break-all rounded-lg bg-black/40 px-3 py-2 text-xs">{u}</code>)}
              <p>Code : <span className="font-mono text-2xl tracking-[0.3em]" data-testid="pair-code">{session.code}</span> <span className="text-xs text-faint">(expire dans {Math.floor(left / 60)} min {String(left % 60).padStart(2, "0")})</span></p>
              {!session.secure && <p className="text-xs text-warn">Connexion HTTP : l’envoi de photos depuis la galerie fonctionne ; l’appareil photo intégré dans le navigateur nécessitera le mode HTTPS (prochaine version).</p>}
              {pending.length === 0 ? <p className="flex items-center gap-2 text-muted"><Spinner className="h-3 w-3" /> En attente d’une demande…</p> : pending.map((r) => (
                <div key={r.id} className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-accent/40 bg-accent/5 p-3" data-testid="pair-request">
                  <span><b>{r.device_name}</b> demande l’accès à vos projets.</span>
                  <span className="flex gap-2">
                    <button className="btn-ghost" onClick={() => decide(r.id, false)}>Refuser</button>
                    <button className="btn-primary" onClick={() => decide(r.id, true)}>Autoriser</button>
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}
        {devices.length > 0 && (
          <div>
            <h3 className="mb-2 text-sm font-medium">Appareils autorisés</h3>
            {devices.map((d) => (
              <div key={d.id} className="flex items-center justify-between border-b border-line py-2 text-sm last:border-0">
                <span>{d.name} <span className="text-xs text-faint">· vu {d.last_seen ? new Date(d.last_seen * 1000).toLocaleString("fr-FR") : "jamais"} · expire le {new Date(d.expires_at * 1000).toLocaleDateString("fr-FR")}</span></span>
                <button className="btn-ghost px-2.5 py-1.5" aria-label={`Révoquer ${d.name}`} onClick={() => api.revokeDevice(d.id).then(loadDevices)}><IconTrash className="h-4 w-4" /></button>
              </div>
            ))}
          </div>
        )}
      </section>

      <section className="grid gap-6 lg:grid-cols-2">
        <div className="card p-5">
          <h2 className="mb-2 font-medium">Matériel</h2>
          {!hw ? <Spinner /> : <>
            {row("Système", `${hw.os} ${hw.arch}`)}
            {row("Processeur", `${hw.cpu_model} (${hw.cpu_cores} cœurs)`)}
            {row("Mémoire", hw.ram_total_mb ? `${(hw.ram_total_mb / 1024).toFixed(1)} Go` : "inconnue")}
            {row("Disque libre", hw.disk_free_mb ? `${(hw.disk_free_mb / 1024).toFixed(1)} Go` : "inconnu")}
            {row("Carte graphique", hw.gpus.length ? hw.gpus.map((g) => g.name + (g.cuda_available ? " (CUDA)" : "")).join(", ") : "aucune détectée")}
            {hw.notes.map((n) => <p key={n} className="mt-2 text-xs text-warn">{n}</p>)}
          </>}
        </div>
        <div className="card p-5">
          <h2 className="mb-2 font-medium">Moteurs</h2>
          {!t ? <Spinner /> : <>
            {row("COLMAP (pycolmap)", t.pycolmap?.available ? `${t.pycolmap.version} · ${t.pycolmap.note}` : "absent", !!t.pycolmap?.available)}
            {row("OpenMVS", t.openmvs_available ? "installé" : "absent", t.openmvs_available)}
            {row("FFmpeg (vidéo)", t.ffmpeg?.available ? "installé" : "absent", !!t.ffmpeg?.available)}
            {row("Blender (optionnel)", t.blender?.available ? t.blender.version ?? "installé" : "absent")}
            {row("Reconstruction possible", system?.reconstruction_available ? "oui" : "non", !!system?.reconstruction_available)}
            {row("Dossier des projets", <code className="text-xs">{system?.data_dir}</code>)}
            {row("Version", system?.version)}
          </>}
        </div>
      </section>
    </div>
  );
}
