"use client";
import { useEffect, useRef, useState } from "react";
import { AutoSelector, DENSITIES, frameStats, GUIDANCE, headingFrom, tiltBand, type Reason } from "@/lib/autoCapture";

const ANALYSIS_W = 320;
const PERIOD_MS = 125; // ~8 analyses per second

export interface AutoMeta { heading: number | null; tilt: number | null }

/** Analyses the live camera and hands over full-resolution frames worth keeping. */
export function useAutoScan(video: React.RefObject<HTMLVideoElement | null>, running: boolean,
  density: keyof typeof DENSITIES, onFrame: (blob: Blob, meta: AutoMeta) => Promise<void>) {
  const [reason, setReason] = useState<Reason>("warmup");
  const [pulse, setPulse] = useState(0);
  const [pose, setPose] = useState<AutoMeta>({ heading: null, tilt: null });
  const poseRef = useRef<AutoMeta>({ heading: null, tilt: null });
  const selector = useRef(new AutoSelector());
  const busy = useRef(false);
  const cb = useRef(onFrame);
  cb.current = onFrame;

  useEffect(() => { selector.current.newViewDiff = DENSITIES[density].newViewDiff; }, [density]);

  useEffect(() => {
    // Listen to both: some phones only fire the relative event, others both.
    // Once the absolute (compass) one delivers values, relative events are ignored to avoid jitter.
    let hasAbsolute = false;
    const handle = (e: DeviceOrientationEvent, absolute: boolean) => {
      if (absolute && e.alpha != null) hasAbsolute = true;
      if (!absolute && hasAbsolute) return;
      const p = { heading: headingFrom(e), tilt: tiltBand(typeof e.beta === "number" ? e.beta : null) };
      if (p.heading == null && p.tilt == null) return;
      poseRef.current = p;
      setPose(p);
    };
    const onAbs = (e: Event) => handle(e as DeviceOrientationEvent, true);
    const onRel = (e: Event) => handle(e as DeviceOrientationEvent, false);
    window.addEventListener("deviceorientationabsolute", onAbs);
    window.addEventListener("deviceorientation", onRel);
    return () => { window.removeEventListener("deviceorientationabsolute", onAbs); window.removeEventListener("deviceorientation", onRel); };
  }, []);

  useEffect(() => {
    if (!running) return;
    selector.current.reset();
    const small = document.createElement("canvas");
    const sctx = small.getContext("2d", { willReadFrequently: true })!;
    let stop = false;
    const tick = async () => {
      if (stop) return;
      const v = video.current;
      if (v && v.videoWidth && !busy.current) {
        const h = Math.round((v.videoHeight * ANALYSIS_W) / v.videoWidth);
        small.width = ANALYSIS_W; small.height = h;
        sctx.drawImage(v, 0, 0, ANALYSIS_W, h);
        const r = selector.current.push(frameStats(sctx.getImageData(0, 0, ANALYSIS_W, h).data, ANALYSIS_W, h), performance.now());
        setReason(r);
        if (r === "kept") {
          busy.current = true;
          const full = document.createElement("canvas");
          full.width = v.videoWidth; full.height = v.videoHeight;
          full.getContext("2d")!.drawImage(v, 0, 0);
          const meta = { ...poseRef.current };
          full.toBlob(async (b) => {
            try { if (b) { setPulse((x) => x + 1); navigator.vibrate?.(10); await cb.current(b, meta); } } finally { busy.current = false; }
          }, "image/jpeg", 0.92);
        }
      }
      setTimeout(tick, PERIOD_MS);
    };
    tick();
    return () => { stop = true; };
  }, [running, video]);

  return { reason, pulse, pose };
}

/** Asks iOS for motion-sensor access (must be called from a user gesture). */
export async function requestOrientation(): Promise<void> {
  const D = (window as any).DeviceOrientationEvent;
  if (D && typeof D.requestPermission === "function") { try { await D.requestPermission(); } catch { /* refused: ring hidden */ } }
}

export function ScanHud({ reason, pulse, count }: { reason: Reason; pulse: number; count: number }) {
  const msg = GUIDANCE[reason];
  return (
    <>
      <div key={pulse} className="pointer-events-none absolute inset-0 rounded-2xl ring-4 ring-ok/0 animate-[flash_0.35s_ease-out]" />
      <div className="pointer-events-none absolute inset-x-0 top-3 flex flex-col items-center gap-2">
        <span className="rounded-full bg-black/60 px-3 py-1.5 text-xs font-medium backdrop-blur" data-testid="auto-count">● {count} image{count > 1 ? "s" : ""}</span>
        {msg && <span className={`rounded-full px-3 py-1.5 text-xs backdrop-blur ${reason === "stationary" ? "bg-black/55 text-text" : "bg-warn/80 text-black"}`} data-testid="auto-guidance">{msg}</span>}
      </div>
    </>
  );
}

const SECTORS = 24;
const MAX_GAP_DEG = 45; // consecutive frames closer than this = continuous walk: the sectors in between are covered

/** "band:sector" keys covered by the scan, in capture order. Exported for tests. */
export function coveredSectors(samples: AutoMeta[]): Set<string> {
  const out = new Set<string>();
  const sec = (h: number) => Math.floor((((h % 360) + 360) % 360) / (360 / SECTORS));
  let prev: AutoMeta | null = null;
  for (const s of samples) {
    if (s.heading == null) continue;
    const band = s.tilt ?? 1;
    out.add(`${band}:${sec(s.heading)}`);
    if (prev && prev.heading != null && (prev.tilt ?? 1) === band) {
      const d = ((s.heading - prev.heading + 540) % 360) - 180; // signed shortest difference
      if (Math.abs(d) <= MAX_GAP_DEG) {
        const steps = Math.ceil(Math.abs(d) / (360 / SECTORS));
        for (let i = 1; i < steps; i++) out.add(`${band}:${sec(prev.heading + (d * i) / steps)}`);
      }
    }
    prev = s;
  }
  return out;
}

/** Directions already covered, measured with the phone's compass (3 height bands). */
export function CoverageRing({ samples, heading }: { samples: AutoMeta[]; heading: number | null }) {
  const withHeading = samples.filter((s) => s.heading != null);
  if (!withHeading.length && heading == null) return null;
  const filled = coveredSectors(withHeading);
  const radii = [34, 26, 18];
  const arc = (r: number, i: number) => {
    const a0 = ((i * 360) / SECTORS - 90) * (Math.PI / 180), a1 = (((i + 1) * 360) / SECTORS - 90 - 2) * (Math.PI / 180);
    return `M ${40 + r * Math.cos(a0)} ${40 + r * Math.sin(a0)} A ${r} ${r} 0 0 1 ${40 + r * Math.cos(a1)} ${40 + r * Math.sin(a1)}`;
  };
  const covered = new Set([...filled].map((k) => k.split(":")[1])).size;
  return (
    <div className="pointer-events-none absolute bottom-24 right-3 rounded-2xl bg-black/55 p-1.5 backdrop-blur" data-testid="coverage">
      <svg viewBox="0 0 80 80" className="h-20 w-20">
        {radii.map((r, band) => Array.from({ length: SECTORS }, (_, i) => (
          <path key={`${band}-${i}`} d={arc(r, i)} fill="none" strokeWidth={6} strokeLinecap="butt"
            stroke={filled.has(`${band}:${i}`) ? "#4ade80" : "rgba(255,255,255,0.12)"} />
        )))}
        {heading != null && <line x1="40" y1="40" x2={40 + 38 * Math.cos((heading - 90) * Math.PI / 180)} y2={40 + 38 * Math.sin((heading - 90) * Math.PI / 180)} stroke="#fbbf24" strokeWidth="2" />}
      </svg>
      <p className="text-center text-[9px] text-muted">{Math.round((covered / SECTORS) * 360)}° du tour</p>
    </div>
  );
}
