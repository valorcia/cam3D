/**
 * Builds and draws the scan guide (see scanGuide.ts). Shared by the Web Worker (OffscreenCanvas,
 * keeps the main thread free for the frame selection) and the main-thread fallback.
 */
import { grayFromRGBA } from "./quality";
import { CoverageMap, detectFeatures, guideMesh, type Feature } from "./scanGuide";

const UNCOVERED = "rgba(37, 78, 235, 0.45)";
const ONCE = "rgba(37, 78, 235, 0.14)";

export interface Crop { x: number; y: number; w: number; h: number }
export interface GuideStats { coverage: number; points: number; triangles: number; cell: number; hint: -1 | 0 | 1 | "done" }

type Ctx = CanvasRenderingContext2D | OffscreenCanvasRenderingContext2D;

export class GuideRenderer {
  private points: Feature[] = [];
  private triangles: Uint32Array<ArrayBufferLike> = new Uint32Array(0);
  private halfedges: Int32Array<ArrayBufferLike> = new Int32Array(0);
  private crop: Crop = { x: 0, y: 0, w: 1, h: 1 };
  private meshVersion = 0;
  private drawn = "";
  map = new CoverageMap();
  heading: number | null = null;
  pitch: number | null = null;
  fov = { h: 50, v: 64 };
  lastKept = -Infinity;

  /** New analysis image (RGBA of the visible part of the video, already resized). */
  setFrame(rgba: Uint8ClampedArray, w: number, h: number, crop: Crop, cell: number) {
    const g = grayFromRGBA(rgba, w, h);
    const m = guideMesh(detectFeatures(g, w, h, cell), Math.ceil(w / cell));
    this.points = m.points; this.triangles = m.triangles; this.halfedges = m.halfedges;
    this.crop = crop;
    this.meshVersion++;
  }

  setCoverage(counts: Uint16Array) { this.map.counts.set(counts); this.map.version++; }

  /** Draws when something visible changed; returns the stats, or null when nothing was redrawn. */
  render(ctx: Ctx, W: number, H: number, cssW: number, cssH: number, scale: number, now: number): GuideStats | null {
    if (!this.meshVersion) return null;
    const fading = now - this.lastKept < 1600;
    const key = [this.meshVersion, this.heading == null ? "-" : Math.round(this.heading * 2), this.pitch == null ? "-" : Math.round(this.pitch * 2),
      this.map.version, fading ? Math.round(now / 40) : "", W, H].join(":");
    if (key === this.drawn) return null;
    this.drawn = key;

    const { points, triangles, halfedges, crop, fov, map, heading } = this;
    const hasPose = heading != null;
    const p0 = this.pitch ?? 0;
    const fallbackAlpha = Math.min(1, (now - this.lastKept) / 1500);
    ctx.clearRect(0, 0, W, H);
    // one path per tint: thousands of small triangles stay cheap to draw
    const blue = new Path2D(), light = new Path2D(), edges = new Path2D();
    for (let i = 0; i < triangles.length; i += 3) {
      const a = points[triangles[i]], b = points[triangles[i + 1]], d = points[triangles[i + 2]];
      const ax = a.x * W, ay = a.y * H, bx = b.x * W, by = b.y * H, dx = d.x * W, dy = d.y * H;
      // each edge once (an inner edge is shared by two triangles)
      if (halfedges[i] < i) { edges.moveTo(ax, ay); edges.lineTo(bx, by); }
      if (halfedges[i + 1] < i + 1) { edges.moveTo(bx, by); edges.lineTo(dx, dy); }
      if (halfedges[i + 2] < i + 2) { edges.moveTo(dx, dy); edges.lineTo(ax, ay); }
      let target: Path2D | null = blue;
      if (hasPose) {
        // centroid → position in the full camera frame → viewing direction
        const fx = crop.x + ((a.x + b.x + d.x) / 3) * crop.w, fy = crop.y + ((a.y + b.y + d.y) / 3) * crop.h;
        const n = map.at(heading + (fx - 0.5) * fov.h, p0 + (0.5 - fy) * fov.v);
        target = n === 0 ? blue : n === 1 ? light : null;
      }
      if (target) { target.moveTo(ax, ay); target.lineTo(bx, by); target.lineTo(dx, dy); target.closePath(); }
    }
    if (hasPose) {
      ctx.fillStyle = UNCOVERED; ctx.fill(blue);
      ctx.fillStyle = ONCE; ctx.fill(light);
    } else if (fallbackAlpha > 0.02) {
      // without orientation sensors: the view is shown covered right after a kept frame, then fades back
      ctx.fillStyle = `rgba(37, 78, 235, ${(0.45 * fallbackAlpha).toFixed(3)})`; ctx.fill(blue);
    }
    ctx.lineWidth = scale * 0.7;
    ctx.strokeStyle = "rgba(255, 255, 255, 0.42)";
    ctx.stroke(edges);
    ctx.fillStyle = "rgba(255, 255, 255, 0.9)";
    const r = scale * 0.9;
    for (const p of points) if (p.kind === 0) ctx.fillRect(p.x * W - r, p.y * H - r, 2 * r, 2 * r);

    let coverage = 1 - fallbackAlpha;
    let hint: GuideStats["hint"] = 0;
    if (hasPose) {
      // coverage of the visible part only
      const cx = crop.x + crop.w / 2, cy = crop.y + crop.h / 2;
      coverage = map.viewCoverage(heading + (cx - 0.5) * fov.h, p0 + (0.5 - cy) * fov.v, fov.h * crop.w, fov.v * crop.h);
      if (coverage >= 0.8) { const dir = map.nextDirection(heading, p0, fov.h * crop.w); hint = dir === 0 ? "done" : dir; }
    }
    const nTri = triangles.length / 3;
    return { coverage, points: points.length, triangles: nTri, cell: Math.sqrt((cssW * cssH * 2) / Math.max(1, nTri)), hint };
  }
}
