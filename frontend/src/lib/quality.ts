/**
 * Client-side photo quality checks, mirroring the engine (stages/prepare.py):
 * sharpness = variance of the Laplacian on a grayscale image 800 px wide,
 * brightness = mean gray level. Thresholds are the server's.
 */
export const BLUR_THRESHOLD = 25;
export const DARK_THRESHOLD = 30;
export const BRIGHT_THRESHOLD = 235;

export function grayFromRGBA(data: Uint8ClampedArray, w: number, h: number): Float32Array {
  const g = new Float32Array(w * h);
  for (let i = 0, p = 0; i < g.length; i++, p += 4) g[i] = 0.299 * data[p] + 0.587 * data[p + 1] + 0.114 * data[p + 2];
  return g;
}

export function laplacianVariance(g: Float32Array, w: number, h: number): number {
  let sum = 0, sum2 = 0, n = 0;
  for (let y = 1; y < h - 1; y++) {
    for (let x = 1; x < w - 1; x++) {
      const i = y * w + x;
      const v = g[i - w] + g[i + w] + g[i - 1] + g[i + 1] - 4 * g[i];
      sum += v; sum2 += v * v; n++;
    }
  }
  if (!n) return 0;
  const mean = sum / n;
  return sum2 / n - mean * mean;
}

export function mean(g: Float32Array): number {
  let s = 0;
  for (let i = 0; i < g.length; i++) s += g[i];
  return g.length ? s / g.length : 0;
}

export interface Quality { sharpness: number; brightness: number; warnings: string[] }

export function judge(sharpness: number, brightness: number): Quality {
  const warnings: string[] = [];
  if (sharpness < BLUR_THRESHOLD) warnings.push("floue");
  if (brightness < DARK_THRESHOLD) warnings.push("trop sombre");
  else if (brightness > BRIGHT_THRESHOLD) warnings.push("surexposée");
  return { sharpness, brightness, warnings };
}

/** Analyse an image blob in the browser (no upload needed). */
export async function analyseBlob(blob: Blob): Promise<Quality> {
  const bmp = await createImageBitmap(blob);
  const w = 800;
  const h = Math.max(1, Math.round((bmp.height * w) / bmp.width));
  const canvas = document.createElement("canvas");
  canvas.width = w; canvas.height = h;
  const ctx = canvas.getContext("2d", { willReadFrequently: true })!;
  ctx.drawImage(bmp, 0, 0, w, h);
  bmp.close?.();
  const g = grayFromRGBA(ctx.getImageData(0, 0, w, h).data, w, h);
  return judge(laplacianVariance(g, w, h), mean(g));
}
