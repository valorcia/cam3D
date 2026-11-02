"use client";
import { useEffect, useRef, useState } from "react";
import { grayFromRGBA } from "@/lib/quality";
import { CoverageMap, detectFeatures, fieldOfView, guideMesh, type Feature } from "@/lib/scanGuide";

const FEATURE_W = 192;     // analysis width for the points
const FEATURE_PERIOD = 150; // ms
const DRAW_PERIOD = 40;     // ms
const UNCOVERED = "rgba(37, 78, 235, 0.45)";
const ONCE = "rgba(37, 78, 235, 0.14)";

export interface GuidePose { heading: number | null; pitch?: number | null }

/**
 * Overlay drawn on the live video: a mesh of the points detected in the image, tinted blue where the
 * viewing direction is not covered yet by a kept frame. A visual guide, not a depth measurement.
 */
export function ScanGuide({ video, pose, map, lastKept, scanning }: {
  video: React.RefObject<HTMLVideoElement | null>;
  pose: React.RefObject<GuidePose>;
  map: React.RefObject<CoverageMap>;
  lastKept: React.RefObject<number>;
  scanning: boolean;
}) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const mesh = useRef<{ points: Feature[]; triangles: Uint32Array } | null>(null);
  const [hint, setHint] = useState<-1 | 0 | 1 | "done">(0);
  const hintRef = useRef<typeof hint>(0);

  // points of the live image
  useEffect(() => {
    const small = document.createElement("canvas");
    const sctx = small.getContext("2d", { willReadFrequently: true })!;
    const t = setInterval(() => {
      const v = video.current;
      if (!v || !v.videoWidth) return;
      const h = Math.round((v.videoHeight * FEATURE_W) / v.videoWidth);
      small.width = FEATURE_W; small.height = h;
      sctx.drawImage(v, 0, 0, FEATURE_W, h);
      const g = grayFromRGBA(sctx.getImageData(0, 0, FEATURE_W, h).data, FEATURE_W, h);
      mesh.current = guideMesh(detectFeatures(g, FEATURE_W, h));
    }, FEATURE_PERIOD);
    return () => clearInterval(t);
  }, [video]);

  // drawing
  useEffect(() => {
    let raf = 0, last = 0;
    const draw = (now: number) => {
      raf = requestAnimationFrame(draw);
      if (now - last < DRAW_PERIOD) return; // ~25 fps is plenty for a guide and spares the scan analysis
      last = now;
      const c = canvas.current, v = video.current, m = mesh.current;
      if (!c || !v || !v.videoWidth || !m) return;
      const W = 720, H = Math.round((720 * v.videoHeight) / v.videoWidth);
      if (c.width !== W || c.height !== H) { c.width = W; c.height = H; }
      const ctx = c.getContext("2d")!;
      ctx.clearRect(0, 0, W, H);
      const fov = fieldOfView(v.videoWidth, v.videoHeight);
      const { heading, pitch } = pose.current ?? { heading: null, pitch: null };
      const cov = map.current;
      const hasPose = heading != null && cov != null;
      const p0 = pitch ?? 0;
      // without orientation sensors: the view is shown covered right after a kept frame, then fades back
      const sinceKept = performance.now() - (lastKept.current ?? -Infinity);
      const fallbackAlpha = Math.min(1, sinceKept / 1500);
      const { points, triangles } = m;
      ctx.lineWidth = 1.4;
      for (let i = 0; i < triangles.length; i += 3) {
        const a = points[triangles[i]], b = points[triangles[i + 1]], d = points[triangles[i + 2]];
        const cx = (a.x + b.x + d.x) / 3, cy = (a.y + b.y + d.y) / 3;
        let fill: string | null;
        if (hasPose) {
          const n = cov.at(heading + (cx - 0.5) * fov.h, p0 + (0.5 - cy) * fov.v);
          fill = n === 0 ? UNCOVERED : n === 1 ? ONCE : null;
        } else {
          fill = fallbackAlpha > 0.02 ? `rgba(37, 78, 235, ${(0.45 * fallbackAlpha).toFixed(3)})` : null;
        }
        ctx.beginPath();
        ctx.moveTo(a.x * W, a.y * H); ctx.lineTo(b.x * W, b.y * H); ctx.lineTo(d.x * W, d.y * H); ctx.closePath();
        if (fill) { ctx.fillStyle = fill; ctx.fill(); }
      }
      // wireframe on top
      ctx.setLineDash([5, 4]);
      ctx.strokeStyle = "rgba(255, 255, 255, 0.55)";
      ctx.beginPath();
      for (let i = 0; i < triangles.length; i += 3) {
        const a = points[triangles[i]], b = points[triangles[i + 1]], d = points[triangles[i + 2]];
        ctx.moveTo(a.x * W, a.y * H); ctx.lineTo(b.x * W, b.y * H); ctx.lineTo(d.x * W, d.y * H); ctx.closePath();
      }
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = "rgba(255, 255, 255, 0.85)";
      for (const p of points) { if (p.x > 0 && p.x < 1 && p.y > 0 && p.y < 1) ctx.fillRect(p.x * W - 1.5, p.y * H - 1.5, 3, 3); }

      // test / debug hooks without re-rendering React at 60 fps
      const viewCov = hasPose ? cov.viewCoverage(heading, p0, fov.h, fov.v) : 1 - fallbackAlpha;
      c.dataset.coverage = String(Math.round(viewCov * 100));
      c.dataset.points = String(points.length);
      let next: typeof hint = 0;
      if (hasPose && viewCov >= 0.8) {
        const dir = cov.nextDirection(heading, p0, fov.h);
        next = dir === 0 ? "done" : dir;
      }
      if (next !== hintRef.current) { hintRef.current = next; setHint(next); }
    };
    raf = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(raf);
  }, [video, pose, map, lastKept]);

  return (
    <>
      <canvas ref={canvas} className="pointer-events-none absolute inset-0 h-full w-full object-cover" data-testid="scan-guide" />
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
