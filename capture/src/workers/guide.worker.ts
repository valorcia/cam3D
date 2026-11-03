/// <reference lib="webworker" />
// Scan guide off the main thread: point detection, triangulation and drawing on an OffscreenCanvas.
import { GuideRenderer, type Crop } from "@/lib/guideRender";

type Msg =
  | { type: "init"; canvas: OffscreenCanvas }
  | { type: "size"; W: number; H: number; cssW: number; cssH: number; scale: number }
  | { type: "frame"; rgba: Uint8ClampedArray; w: number; h: number; crop: Crop; cell: number }
  | { type: "pose"; heading: number | null; pitch: number | null; fov: { h: number; v: number } }
  | { type: "coverage"; counts: Uint16Array }
  | { type: "kept"; at: number };

const r = new GuideRenderer();
let canvas: OffscreenCanvas | null = null, ctx: OffscreenCanvasRenderingContext2D | null = null;
let size = { W: 0, H: 0, cssW: 0, cssH: 0, scale: 1 };
let scheduled = false;

function draw() {
  scheduled = false;
  if (!canvas || !ctx || !size.W) return;
  const stats = r.render(ctx, size.W, size.H, size.cssW, size.cssH, size.scale, performance.now() + offset);
  if (stats) (self as unknown as Worker).postMessage({ type: "stats", stats });
  if (performance.now() + offset - r.lastKept < 1600) schedule(); // keep fading after a kept frame
}
function schedule() { if (!scheduled) { scheduled = true; setTimeout(draw, 40); } }

// performance.now() of the page and of the worker have different origins: the page sends its clock
let offset = 0;

self.onmessage = (e: MessageEvent<Msg & { now?: number }>) => {
  const m = e.data;
  if (typeof m.now === "number") offset = m.now - performance.now();
  switch (m.type) {
    case "init": canvas = m.canvas; ctx = canvas.getContext("2d"); break;
    case "size":
      size = m;
      if (canvas && (canvas.width !== m.W || canvas.height !== m.H)) { canvas.width = m.W; canvas.height = m.H; }
      break;
    case "frame": r.setFrame(m.rgba, m.w, m.h, m.crop, m.cell); break;
    case "pose": r.heading = m.heading; r.pitch = m.pitch; r.fov = m.fov; break;
    case "coverage": r.setCoverage(m.counts); break;
    case "kept": r.lastKept = m.at; break;
  }
  schedule();
};
