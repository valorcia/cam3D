"use client";
import { useEffect, useRef, useState } from "react";
import { GuideRenderer, type GuideStats } from "@/lib/guideRender";
import { CoverageMap, coverCrop, fieldOfView } from "@/lib/scanGuide";

const CELL_CSS_PX = 12;     // target triangle size on screen
const FEATURE_PERIOD = 150; // ms between two analyses of the image
const TICK = 40;            // ms between two checks of pose / coverage changes

export interface GuidePose { heading: number | null; pitch?: number | null }

/**
 * Overlay drawn on the live video: a fine mesh of the points detected in the visible part of the image,
 * tinted blue where the viewing direction is not covered yet by a kept frame.
 * A visual guide, not a depth measurement. Detection and drawing run in a Web Worker when the browser
 * supports OffscreenCanvas, so that the scan's frame selection keeps the main thread.
 */
export function ScanGuide({ video, pose, map, lastKept, scanning }: {
  video: React.RefObject<HTMLVideoElement | null>;
  pose: React.RefObject<GuidePose>;
  map: React.RefObject<CoverageMap>;
  lastKept: React.RefObject<number>;
  scanning: boolean;
}) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const [hint, setHint] = useState<GuideStats["hint"]>(0);
  const [mode, setMode] = useState<"worker" | "main">(() =>
    typeof window !== "undefined" && typeof Worker !== "undefined" && "transferControlToOffscreen" in HTMLCanvasElement.prototype ? "worker" : "main");

  useEffect(() => {
    const c = canvas.current;
    if (!c) return;
    let worker: Worker | null = null;
    let renderer: GuideRenderer | null = null;
    let ctx: CanvasRenderingContext2D | null = null;
    let stopped = false;
    const size = { W: 0, H: 0, cssW: 0, cssH: 0, scale: 1 };

    const onStats = (s: GuideStats) => {
      c.dataset.coverage = String(Math.round(s.coverage * 100));
      c.dataset.points = String(s.points);
      c.dataset.triangles = String(s.triangles);
      c.dataset.cell = String(Math.round(s.cell));
      c.dataset.renderer = mode;
      setHint((h) => (h === s.hint ? h : s.hint));
    };

    if (mode === "worker") {
      try {
        const off = c.transferControlToOffscreen();
        worker = new Worker(new URL("../workers/guide.worker.ts", import.meta.url), { type: "module" });
        worker.onmessage = (e) => { if (e.data?.type === "stats") onStats(e.data.stats); };
        worker.onerror = () => { if (!stopped) setMode("main"); }; // e.g. script not cached while offline
        worker.postMessage({ type: "init", canvas: off }, [off]);
      } catch {
        setMode("main");
        return;
      }
    } else {
      renderer = new GuideRenderer();
      ctx = c.getContext("2d");
    }
    const send = (msg: Record<string, unknown>, transfer: Transferable[] = []) => {
      const m = { ...msg, now: performance.now() };
      if (worker) worker.postMessage(m, transfer);
    };

    // canvas size in device pixels (capped at 2x)
    const resize = () => {
      const scale = Math.min(2, window.devicePixelRatio || 1);
      Object.assign(size, { W: Math.round(c.clientWidth * scale), H: Math.round(c.clientHeight * scale), cssW: c.clientWidth, cssH: c.clientHeight, scale });
      if (worker) send({ type: "size", ...size });
      else if (c.width !== size.W || c.height !== size.H) { c.width = size.W; c.height = size.H; }
    };
    resize();
    const ro = new ResizeObserver(resize);
    ro.observe(c);

    // analysis image: only the part of the video that is on screen (it is cropped to fill the screen)
    const small = document.createElement("canvas");
    const sctx = small.getContext("2d", { willReadFrequently: true })!;
    const frameTimer = setInterval(() => {
      const v = video.current;
      if (!v || !v.videoWidth || !c.clientWidth) return;
      const crop = coverCrop(v.videoWidth, v.videoHeight, c.clientWidth, c.clientHeight);
      // half the CSS resolution: a cell of CELL_CSS_PX/2 analysis pixels = CELL_CSS_PX on screen
      const w = Math.max(64, Math.round(c.clientWidth / 2)), h = Math.max(64, Math.round(c.clientHeight / 2));
      small.width = w; small.height = h;
      sctx.drawImage(v, crop.x * v.videoWidth, crop.y * v.videoHeight, crop.w * v.videoWidth, crop.h * v.videoHeight, 0, 0, w, h);
      const rgba = sctx.getImageData(0, 0, w, h).data;
      const cell = Math.max(4, Math.round(CELL_CSS_PX / 2));
      if (worker) send({ type: "frame", rgba, w, h, crop, cell }, [rgba.buffer]);
      else renderer!.setFrame(rgba, w, h, crop, cell);
    }, FEATURE_PERIOD);

    // pose, coverage and kept-frame changes
    let sentPose = "", sentMap: CoverageMap | null = null, sentVersion = -1, sentKept = -Infinity;
    const tick = setInterval(() => {
      const v = video.current;
      const fov = v?.videoWidth ? fieldOfView(v.videoWidth, v.videoHeight) : fieldOfView(3, 4);
      const p = pose.current;
      const heading = p?.heading ?? null, pitch = p?.pitch ?? null;
      const key = `${heading == null ? "-" : Math.round(heading * 2)}:${pitch == null ? "-" : Math.round(pitch * 2)}:${fov.h}`;
      if (key !== sentPose) {
        sentPose = key;
        if (worker) send({ type: "pose", heading, pitch, fov });
        else Object.assign(renderer!, { heading, pitch, fov });
      }
      const m = map.current;
      if (m && (m !== sentMap || m.version !== sentVersion)) {
        sentMap = m; sentVersion = m.version;
        if (worker) send({ type: "coverage", counts: m.counts.slice() });
        else renderer!.setCoverage(m.counts);
      }
      const k = lastKept.current ?? -Infinity;
      if (k !== sentKept) {
        sentKept = k;
        if (worker) send({ type: "kept", at: k });
        else renderer!.lastKept = k;
      }
      if (renderer && ctx) {
        const s = renderer.render(ctx, size.W, size.H, size.cssW, size.cssH, size.scale, performance.now());
        if (s) onStats(s);
      }
    }, TICK);

    return () => {
      stopped = true;
      clearInterval(frameTimer); clearInterval(tick); ro.disconnect();
      worker?.terminate();
    };
  }, [mode, video, pose, map, lastKept]);

  return (
    <>
      {/* a new element when falling back: a canvas handed to a worker cannot be drawn on again */}
      <canvas key={mode} ref={canvas} className="pointer-events-none absolute inset-0 h-full w-full" data-testid="scan-guide" />
      {scanning && hint !== 0 && (
        <div className={`pointer-events-none absolute top-1/2 -translate-y-1/2 ${hint === -1 ? "left-2" : hint === 1 ? "right-2" : "inset-x-0 mx-auto w-fit"}`} data-testid="guide-hint">
          <span className="block rounded-full bg-black/60 px-3 py-2 text-sm font-medium text-white backdrop-blur">
            {hint === -1 ? "‹ Continuez par ici" : hint === 1 ? "Continuez par ici ›" : "Tour complet à cette hauteur : changez de hauteur"}
          </span>
        </div>
      )}
      <span className="pointer-events-none absolute bottom-[98px] left-3 rounded-full bg-black/45 px-2 py-0.5 text-[10px] text-white/70">
        Guide visuel · estimation, pas de LiDAR
      </span>
    </>
  );
}
