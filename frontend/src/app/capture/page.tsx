"use client";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useRef, useState } from "react";
import { IconBack, IconImages, IconTrash } from "@/components/Icons";
import { CoverageRing, requestOrientation, ScanHud, useAutoScan, type AutoMeta } from "@/components/AutoScan";
import { ErrorBox, Spinner } from "@/components/ui";
import { DENSITIES } from "@/lib/autoCapture";
import { api, uploadPhotos, uploadVideo } from "@/lib/api";
import { analyseBlob, type Quality } from "@/lib/quality";
import { useApp } from "@/lib/store";

type Status = "pending" | "uploading" | "done" | "error";
interface Shot { key: string; file: File; preview: string; status: Status; serverName?: string; error?: string; quality?: Quality }

const TIPS = [
  "Tournez lentement autour de l’objet",
  "Gardez 60 à 80 % de recouvrement entre deux photos",
  "Faites un 2e tour plus haut, puis plus bas",
  "Évitez les mouvements brusques et le contre-jour",
  "Pensez aux zones cachées",
];
const RECOMMENDED = 40;

function stamp() {
  const d = new Date();
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}_${p(d.getHours())}${p(d.getMinutes())}${p(d.getSeconds())}`;
}

function Capture() {
  const id = useSearchParams().get("id") ?? "";
  const { whoami, system } = useApp();
  const video = useRef<HTMLVideoElement>(null);
  const stream = useRef<MediaStream | null>(null);
  const [mode, setMode] = useState<"starting" | "camera" | "fallback">("starting");
  const [camError, setCamError] = useState<string | null>(null);
  const [res, setRes] = useState<string>("");
  const [shots, setShots] = useState<Shot[]>([]);
  const [flash, setFlash] = useState(false);
  const [tip, setTip] = useState(0);
  const [toast, setToast] = useState<string | null>(null);
  const [projectName, setProjectName] = useState("");
  const [videoJob, setVideoJob] = useState<string | null>(null);
  const counter = useRef(0);
  const queue = useRef<Promise<void>>(Promise.resolve());
  const [shotMode, setShotMode] = useState<"auto" | "manual">("auto");
  const [scanning, setScanning] = useState(false);
  const [density, setDensity] = useState<keyof typeof DENSITIES>("normal");
  const [poses, setPoses] = useState<AutoMeta[]>([]);

  useEffect(() => { if (whoami && id) api.project(id).then((p) => setProjectName(p.name)).catch(() => undefined); }, [whoami, id]);
  useEffect(() => { const t = setInterval(() => setTip((x) => (x + 1) % TIPS.length), 5000); return () => clearInterval(t); }, []);

  // camera (secure context only: HTTPS or localhost)
  useEffect(() => {
    let wake: any = null;
    async function start() {
      if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) {
        setCamError("La caméra du navigateur nécessite la connexion sécurisée (HTTPS).");
        setMode("fallback");
        return;
      }
      try {
        const s = await navigator.mediaDevices.getUserMedia({
          audio: false,
          video: { facingMode: { ideal: "environment" }, width: { ideal: 4032 }, height: { ideal: 3024 } },
        });
        stream.current = s;
        if (video.current) { video.current.srcObject = s; await video.current.play().catch(() => undefined); }
        const st = s.getVideoTracks()[0]?.getSettings();
        if (st?.width) setRes(`${st.width}×${st.height}`);
        setMode("camera");
        try { wake = await (navigator as any).wakeLock?.request("screen"); } catch { /* optional */ }
      } catch (e: any) {
        setCamError(e?.name === "NotAllowedError" ? "Accès à la caméra refusé. Autorisez-le dans les réglages du navigateur."
          : "Caméra indisponible sur cet appareil.");
        setMode("fallback");
      }
    }
    start();
    return () => { stream.current?.getTracks().forEach((t) => t.stop()); wake?.release?.(); };
  }, []);

  const upload = useCallback((shot: Shot) => {
    queue.current = queue.current.then(async () => {
      setShots((all) => all.map((s) => (s.key === shot.key ? { ...s, status: "uploading" } : s)));
      try {
        const r = await uploadPhotos(id, [shot.file]);
        const added = r.added?.[0];
        if (!added) throw new Error(r.rejected?.[0]?.error ?? "Refusée par le serveur");
        setShots((all) => all.map((s) => (s.key === shot.key ? { ...s, status: "done", serverName: added.name } : s)));
      } catch (e: any) {
        setShots((all) => all.map((s) => (s.key === shot.key ? { ...s, status: "error", error: e.message } : s)));
      }
    });
  }, [id]);

  const auto = useAutoScan(video, scanning && mode === "camera" && shotMode === "auto", density, async (blob, meta) => {
    setPoses((p) => [...p, meta]);
    const key = `${Date.now()}_${counter.current++}`;
    const file = new File([blob], `scan_${stamp()}_${counter.current}.jpg`, { type: "image/jpeg" });
    const shot: Shot = { key, file, preview: URL.createObjectURL(file), status: "pending" };
    setShots((all) => [...all, shot]);
    upload(shot); // frames are already selected for sharpness: no second analysis
  });

  async function toggleScan() {
    if (!scanning) await requestOrientation();
    setScanning(!scanning);
  }

  useEffect(() => {
    let lock: any = null;
    if (scanning) (navigator as any).wakeLock?.request("screen").then((l: any) => { lock = l; }).catch(() => undefined);
    return () => { lock?.release?.(); };
  }, [scanning]);

  async function addFile(file: File) {
    const key = `${Date.now()}_${counter.current++}`;
    const shot: Shot = { key, file, preview: URL.createObjectURL(file), status: "pending" };
    setShots((all) => [...all, shot]);
    upload(shot);
    try {
      const q = await analyseBlob(file);
      setShots((all) => all.map((s) => (s.key === key ? { ...s, quality: q } : s)));
      if (q.warnings.length) { setToast(`Photo ${q.warnings.join(", ")} : reprenez-la si possible.`); setTimeout(() => setToast(null), 3000); }
    } catch { /* analysis is best-effort */ }
  }

  async function shoot() {
    const v = video.current;
    const track = stream.current?.getVideoTracks()[0];
    if (!v || !track) return;
    setFlash(true); setTimeout(() => setFlash(false), 120);
    navigator.vibrate?.(25);
    let blob: Blob | null = null;
    const IC = (window as any).ImageCapture;
    if (IC) {
      try { blob = await new IC(track).takePhoto(); } catch { blob = null; } // full sensor resolution when supported
    }
    if (!blob) {
      const c = document.createElement("canvas");
      c.width = v.videoWidth; c.height = v.videoHeight;
      c.getContext("2d")!.drawImage(v, 0, 0);
      blob = await new Promise<Blob | null>((r) => c.toBlob(r, "image/jpeg", 0.95));
    }
    if (blob) addFile(new File([blob], `capture_${stamp()}_${counter.current}.jpg`, { type: "image/jpeg" }));
  }

  async function remove(s: Shot) {
    if (s.status === "uploading" || s.status === "pending") return;
    if (s.serverName) { try { await api.deletePhoto(id, s.serverName); } catch { /* already gone */ } }
    URL.revokeObjectURL(s.preview);
    setShots((all) => all.filter((x) => x.key !== s.key));
  }

  async function sendVideo(file: File | undefined) {
    if (!file) return;
    try { const j = await uploadVideo(id, file); setVideoJob(j.id); setToast("Vidéo envoyée : extraction des images sur l’ordinateur…"); }
    catch (e: any) { setToast(e.message); }
    setTimeout(() => setToast(null), 4000);
  }

  const done = shots.filter((s) => s.status === "done").length;
  const failed = shots.filter((s) => s.status === "error");
  const pending = shots.length - done - failed.length;

  if (!id) return <ErrorBox>Projet non indiqué.</ErrorBox>;

  return (
    <div className="fixed inset-0 z-40 flex flex-col bg-black text-text" data-testid="capture">
      {/* top bar */}
      <div className="flex items-center justify-between gap-3 px-4 pb-2" style={{ paddingTop: "max(12px, env(safe-area-inset-top))" }}>
        <Link href={`/project/?id=${id}&tab=photos`} className="flex items-center gap-1 text-sm text-muted"><IconBack className="h-4 w-4" /> Terminer</Link>
        <div className="truncate text-center text-sm">
          <div className="truncate font-medium">{projectName}</div>
          <div className="text-xs text-muted" data-testid="capture-counter">
            {shots.length} photo{shots.length > 1 ? "s" : ""} · {done} envoyée{done > 1 ? "s" : ""}{pending ? ` · ${pending} en cours` : ""}
          </div>
        </div>
        <span className="w-16 text-right text-[10px] text-faint">{res}</span>
      </div>

      {/* viewfinder or fallback */}
      <div className="relative flex-1 overflow-hidden">
        <video ref={video} playsInline muted autoPlay className={`h-full w-full object-cover ${mode === "camera" ? "" : "hidden"}`} />
        {mode === "starting" && <div className="absolute inset-0 grid place-items-center"><Spinner className="h-6 w-6" /></div>}
        {mode === "fallback" && (
          <div className="absolute inset-0 overflow-y-auto p-5">
            <div className="mx-auto max-w-sm space-y-4 pt-4">
              {camError && <p className="rounded-xl bg-white/5 p-3 text-sm text-muted">{camError} Vous pouvez utiliser l’appareil photo du téléphone :</p>}
              <label className="btn-primary w-full">
                Ouvrir l’appareil photo
                <input type="file" accept="image/*" capture="environment" hidden data-testid="native-camera"
                  onChange={(e) => { Array.from(e.target.files ?? []).forEach(addFile); e.target.value = ""; }} />
              </label>
              <label className="btn-ghost w-full">
                <IconImages className="h-4 w-4" /> Choisir dans la galerie
                <input type="file" accept="image/*" multiple hidden data-testid="gallery-input"
                  onChange={(e) => { Array.from(e.target.files ?? []).forEach(addFile); e.target.value = ""; }} />
              </label>
              {system?.video_import_available && (
                <label className="btn-ghost w-full">
                  Filmer ou importer une vidéo
                  <input type="file" accept="video/*" capture="environment" hidden onChange={(e) => { sendVideo(e.target.files?.[0]); e.target.value = ""; }} />
                </label>
              )}
              <p className="text-xs text-faint">Pour photographier directement dans cette page, installez le certificat local de cam3D (Paramètres de l’ordinateur › Connecter un téléphone) puis ouvrez l’adresse en https.</p>
            </div>
          </div>
        )}
        {flash && <div className="pointer-events-none absolute inset-0 bg-white/70" />}
        {mode === "camera" && shotMode === "manual" && (
          <div className="pointer-events-none absolute inset-x-0 top-3 flex justify-center">
            <span className="rounded-full bg-black/55 px-3 py-1.5 text-xs text-text backdrop-blur" key={tip}>{TIPS[tip]}</span>
          </div>
        )}
        {mode === "camera" && shotMode === "auto" && scanning && <ScanHud reason={auto.reason} pulse={auto.pulse} count={poses.length} />}
        {mode === "camera" && shotMode === "auto" && <CoverageRing samples={poses} heading={auto.pose.heading} />}
        {mode === "camera" && !scanning && (
          <div className="absolute left-3 top-3 flex rounded-lg bg-black/55 p-0.5 text-xs backdrop-blur" role="group">
            {(["auto", "manual"] as const).map((m) => (
              <button key={m} onClick={() => setShotMode(m)} aria-pressed={shotMode === m} data-testid={`mode-${m}`}
                className={`rounded-md px-2.5 py-1 ${shotMode === m ? "bg-white/20" : "text-muted"}`}>{m === "auto" ? "Scan continu" : "Photo"}</button>
            ))}
          </div>
        )}
        {mode === "camera" && shotMode === "auto" && !scanning && (
          <div className="absolute inset-x-3 bottom-3 flex items-center justify-between gap-2 rounded-xl bg-black/55 px-3 py-2 text-xs text-text backdrop-blur">
            <span>Appuyez sur le bouton rouge puis tournez lentement autour de l’objet : les images sont prises automatiquement.</span>
            <select className="rounded-md bg-white/10 px-2 py-1" value={density} onChange={(e) => setDensity(e.target.value as keyof typeof DENSITIES)} aria-label="Densité d’images">
              {Object.entries(DENSITIES).map(([k, d]) => <option key={k} value={k} className="text-black">{d.label}</option>)}
            </select>
          </div>
        )}
        {toast && <div className="absolute inset-x-4 top-14 rounded-xl bg-black/80 px-4 py-2.5 text-center text-sm text-warn backdrop-blur" role="status">{toast}</div>}
        {videoJob && <VideoJobBanner jobId={videoJob} onDone={() => setVideoJob(null)} />}
      </div>

      {/* recommended count: a simple photo counter, not a 3D coverage estimate */}
      <div className="px-4 pt-2">
        <div className="h-1 overflow-hidden rounded-full bg-white/10"><div className="h-full bg-accent transition-[width]" style={{ width: `${Math.min(100, (shots.length / RECOMMENDED) * 100)}%` }} /></div>
        <p className="mt-1 text-center text-[10px] text-faint">Nombre de photos · {RECOMMENDED} conseillées pour un objet</p>
      </div>

      {/* strip */}
      <div className="flex h-20 items-center gap-2 overflow-x-auto px-4" data-testid="capture-strip">
        {shots.slice().reverse().map((s) => (
          <div key={s.key} className="relative h-16 w-16 shrink-0 overflow-hidden rounded-lg bg-white/5">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={s.preview} alt="" className="h-full w-full object-cover" />
            <span className={`absolute bottom-1 left-1 h-2 w-2 rounded-full ${s.status === "done" ? "bg-ok" : s.status === "error" ? "bg-danger" : "bg-warn animate-pulse"}`} />
            {s.quality?.warnings.length ? <span className="absolute inset-x-0 top-0 bg-black/70 text-center text-[9px] text-warn">{s.quality.warnings[0]}</span> : null}
            {(s.status === "done" || s.status === "error") && (
              <button onClick={() => remove(s)} aria-label="Supprimer cette photo" className="absolute right-0.5 top-0.5 grid h-6 w-6 place-items-center rounded-md bg-black/60"><IconTrash className="h-3.5 w-3.5" /></button>
            )}
          </div>
        ))}
        {failed.length > 0 && (
          <button className="btn-danger shrink-0 px-3 py-1.5 text-xs" onClick={() => failed.forEach(upload)}>Renvoyer {failed.length}</button>
        )}
      </div>

      {/* shutter */}
      <div className="flex items-center justify-center pb-4 pt-1" style={{ paddingBottom: "max(16px, env(safe-area-inset-bottom))" }}>
        {mode === "camera" && shotMode === "auto" ? (
          <button onClick={toggleScan} data-testid="scan-toggle" aria-label={scanning ? "Arrêter le scan" : "Démarrer le scan"}
            className="grid h-[74px] w-[74px] place-items-center rounded-full border-4 border-white/90 transition-transform active:scale-90">
            {scanning ? <span className="h-7 w-7 rounded-md bg-danger" /> : <span className="h-[58px] w-[58px] rounded-full bg-danger" />}
          </button>
        ) : mode === "camera" ? (
          <button onClick={shoot} aria-label="Prendre une photo" data-testid="shutter"
            className="grid h-[74px] w-[74px] place-items-center rounded-full border-4 border-white/90 transition-transform active:scale-90">
            <span className="h-[58px] w-[58px] rounded-full bg-white" />
          </button>
        ) : <div className="h-[74px]" />}
      </div>
    </div>
  );
}

function VideoJobBanner({ jobId, onDone }: { jobId: string; onDone: () => void }) {
  const events = useApp((s) => s.jobEvents[jobId]);
  const revision = useApp((s) => s.revision);
  const [msg, setMsg] = useState("Extraction des images…");
  useEffect(() => {
    api.job(jobId).then((j) => {
      if (j.status === "succeeded") { setMsg(`${(j.stages as any)?.video?.frames_added ?? 0} images ajoutées depuis la vidéo`); setTimeout(onDone, 4000); }
      else if (j.status === "failed") { setMsg(j.error ?? "Échec de l’extraction"); setTimeout(onDone, 6000); }
    }).catch(() => undefined);
  }, [jobId, revision, onDone]);
  const last = events?.[events.length - 1];
  return (
    <div className="absolute inset-x-4 bottom-4 rounded-xl bg-black/80 px-4 py-3 text-sm backdrop-blur">
      <p>{msg}</p>
      {last?.progress != null && <div className="mt-2 h-1 overflow-hidden rounded-full bg-white/10"><div className="h-full bg-accent" style={{ width: `${last.progress * 100}%` }} /></div>}
    </div>
  );
}

export default function CapturePage() {
  return <Suspense fallback={<Spinner />}><Capture /></Suspense>;
}
