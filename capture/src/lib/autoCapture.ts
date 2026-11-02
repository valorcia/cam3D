/**
 * Continuous scan ("film the object, frames are picked automatically").
 *
 * The camera stream is analysed ~8 times per second on a small grayscale
 * version (320 px wide). A frame is kept when it is:
 *  - sharp compared with the recent frames (relative variance of Laplacian:
 *    absolute values depend on the scene),
 *  - not taken during a fast move (difference with the previous analysed frame),
 *  - different enough from the last kept frame (new point of view),
 *  - correctly exposed.
 * Kept frames are then grabbed at the full camera resolution.
 * Pure decision logic (AutoSelector) is unit-tested; the browser part is in useAutoScan.
 */
import { grayFromRGBA, laplacianVariance, mean } from "./quality";

export type Reason = "kept" | "stationary" | "too_fast" | "blurry" | "dark" | "bright" | "cooldown" | "warmup";

export interface Density { label: string; newViewDiff: number }
export const DENSITIES: Record<"light" | "normal" | "dense", Density> = {
  light: { label: "Léger", newViewDiff: 13 },
  normal: { label: "Normal", newViewDiff: 9 },
  dense: { label: "Dense", newViewDiff: 6 },
};

export interface FrameStats { sharpness: number; brightness: number; thumb: Float32Array }

export const THUMB_W = 64, THUMB_H = 48;

export function thumbnail(gray: Float32Array, w: number, h: number): Float32Array {
  const out = new Float32Array(THUMB_W * THUMB_H);
  const sx = w / THUMB_W, sy = h / THUMB_H;
  for (let y = 0; y < THUMB_H; y++) {
    for (let x = 0; x < THUMB_W; x++) {
      let s = 0, n = 0;
      for (let yy = Math.floor(y * sy); yy < Math.floor((y + 1) * sy); yy++) {
        for (let xx = Math.floor(x * sx); xx < Math.floor((x + 1) * sx); xx++) { s += gray[yy * w + xx]; n++; }
      }
      out[y * THUMB_W + x] = n ? s / n : 0;
    }
  }
  return out;
}

/** Mean absolute difference between two thumbnails, after removing the global
 *  brightness change (auto-exposure must not look like camera motion). */
export function thumbDiff(a: Float32Array, b: Float32Array): number {
  let ma = 0, mb = 0;
  for (let i = 0; i < a.length; i++) { ma += a[i]; mb += b[i]; }
  const off = (ma - mb) / a.length;
  let d = 0;
  for (let i = 0; i < a.length; i++) d += Math.abs(a[i] - b[i] - off);
  return d / a.length;
}

export function frameStats(rgba: Uint8ClampedArray, w: number, h: number): FrameStats {
  const g = grayFromRGBA(rgba, w, h);
  return { sharpness: laplacianVariance(g, w, h), brightness: mean(g), thumb: thumbnail(g, w, h) };
}

export class AutoSelector {
  private recentSharp: number[] = [];
  private prev: Float32Array | null = null;
  private lastKept: Float32Array | null = null;
  private lastKeptAt = -Infinity;
  constructor(public newViewDiff = DENSITIES.normal.newViewDiff, private fastDiff = 22, private blurRatio = 0.45,
              private minIntervalMs = 350) {}

  reset() { this.recentSharp = []; this.prev = null; this.lastKept = null; this.lastKeptAt = -Infinity; }

  push(s: FrameStats, t: number): Reason {
    const motion = this.prev ? thumbDiff(s.thumb, this.prev) : 0;
    this.prev = s.thumb;
    this.recentSharp.push(s.sharpness);
    if (this.recentSharp.length > 40) this.recentSharp.shift();
    if (this.recentSharp.length < 3) return "warmup";
    if (s.brightness < 30) return "dark";
    if (s.brightness > 235) return "bright";
    if (motion > this.fastDiff) return "too_fast";
    const sorted = [...this.recentSharp].sort((a, b) => a - b);
    const median = sorted[Math.floor(sorted.length / 2)];
    if (s.sharpness < this.blurRatio * median || s.sharpness < 4) return "blurry";
    if (this.lastKept && thumbDiff(s.thumb, this.lastKept) < this.newViewDiff) return "stationary";
    if (t - this.lastKeptAt < this.minIntervalMs) return "cooldown";
    this.lastKept = s.thumb;
    this.lastKeptAt = t;
    return "kept";
  }
}

export const GUIDANCE: Partial<Record<Reason, string>> = {
  stationary: "Déplacez-vous lentement autour de l’objet",
  too_fast: "Trop rapide : ralentissez",
  blurry: "Image floue : stabilisez le téléphone",
  dark: "Trop sombre : ajoutez de la lumière",
  bright: "Surexposé : évitez le contre-jour",
};

/** Heading/tilt from DeviceOrientation (relative heading is enough to follow a tour). */
export interface Pose { heading: number | null; tilt: number | null }

export function headingFrom(e: DeviceOrientationEvent): number | null {
  const ios = (e as any).webkitCompassHeading;
  if (typeof ios === "number" && !Number.isNaN(ios)) return ios;
  if (typeof e.alpha === "number") return (360 - e.alpha) % 360;
  return null;
}

/** 0 = high (looking down), 1 = middle, 2 = low (looking up); from beta (front-back tilt). */
export function tiltBand(beta: number | null): number | null {
  if (beta == null) return null;
  return beta < 60 ? 0 : beta <= 110 ? 1 : 2;
}
