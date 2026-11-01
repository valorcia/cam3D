import path from "node:path";

/** Local stand-in for Vercel Blob, used only with RELAY_STORAGE=local outside Vercel (dev/tests). */
export const DEV_ROOT = path.resolve(/*turbopackIgnore: true*/ process.env.RELAY_DEV_DIR ?? ".relay-dev");
