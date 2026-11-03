/**
 * On-screen scan guide ("looks like a LiDAR scan, helps you find your way").
 *
 * This is NOT a depth measurement: a web page has no access to the iPhone LiDAR.
 * It only combines two real signals:
 *  - points detected in the live image (corners, Shi-Tomasi response) joined
 *    into a triangle mesh drawn over the video;
 *  - which viewing directions are already covered by kept frames, from the
 *    phone's compass (heading) and tilt (pitch) and an approximate field of view.
 * Uncovered parts of the view are tinted, covered parts are left clear.
 */
import Delaunator from "delaunator";

export interface Feature { x: number; y: number; kind?: 0 | 1 | 2 } // normalised 0..1; 0 corner, 1 edge, 2 grid

/**
 * One point per grid cell of a grayscale image, so that the mesh is fine everywhere:
 * the strongest corner of the cell (Shi-Tomasi minimum eigenvalue) when there is one,
 * otherwise the strongest edge pixel, otherwise the cell centre (plain areas).
 */
export function detectFeatures(gray: Float32Array, w: number, h: number, cell = Math.max(4, Math.round(w / 32))): Feature[] {
  const ix = new Float32Array(w * h), iy = new Float32Array(w * h);
  for (let y = 1; y < h - 1; y++) {
    for (let x = 1; x < w - 1; x++) {
      const i = y * w + x;
      ix[i] = (gray[i + 1] - gray[i - 1]) * 0.5;
      iy[i] = (gray[i + w] - gray[i - w]) * 0.5;
    }
  }
  const resp = new Float32Array(w * h), grad = new Float32Array(w * h);
  let max = 0;
  for (let y = 2; y < h - 2; y++) {
    for (let x = 2; x < w - 2; x++) {
      let sxx = 0, syy = 0, sxy = 0;
      for (let dy = -1; dy <= 1; dy++) {
        for (let dx = -1; dx <= 1; dx++) {
          const j = (y + dy) * w + x + dx;
          sxx += ix[j] * ix[j]; syy += iy[j] * iy[j]; sxy += ix[j] * iy[j];
        }
      }
      const half = (sxx - syy) / 2;
      const r = (sxx + syy) / 2 - Math.sqrt(half * half + sxy * sxy);
      const i = y * w + x;
      resp[i] = r;
      grad[i] = sxx + syy;
      if (r > max) max = r;
    }
  }
  const cornerMin = Math.max(max * 0.01, 60); // 60 ≈ a few grey levels of contrast in both directions
  const edgeMin = 9 * 6 * 6;                  // gradient of ~6 grey levels
  const out: Feature[] = [];
  for (let cy = 0; cy < h; cy += cell) {
    for (let cx = 0; cx < w; cx += cell) {
      let bc = cornerMin, bcx = -1, bcy = -1, be = edgeMin, bex = -1, bey = -1;
      for (let y = Math.max(2, cy); y < Math.min(h - 2, cy + cell); y++) {
        for (let x = Math.max(2, cx); x < Math.min(w - 2, cx + cell); x++) {
          const i = y * w + x;
          if (resp[i] > bc) { bc = resp[i]; bcx = x; bcy = y; }
          if (grad[i] > be) { be = grad[i]; bex = x; bey = y; }
        }
      }
      if (bcx >= 0) out.push({ x: bcx / (w - 1), y: bcy / (h - 1), kind: 0 });
      else if (bex >= 0) out.push({ x: bex / (w - 1), y: bey / (h - 1), kind: 1 });
      else out.push({ x: Math.min(1, (cx + cell / 2) / (w - 1)), y: Math.min(1, (cy + cell / 2) / (h - 1)), kind: 2 });
    }
  }
  return out;
}

/** Triangles (flat index triples into the returned points) covering the whole frame. */
export function guideMesh(features: Feature[], border = 12): { points: Feature[]; triangles: Uint32Array; halfedges: Int32Array } {
  const points: Feature[] = [...features];
  for (let i = 0; i <= border; i++) {
    const t = i / border;
    points.push({ x: t, y: 0, kind: 2 }, { x: t, y: 1, kind: 2 });
    if (i > 0 && i < border) points.push({ x: 0, y: t, kind: 2 }, { x: 1, y: t, kind: 2 });
  }
  const d = Delaunator.from(points, (p) => p.x, (p) => p.y);
  return { points, triangles: d.triangles, halfedges: d.halfedges };
}

/** Part of the video frame visible in a box filled with object-fit: cover (normalised frame coordinates). */
export function coverCrop(videoW: number, videoH: number, boxW: number, boxH: number): { x: number; y: number; w: number; h: number } {
  const s = Math.max(boxW / videoW, boxH / videoH);
  const w = Math.min(1, boxW / s / videoW), h = Math.min(1, boxH / s / videoH);
  return { x: (1 - w) / 2, y: (1 - h) / 2, w, h };
}

/** Approximate field of view of a phone main camera (degrees) for the displayed video. */
export function fieldOfView(videoW: number, videoH: number): { h: number; v: number } {
  const LONG = 64, SHORT = 50; // typical 26 mm-equivalent wide lens, 4:3 sensor
  return videoW >= videoH ? { h: LONG, v: SHORT } : { h: SHORT, v: LONG };
}

/** Camera pitch from DeviceOrientation beta (phone upright = 0°, pointing down = negative). */
export function pitchFromBeta(beta: number | null | undefined): number | null {
  if (typeof beta !== "number" || Number.isNaN(beta)) return null;
  return Math.max(-90, Math.min(90, beta - 90));
}

/** Middle pitch of a height band, for photos saved before the pitch was recorded. */
export function pitchFromBand(band: number | null | undefined): number | null {
  return band == null ? null : band === 0 ? -40 : band === 2 ? 35 : 0;
}

const STEP = 2; // degrees per cell
const COLS = 360 / STEP, ROWS = 180 / STEP;
const wrap = (a: number) => ((a % 360) + 360) % 360;

/** Viewing directions covered by kept frames, on a yaw × pitch grid. */
export class CoverageMap {
  readonly counts = new Uint16Array(COLS * ROWS);
  version = 0; // incremented at every change, so that a view can tell when to redraw

  private col(yaw: number) { return Math.floor(wrap(yaw) / STEP) % COLS; }
  private row(pitch: number) { return Math.max(0, Math.min(ROWS - 1, Math.floor((pitch + 90) / STEP))); }

  /** Marks the field of view of a frame taken at (yaw, pitch). */
  mark(yaw: number, pitch: number, fovH: number, fovV: number) {
    const r0 = this.row(pitch - fovV / 2), r1 = this.row(pitch + fovV / 2);
    const cols = Math.max(1, Math.round(fovH / STEP));
    const c0 = this.col(yaw - fovH / 2);
    this.version++;
    for (let r = r0; r <= r1; r++) for (let k = 0; k < cols; k++) {
      const i = r * COLS + ((c0 + k) % COLS);
      if (this.counts[i] < 65535) this.counts[i]++;
    }
  }

  at(yaw: number, pitch: number): number { return this.counts[this.row(pitch) * COLS + this.col(yaw)]; }

  /** Share (0..1) of the current view already covered at least once. */
  viewCoverage(yaw: number, pitch: number, fovH: number, fovV: number): number {
    let seen = 0, total = 0;
    for (let dp = -fovV / 2 + STEP / 2; dp < fovV / 2; dp += STEP) {
      for (let dy = -fovH / 2 + STEP / 2; dy < fovH / 2; dy += STEP) {
        total++;
        if (this.at(yaw + dy, pitch + dp) > 0) seen++;
      }
    }
    return total ? seen / total : 0;
  }

  /** Closest side (+1 right, -1 left) with uncovered directions at this pitch, 0 when the whole turn is done. */
  nextDirection(yaw: number, pitch: number, fovH: number): -1 | 0 | 1 {
    for (let d = fovH / 2; d <= 180; d += STEP) {
      if (this.at(yaw + d, pitch) === 0) return 1;
      if (this.at(yaw - d, pitch) === 0) return -1;
    }
    return 0;
  }

  /** Share (0..1) of the full turn covered at this pitch. */
  turnCoverage(pitch: number): number {
    const r = this.row(pitch);
    let n = 0;
    for (let c = 0; c < COLS; c++) if (this.counts[r * COLS + c] > 0) n++;
    return n / COLS;
  }
}
