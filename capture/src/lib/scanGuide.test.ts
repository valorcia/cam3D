import { describe, expect, it } from "vitest";
import { CoverageMap, coverCrop, detectFeatures, fieldOfView, guideMesh, pitchFromBeta } from "./scanGuide";

function image(w: number, h: number, f: (x: number, y: number) => number) {
  const g = new Float32Array(w * h);
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) g[y * w + x] = f(x, y);
  return g;
}

describe("detectFeatures", () => {
  it("fills a plain image with a regular grid (no corner) so the mesh stays fine", () => {
    const pts = detectFeatures(image(96, 72, () => 128), 96, 72, 6);
    expect(pts).toHaveLength(16 * 12);
    expect(pts.every((p) => p.kind === 2)).toBe(true);
  });

  it("follows a plain edge with edge points, without inventing corners", () => {
    const pts = detectFeatures(image(96, 72, (x) => (x < 48 ? 40 : 200)), 96, 72, 6);
    expect(pts.filter((p) => p.kind === 0)).toHaveLength(0);
    const edge = pts.filter((p) => p.kind === 1);
    expect(edge.length).toBeGreaterThanOrEqual(10);
    for (const p of edge) expect(Math.abs(p.x * 95 - 47.5)).toBeLessThanOrEqual(1.5);
  });

  it("finds the corners of a checkerboard, near the real corners", () => {
    const w = 96, h = 72, sq = 24;
    const pts = detectFeatures(image(w, h, (x, y) => ((Math.floor(x / sq) + Math.floor(y / sq)) % 2 ? 220 : 30)), w, h, 12).filter((p) => p.kind === 0);
    expect(pts.length).toBeGreaterThanOrEqual(6); // 3 × 2 inner corners
    for (const p of pts) {
      const x = p.x * (w - 1), y = p.y * (h - 1);
      const dx = Math.abs(x - Math.round(x / sq) * sq), dy = Math.abs(y - Math.round(y / sq) * sq);
      expect(Math.max(dx, dy)).toBeLessThanOrEqual(2);
    }
  });
});

describe("coverCrop", () => {
  it("keeps the centre of a 4:3 landscape frame shown on a tall phone screen", () => {
    const c = coverCrop(1280, 960, 412, 839);
    expect(c.h).toBeCloseTo(1, 6);
    expect(c.w).toBeCloseTo((412 / 839) * (960 / 1280), 6);
    expect(c.x).toBeCloseTo((1 - c.w) / 2, 6);
  });
});

describe("guideMesh", () => {
  it("covers the whole frame even without any point", () => {
    const { points, triangles } = guideMesh([]);
    let area = 0;
    for (let i = 0; i < triangles.length; i += 3) {
      const a = points[triangles[i]], b = points[triangles[i + 1]], c = points[triangles[i + 2]];
      area += Math.abs((b.x - a.x) * (c.y - a.y) - (c.x - a.x) * (b.y - a.y)) / 2;
    }
    expect(area).toBeCloseTo(1, 6);
  });
});

describe("CoverageMap", () => {
  const fov = fieldOfView(1440, 1920); // portrait

  it("marks the field of view of a frame, across north (0°/360°)", () => {
    const m = new CoverageMap();
    m.mark(5, 0, fov.h, fov.v);
    expect(m.at(5, 0)).toBe(1);
    expect(m.at(350, 0)).toBe(1);      // 5 − 25 = −20° → 340°: still in view
    expect(m.at(40, 0)).toBe(0);       // outside the 50° wide view
    expect(m.at(5, 60)).toBe(0);       // far above
    expect(m.viewCoverage(5, 0, fov.h, fov.v)).toBe(1);
    expect(m.viewCoverage(5 + fov.h, 0, fov.h, fov.v)).toBe(0);
  });

  it("points to the closest uncovered side, then reports a full turn", () => {
    const m = new CoverageMap();
    for (let yaw = 0; yaw < 200; yaw += 20) m.mark(yaw, 0, fov.h, fov.v);
    expect(m.nextDirection(180, 0, fov.h)).toBe(1);   // 205°+ is still empty
    expect(m.nextDirection(10, 0, fov.h)).toBe(-1);   // 335° and below is empty
    for (let yaw = 200; yaw < 360; yaw += 20) m.mark(yaw, 0, fov.h, fov.v);
    expect(m.nextDirection(90, 0, fov.h)).toBe(0);
    expect(m.turnCoverage(0)).toBe(1);
    expect(m.turnCoverage(80)).toBe(0);
  });

  it("converts the phone tilt to a camera pitch", () => {
    expect(pitchFromBeta(90)).toBe(0);    // upright: horizon
    expect(pitchFromBeta(30)).toBe(-60);  // tilted towards the floor
    expect(pitchFromBeta(null)).toBeNull();
  });
});
