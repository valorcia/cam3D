import { describe, expect, it } from "vitest";
import { judge, laplacianVariance, mean } from "./quality";

function noise(w: number, h: number, seed = 1) {
  const g = new Float32Array(w * h);
  let s = seed;
  for (let i = 0; i < g.length; i++) { s = (s * 1103515245 + 12345) % 2 ** 31; g[i] = (s / 2 ** 31) * 255; }
  return g;
}

describe("quality", () => {
  it("flat image has zero sharpness, noise is sharp", () => {
    expect(laplacianVariance(new Float32Array(100 * 80).fill(128), 100, 80)).toBe(0);
    expect(laplacianVariance(noise(100, 80), 100, 80)).toBeGreaterThan(1000);
  });
  it("box blur reduces the Laplacian variance a lot", () => {
    const w = 120, h = 90, g = noise(w, h), b = new Float32Array(w * h);
    for (let y = 2; y < h - 2; y++) for (let x = 2; x < w - 2; x++) {
      let s = 0; for (let dy = -2; dy <= 2; dy++) for (let dx = -2; dx <= 2; dx++) s += g[(y + dy) * w + x + dx];
      b[y * w + x] = s / 25;
    }
    expect(laplacianVariance(b, w, h)).toBeLessThan(laplacianVariance(g, w, h) / 10);
  });
  it("uses the server thresholds", () => {
    expect(judge(10, 128).warnings).toEqual(["floue"]);
    expect(judge(500, 10).warnings).toEqual(["trop sombre"]);
    expect(judge(500, 250).warnings).toEqual(["surexposée"]);
    expect(judge(500, 128).warnings).toEqual([]);
    expect(mean(new Float32Array([0, 255]))).toBe(127.5);
  });
});
