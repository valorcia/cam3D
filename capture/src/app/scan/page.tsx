"use client";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useRef, useState } from "react";
import { zipSync } from "fflate";
import { CoverageRing, requestOrientation, ScanHud, useAutoScan } from "@/components/AutoScan";
import { ErrorBox, Spinner } from "@/components/ui";
import { DENSITIES } from "@/lib/autoCapture";
import { randomHex, sha256Hex } from "@/lib/crypto";
import { db, settings, type Photo, type Scan } from "@/lib/db";
import { analyseBlob } from "@/lib/quality";
import { relayStatus, removePhotoRemote, removeScanRemote, syncScan, transferCode, type RelayStatus } from "@/lib/relay";
import { useOnline } from "@/lib/useOnline";

const TIPS = ["Tournez lentement autour de l’objet", "60 à 80 % de recouvrement entre deux photos", "Un 2e tour plus haut, puis plus bas", "Évitez le contre-jour et les reflets", "Pensez aux zones cachées"];

function stamp(n: number) {
  const d = new Date(), p = (x: number) => String(x).padStart(2, "0");
  return `IMG_${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}_${p(d.getHours())}${p(d.getMinutes())}${p(d.getSeconds())}_${n}.jpg`;
}

function ScanView() {
  const id = useSearchParams().get("id") ?? "";
  const online = useOnline();
  const video = useRef<HTMLVideoElement>(null);
  const stream = useRef<MediaStream | null>(null);
  const [scan, setScan] = useState<Scan | null>(null);
  const [photos, setPhotos] = useState<Photo[]>([]);
  const [urls, setUrls] = useState<Record<string, string>>({});
  const [camera, setCamera] = useState<"off" | "starting" | "on" | "unavailable">("off");
  const [camMsg, setCamMsg] = useState("");
  const [tip, setTip] = useState(0);
  const [toast, setToast] = useState<string | null>(null);
  const [relay, setRelay] = useState<RelayStatus | null>(null);
  const [syncing, setSyncing] = useState(false);
  const [syncError, setSyncError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const counter = useRef(0);
  const [mode, setMode] = useState<"auto" | "manual">("auto");
  const [scanning, setScanning] = useState(false);
  const [density, setDensity] = useState<keyof typeof DENSITIES>("normal");
  const [sessionCount, setSessionCount] = useState(0);

  const reload = useCallback(async () => {
    const s = await db.scan(id);
    setScan(s ?? null);
    const ps = await db.photos(id);
    setPhotos(ps);
    setUrls((cur) => {
      const next: Record<string, string> = {};
      for (const p of ps) next[p.id] = cur[p.id] ?? URL.createObjectURL(p.blob);
      for (const [k, u] of Object.entries(cur)) if (!next[k]) URL.revokeObjectURL(u);
      return next;
    });
  }, [id]);

  const reloadTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const reloadSoon = () => {
    if (reloadTimer.current) return;
    reloadTimer.current = setTimeout(() => { reloadTimer.current = null; reload(); if (navigator.onLine) sync(); }, 1200);
  };

  const sync = useCallback(async () => {
    setSyncError(null);
    setSyncing(true);
    try { await syncScan(id, reload); } catch (e: any) { setSyncError(e?.message ?? "Envoi interrompu"); }
    setSyncing(false);
    reload();
  }, [id, reload]);

  useEffect(() => { reload(); }, [reload]);
  useEffect(() => { relayStatus().then(setRelay); }, [online]);
  useEffect(() => { const t = setInterval(() => setTip((x) => (x + 1) % TIPS.length), 5000); return () => clearInterval(t); }, []);
  useEffect(() => { if (online) sync(); }, [online, sync]);
  useEffect(() => { const t = setInterval(() => { if (navigator.onLine) sync(); }, 20000); return () => clearInterval(t); }, [sync]);
  useEffect(() => () => { stream.current?.getTracks().forEach((t) => t.stop()); }, []);
  // Release the camera as soon as the app leaves the screen (iOS otherwise keeps it paused but held);
  // it is reopened when the user comes back.
  const resumeCamera = useRef(false);
  useEffect(() => {
    const onVis = (e: Event) => {
      if (e.type === "pagehide" || document.visibilityState === "hidden") {
        if (stream.current) {
          resumeCamera.current = true;
          stream.current.getTracks().forEach((t) => t.stop());
          stream.current = null;
          setScanning(false);
          setCamera("off");
        }
      } else if (resumeCamera.current) {
        resumeCamera.current = false;
        startCamera(attempt.current);
      }
    };
    document.addEventListener("visibilitychange", onVis);
    window.addEventListener("pagehide", onVis);
    return () => { document.removeEventListener("visibilitychange", onVis); window.removeEventListener("pagehide", onVis); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  useEffect(() => {
    // keep the screen awake while scanning
    let lock: any = null;
    if (scanning) (navigator as any).wakeLock?.request("screen").then((l: any) => { lock = l; }).catch(() => undefined);
    return () => { lock?.release?.(); };
  }, [scanning]);

  // Resolutions tried in order: some phones return a black stream for very high requests.
  const CAMERA_TRIES = [
    { width: { ideal: 4032 }, height: { ideal: 3024 } },
    { width: { ideal: 1920 }, height: { ideal: 1440 } },
    {},
  ];
  const attempt = useRef(0);
  const [videoInfo, setVideoInfo] = useState("");
  const [camSession, setCamSession] = useState(0); // new value at every (re)start, so the watchdog always re-arms

  async function startCamera(tryIndex = 0) {
    if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) {
      setCamera("unavailable"); setCamMsg("Caméra du navigateur indisponible : utilisez l’appareil photo du téléphone ci-dessous."); return;
    }
    stream.current?.getTracks().forEach((t) => t.stop());
    attempt.current = tryIndex;
    setVideoInfo("");
    setCamera("starting");
    setCamMsg("");
    try {
      const s = await navigator.mediaDevices.getUserMedia({ audio: false, video: { facingMode: { ideal: "environment" }, ...CAMERA_TRIES[tryIndex] } });
      stream.current = s;
      setCamera("on"); // the stream is attached to <video> by the effect below, once it is mounted
      setCamSession((n) => n + 1);
    } catch (e: any) {
      if (e?.name === "OverconstrainedError" && tryIndex + 1 < CAMERA_TRIES.length) return startCamera(tryIndex + 1);
      setCamera("unavailable");
      setCamMsg(e?.name === "NotAllowedError" ? "Accès à la caméra refusé : autorisez-le dans les réglages du navigateur (Safari : aA › Réglages du site web › Caméra)."
        : e?.name === "NotReadableError" ? "La caméra est utilisée par une autre application : fermez-la puis réessayez." : "Caméra indisponible.");
    }
  }

  // Attach the stream when the <video> element exists (it is only rendered once camera === "on"),
  // then make sure frames really arrive: a black preview is retried at a lower resolution.
  useEffect(() => {
    if (camera !== "on") return;
    const v = video.current, s = stream.current;
    if (!v || !s) return;
    if (v.srcObject !== s) v.srcObject = s;
    v.play().catch(() => undefined);
    const ok = () => { if (v.videoWidth) setVideoInfo(`${v.videoWidth}×${v.videoHeight}`); };
    v.addEventListener("loadedmetadata", ok);
    v.addEventListener("playing", ok);
    ok(); // metadata may already be there
    const watchdog = setTimeout(() => {
      if (v.videoWidth > 0 && v.readyState >= 2) { ok(); return; }
      if (attempt.current + 1 < CAMERA_TRIES.length) { startCamera(attempt.current + 1); return; }
      s.getTracks().forEach((t) => t.stop());
      setCamera("unavailable");
      setCamMsg("La caméra ne renvoie pas d’image dans ce navigateur. Utilisez « Appareil photo » ci-dessous, ou rouvrez l’application depuis Safari / Chrome (pas depuis une application de messagerie).");
    }, 4000);
    return () => { clearTimeout(watchdog); v.removeEventListener("loadedmetadata", ok); v.removeEventListener("playing", ok); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [camera, camSession]);

  async function addFile(file: Blob, name: string, extra: Partial<Photo> = {}) {
    const p: Photo = { id: randomHex(16), scanId: id, name, type: file.type || "image/jpeg", size: file.size, created: Date.now(), blob: file, uploaded: false, ...extra };
    if (extra.auto) {  // continuous scan: frames are already selected for sharpness, keep the loop light
      p.sha256 = await sha256Hex(new Uint8Array(await file.arrayBuffer()));
      await db.putPhoto(p);
      setSessionCount((n) => n + 1);
      reloadSoon();
      return;
    }
    try {
      const q = await analyseBlob(file);
      Object.assign(p, { sharpness: Math.round(q.sharpness), brightness: Math.round(q.brightness), warnings: q.warnings });
      if (q.warnings.length) { setToast(`Photo ${q.warnings.join(", ")} : reprenez-la si possible.`); setTimeout(() => setToast(null), 3000); }
    } catch { /* best effort */ }
    p.sha256 = await sha256Hex(new Uint8Array(await file.arrayBuffer()));
    await db.putPhoto(p);
    await reload();
    if (navigator.onLine) sync();
  }

  const auto = useAutoScan(video, scanning && camera === "on" && mode === "auto", density,
    (blob, meta) => addFile(blob, stamp(++counter.current), { auto: true, heading: meta.heading, tilt: meta.tilt }));

  async function toggleScan() {
    if (!scanning) { await requestOrientation(); setSessionCount(0); }
    setScanning(!scanning);
    if (scanning) { reload(); if (navigator.onLine) sync(); }
  }

  async function shoot() {
    const v = video.current, track = stream.current?.getVideoTracks()[0];
    if (!v || !track) return;
    navigator.vibrate?.(25);
    let blob: Blob | null = null;
    const IC = (window as any).ImageCapture;
    if (IC) { try { blob = await new IC(track).takePhoto(); } catch { blob = null; } }
    if (!blob) {
      const c = document.createElement("canvas");
      c.width = v.videoWidth; c.height = v.videoHeight;
      c.getContext("2d")!.drawImage(v, 0, 0);
      blob = await new Promise<Blob | null>((r) => c.toBlob(r, "image/jpeg", 0.95));
    }
    if (blob) await addFile(blob, stamp(++counter.current));
  }

  async function removePhoto(p: Photo) {
    if (p.uploaded && scan && online) await removePhotoRemote(scan, p.id).catch(() => undefined);
    await db.deletePhoto(p.id);
    await reload();
    if (navigator.onLine) sync();
  }

  async function zipBlob(): Promise<Blob> {
    const files: Record<string, Uint8Array> = {};
    for (const p of photos) files[p.name] = new Uint8Array(await p.blob.arrayBuffer());
    return new Blob([zipSync(files, { level: 0 }) as BlobPart], { type: "application/zip" });
  }

  async function downloadZip() {
    const b = await zipBlob();
    const a = document.createElement("a");
    a.href = URL.createObjectURL(b);
    a.download = `${(scan?.name ?? "scan").replace(/[^\p{L}\p{N} _-]+/gu, "_")}.zip`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 5000);
  }

  async function sharePhotos() {
    const files = photos.map((p) => new File([p.blob], p.name, { type: p.type }));
    if (navigator.canShare?.({ files })) await navigator.share({ files, title: scan?.name }).catch(() => undefined);
    else downloadZip();
  }

  if (!id) return <ErrorBox>Scan introuvable.</ErrorBox>;
  if (scan === null) return <div className="space-y-4 pt-4"><Link href="/" className="text-sm text-muted">‹ Mes scans</Link><ErrorBox>Ce scan n’existe pas sur ce téléphone.</ErrorBox></div>;

  const uploaded = photos.filter((p) => p.uploaded).length;
  const code = scan ? transferCode(scan) : null;
  const link = code && typeof location !== "undefined" ? `${location.origin}/t/#${code}` : null;
  const complete = scan && code && scan.manifestCount === photos.length && uploaded === photos.length && photos.length > 0;
  const relayReady = relay?.enabled && !!settings.relayKey;

  return (
    <div className="space-y-4" data-testid="scan">
      <header className="flex items-center justify-between gap-3">
        <Link href="/" className="text-sm text-muted">‹ Mes scans</Link>
        <span className={`chip ${online ? "bg-ok/10 text-ok" : "bg-warn/10 text-warn"}`}>{online ? "En ligne" : "Hors connexion"}</span>
      </header>
      <input className="w-full bg-transparent text-xl font-semibold tracking-tight outline-none" value={scan?.name ?? ""} aria-label="Nom du scan"
        onChange={(e) => scan && setScan({ ...scan, name: e.target.value })}
        onBlur={async () => { if (scan) { await db.putScan({ ...scan, manifestCount: -1 }); reload(); if (navigator.onLine) sync(); } }} />

      {/* viewfinder */}
      <div className="relative overflow-hidden rounded-2xl border border-line bg-black">
        <div className="relative aspect-[3/4] w-full">
          {camera === "on" && !videoInfo && <div className="absolute inset-0 grid place-items-center"><Spinner className="h-6 w-6" /></div>}
          {camera === "on" && videoInfo && <span className="pointer-events-none absolute bottom-2 right-3 text-[10px] text-white/60" data-testid="video-info">{videoInfo}</span>}
          {camera === "on" ? <video ref={video} playsInline muted autoPlay className="h-full w-full object-cover" /> : (
            <div className="absolute inset-0 grid place-items-center p-6 text-center">
              {camera === "starting" ? <Spinner className="h-6 w-6" /> : (
                <div className="space-y-3">
                  {camMsg && <p className="text-sm text-muted">{camMsg}</p>}
                  {camera === "off" && <button className="btn-primary" onClick={() => startCamera(0)} data-testid="start-camera">Ouvrir la caméra</button>}
                  {camera === "unavailable" && camMsg && <button className="btn-ghost" onClick={() => startCamera(0)}>Réessayer</button>}
                </div>
              )}
            </div>
          )}
          {camera === "on" && mode === "manual" && <span className="pointer-events-none absolute inset-x-0 top-3 mx-auto w-fit rounded-full bg-black/55 px-3 py-1.5 text-xs backdrop-blur">{TIPS[tip]}</span>}
          {camera === "on" && mode === "auto" && scanning && <ScanHud reason={auto.reason} pulse={auto.pulse} count={sessionCount} />}
          {camera === "on" && mode === "auto" && <CoverageRing samples={photos.map((p) => ({ heading: p.heading ?? null, tilt: p.tilt ?? null }))} heading={auto.pose.heading} />}
          {camera === "on" && !scanning && (
            <div className="absolute left-3 top-3 flex rounded-lg bg-black/55 p-0.5 text-xs backdrop-blur" role="group">
              {(["auto", "manual"] as const).map((m) => (
                <button key={m} disabled={scanning} onClick={() => setMode(m)} aria-pressed={mode === m} data-testid={`mode-${m}`}
                  className={`rounded-md px-2.5 py-1 ${mode === m ? "bg-white/20" : "text-muted"}`}>{m === "auto" ? "Scan continu" : "Photo"}</button>
              ))}
            </div>
          )}
          {toast && <div className="absolute inset-x-3 bottom-24 rounded-xl bg-black/80 px-3 py-2 text-center text-sm text-warn" role="status">{toast}</div>}
          {camera === "on" && mode === "auto" && (
            <button onClick={toggleScan} data-testid="scan-toggle" aria-label={scanning ? "Arrêter le scan" : "Démarrer le scan"}
              className="absolute bottom-4 left-1/2 grid h-[70px] w-[70px] -translate-x-1/2 place-items-center rounded-full border-4 border-white/90 active:scale-90">
              {scanning ? <span className="h-7 w-7 rounded-md bg-danger" /> : <span className="h-[54px] w-[54px] rounded-full bg-danger" />}
            </button>
          )}
          {camera === "on" && mode === "manual" && (
            <button onClick={shoot} aria-label="Prendre une photo" data-testid="shutter"
              className="absolute bottom-4 left-1/2 grid h-[70px] w-[70px] -translate-x-1/2 place-items-center rounded-full border-4 border-white/90 active:scale-90">
              <span className="h-[54px] w-[54px] rounded-full bg-white" />
            </button>
          )}
        </div>
      </div>
      {camera === "on" && mode === "auto" && (
        <div className="flex items-center justify-between gap-2 text-xs text-muted">
          <span>{scanning ? "Tournez lentement autour de l’objet, à 2 ou 3 hauteurs." : "Appuyez sur le bouton rouge puis tournez autour de l’objet : les images sont prises automatiquement."}</span>
          <select className="input w-auto py-1.5 text-xs" value={density} disabled={scanning} onChange={(e) => setDensity(e.target.value as keyof typeof DENSITIES)} aria-label="Densité d’images">
            {Object.entries(DENSITIES).map(([k, d]) => <option key={k} value={k}>{d.label}</option>)}
          </select>
        </div>
      )}
      <div className="grid grid-cols-2 gap-2">
        <label className="btn-ghost">Appareil photo
          <input type="file" accept="image/*" capture="environment" hidden onChange={async (e) => { for (const f of Array.from(e.target.files ?? [])) await addFile(f, f.name || stamp(++counter.current)); e.target.value = ""; }} />
        </label>
        <label className="btn-ghost">Galerie
          <input type="file" accept="image/*" multiple hidden data-testid="gallery" onChange={async (e) => { for (const f of Array.from(e.target.files ?? [])) await addFile(f, f.name); e.target.value = ""; }} />
        </label>
      </div>

      {/* strip */}
      <div>
        <p className="mb-2 text-sm" data-testid="counter">{photos.length} photo{photos.length > 1 ? "s" : ""} sur ce téléphone{scan?.relay ? ` · ${uploaded} chiffrée${uploaded > 1 ? "s" : ""} en ligne` : ""}</p>
        <div className="flex gap-2 overflow-x-auto pb-1">
          {photos.slice().reverse().map((p) => (
            <div key={p.id} className="relative h-16 w-16 shrink-0 overflow-hidden rounded-lg bg-white/5">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              {urls[p.id] && <img src={urls[p.id]} alt="" className="h-full w-full object-cover" />}
              {scan?.relay && <span className={`absolute bottom-1 left-1 h-2 w-2 rounded-full ${p.uploaded ? "bg-ok" : "bg-warn"}`} title={p.uploaded ? "Envoyée (chiffrée)" : "En attente d’envoi"} />}
              {p.warnings?.length ? <span className="absolute inset-x-0 top-0 bg-black/70 text-center text-[9px] text-warn">{p.warnings[0]}</span> : null}
              <button onClick={() => removePhoto(p)} aria-label="Supprimer cette photo" className="absolute right-0.5 top-0.5 grid h-6 w-6 place-items-center rounded-md bg-black/60 text-xs">✕</button>
            </div>
          ))}
        </div>
      </div>

      {/* transfer */}
      <section className="card space-y-3 p-4" data-testid="transfer">
        <h2 className="font-medium">Envoyer vers l’ordinateur</h2>
        <label className="flex items-start gap-3 text-sm">
          <input type="checkbox" className="mt-1" checked={!!scan?.relay} disabled={!relayReady}
            onChange={async (e) => { if (!scan) return; await db.putScan({ ...scan, relay: e.target.checked }); reload(); if (e.target.checked) sync(); }} />
          <span>Envoyer des copies chiffrées au relais
            <span className="block text-xs text-muted">{relayReady ? "Chiffrées sur ce téléphone ; effacées du relais après 7 jours." : <Link className="underline" href="/settings/">Configurer le relais</Link>}</span>
          </span>
        </label>
        {scan?.relay && relayReady && (
          <div className="space-y-2 text-sm">
            <p className="flex items-center gap-2 text-muted" data-testid="sync-status">
              {syncing && <Spinner className="h-3 w-3" />}
              {!online ? `Hors connexion : ${photos.length - uploaded} photo(s) seront envoyées au retour du réseau.` :
                complete ? "Tout est envoyé et chiffré." : syncing ? "Envoi chiffré en cours…" : `${photos.length - uploaded} photo(s) en attente.`}
            </p>
            {syncError && <ErrorBox>{syncError}</ErrorBox>}
            {code && link && (
              <div className="space-y-2 rounded-xl bg-white/5 p-3">
                <p className="text-xs text-muted">Sur votre ordinateur, ouvrez ce lien (ou collez le code dans cam3D › Depuis le téléphone). Toute personne qui a ce code peut voir ces photos : ne l’envoyez qu’à vous-même.</p>
                <textarea readOnly className="input h-20 font-mono text-[10px]" value={code} data-testid="transfer-code" onFocus={(e) => e.target.select()} />
                <div className="grid grid-cols-2 gap-2">
                  <button className="btn-primary" onClick={() => (navigator.share ? navigator.share({ title: `cam3D : ${scan?.name}`, url: link }).catch(() => undefined) : navigator.clipboard?.writeText(link))}>Partager le lien</button>
                  <button className="btn-ghost" onClick={() => navigator.clipboard?.writeText(code).then(() => { setCopied(true); setTimeout(() => setCopied(false), 1500); })}>{copied ? "Copié" : "Copier le code"}</button>
                </div>
                {!complete && <p className="text-xs text-warn">Des photos sont encore en attente : le code reste valable, réimportez plus tard pour les récupérer.</p>}
              </div>
            )}
          </div>
        )}
        <div className="grid grid-cols-2 gap-2 border-t border-line pt-3">
          <button className="btn-ghost" disabled={!photos.length} onClick={sharePhotos}>Partager les photos</button>
          <button className="btn-ghost" disabled={!photos.length} onClick={downloadZip} data-testid="zip">Télécharger un ZIP</button>
        </div>
        <p className="text-xs text-faint">Sans relais : partagez les photos (AirDrop, Quick Share…) ou le ZIP vers l’ordinateur, puis importez-les dans cam3D.</p>
        {scan?.manifestUrl && online && (
          <button className="text-xs text-muted underline" onClick={async () => { if (scan) { await removeScanRemote(scan); reload(); } }}>Retirer ce scan du relais maintenant</button>
        )}
      </section>
      <button className="w-full text-center text-xs text-danger underline" onClick={async () => {
        if (!scan || !confirm("Supprimer ce scan et ses photos de ce téléphone ?")) return;
        if (scan.manifestUrl && online) await removeScanRemote(scan).catch(() => undefined);
        await db.deleteScan(scan.id); location.href = "/";
      }}>Supprimer ce scan du téléphone</button>
    </div>
  );
}

export default function ScanPage() {
  return <Suspense fallback={<Spinner />}><ScanView /></Suspense>;
}
