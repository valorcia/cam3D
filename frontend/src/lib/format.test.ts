import { describe, expect, it } from "vitest";
import { failureAdvice, formatBytes, formatDuration, formatMeasure, reduceStages } from "./format";

describe("format", () => {
  it("formats bytes in French units", () => {
    expect(formatBytes(512)).toBe("512 o");
    expect(formatBytes(5_362_912)).toBe("5,1 Mo");
    expect(formatBytes(null)).toBe("—");
  });
  it("formats durations", () => {
    expect(formatDuration(42)).toBe("42 s");
    expect(formatDuration(126)).toBe("2 min 06 s");
    expect(formatDuration(3725)).toBe("1 h 02 min");
  });
});

describe("reduceStages", () => {
  it("only exposes measured progress and keeps the last state", () => {
    const st = reduceStages([
      { stage: "prepare", status: "started", message: "go", progress: null, detail: {} },
      { stage: "prepare", status: "progress", message: "1/2", progress: 0.5, detail: {} },
      { stage: "prepare", status: "finished", message: "ok", progress: null, detail: { duration: 1.2 } },
      { stage: "sfm", status: "started", message: "SfM", progress: null, detail: {} },
      { stage: "sfm", status: "log", message: "Appariement", progress: null, detail: {} },
      { stage: "refine", status: "skipped", message: "désactivé", progress: null, detail: {} },
    ]);
    const by = Object.fromEntries(st.map((s) => [s.id, s]));
    expect(by.prepare.status).toBe("finished");
    expect(by.prepare.duration).toBe(1.2);
    expect(by.prepare.progress).toBeNull();
    expect(by.sfm.status).toBe("running");
    expect(by.sfm.progress).toBeNull(); // no measurement -> no percentage
    expect(by.sfm.message).toBe("Appariement");
    expect(by.refine.status).toBe("skipped");
    expect(by.dense.status).toBe("pending");
    expect(st.map((s) => s.id)).toEqual(["prepare", "sfm", "dense", "mesh", "refine", "texture", "cleanup", "export"]);
  });
});

describe("failureAdvice", () => {
  it("explains SfM failures", () => {
    expect(failureAdvice("sfm", "COLMAP n'a pu enregistrer aucune caméra")).toMatch(/recouvrement/);
    expect(failureAdvice("export", "Traitement annulé")).toBeNull();
  });
});

describe("formatMeasure", () => {
  it("never presents an uncalibrated distance as a real measure", () => {
    expect(formatMeasure(1.2345, null)).toBe("1,235 u (non étalonné)");
  });
  it("converts calibrated distances", () => {
    expect(formatMeasure(2, 0.5, "m")).toBe("1 m");
    expect(formatMeasure(2, 0.5, "cm")).toBe("100 cm");
    expect(formatMeasure(0.0123, 1, "mm")).toBe("12 mm");
  });
});
