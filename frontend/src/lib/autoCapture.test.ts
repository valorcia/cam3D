import { describe, expect, it } from "vitest";
import { coveredSectors } from "../components/AutoScan";
import { AutoSelector, THUMB_H, THUMB_W, thumbDiff, tiltBand, type FrameStats } from "./autoCapture";

function view(seed: number, gain = 0): Float32Array {
  const t = new Float32Array(THUMB_W * THUMB_H);
  let s = seed;
  for (let i = 0; i < t.length; i++) { s = (s * 1103515245 + 12345) % 2 ** 31; t[i] = 60 + (s / 2 ** 31) * 120 + gain; }
  return t;
}
const frame = (thumb: Float32Array, sharp = 500, bright = 128): FrameStats => ({ sharpness: sharp, brightness: bright, thumb });

describe("AutoSelector", () => {
  it("keeps one frame per new view, ignores a still camera", () => {
    const sel = new AutoSelector();
    const a = view(1), b = view(2);
    const reasons: string[] = [];
    let t = 0;
    for (let i = 0; i < 8; i++) reasons.push(sel.push(frame(a), (t += 125)));
    // the cut to a new view is first seen as a fast move, then kept once stable
    for (let i = 0; i < 8; i++) reasons.push(sel.push(frame(b), (t += 125)));
    expect(reasons.filter((r) => r === "kept").length).toBe(2);
    expect(reasons).toContain("stationary");
    expect(reasons).toContain("too_fast");
  });

  it("rejects blurred, dark and overexposed frames", () => {
    const sel = new AutoSelector();
    let t = 0;
    for (let i = 0; i < 5; i++) sel.push(frame(view(1)), (t += 125));
    expect(sel.push(frame(view(1), 50), (t += 125))).toBe("blurry");
    expect(sel.push(frame(view(1), 500, 10), (t += 125))).toBe("dark");
    expect(sel.push(frame(view(1), 500, 250), (t += 125))).toBe("bright");
  });

  it("does not mistake an exposure change for motion", () => {
    expect(thumbDiff(view(3), view(3, 25))).toBeLessThan(0.001);
    expect(thumbDiff(view(3), view(4))).toBeGreaterThan(20);
  });

  it("maps phone tilt to height bands", () => {
    expect(tiltBand(30)).toBe(0);
    expect(tiltBand(90)).toBe(1);
    expect(tiltBand(130)).toBe(2);
    expect(tiltBand(null)).toBeNull();
  });
});

describe("coverage ring", () => {
  it("a full tour with a frame every ~27° covers the whole ring", () => {
    const tour = Array.from({ length: 14 }, (_, i) => ({ heading: i * 27, tilt: 1 }));
    const keys = coveredSectors(tour);
    expect(new Set([...keys].map((k) => k.split(":")[1])).size).toBe(24);
  });
  it("a jump of more than 45° leaves the gap uncovered, and bands stay separate", () => {
    const keys = coveredSectors([{ heading: 0, tilt: 1 }, { heading: 90, tilt: 1 }, { heading: 100, tilt: 0 }]);
    expect(keys.has("1:0") && keys.has("1:6") && keys.has("0:6")).toBe(true);
    expect(keys.has("1:3")).toBe(false);
  });
});
