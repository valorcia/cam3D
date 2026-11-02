// Remote capture end-to-end: phone captures anywhere (incl. offline), encrypted relay, PC import, reconstruction.
//   CAPTURE_URL=http://localhost:3100 RELAY_ACCESS_KEY=… RELAY_DEV_DIR=<dir> CAM3D_URL=http://127.0.0.1:8765 \
//   CAM3D_FAKE_CAMERA=camera.y4m node tests/e2e_remote.mjs
// The capture app must run with RELAY_STORAGE=local (local stand-in for Vercel Blob) and cam3D with
// CAM3D_RELAY_ALLOW=<CAPTURE_URL> (otherwise only *.public.blob.vercel-storage.com is accepted).
import { createRequire } from "node:module";
import fs from "node:fs";
import path from "node:path";

const require = createRequire(import.meta.url);
const { chromium, devices } = require("playwright");
const CAPTURE = process.env.CAPTURE_URL ?? "http://localhost:3100";
const CAM3D = process.env.CAM3D_URL ?? "http://127.0.0.1:8765";
const KEY = process.env.RELAY_ACCESS_KEY;
const DEV_DIR = process.env.RELAY_DEV_DIR;
const SHOTS = process.env.CAM3D_SHOTS ?? path.resolve("tests/screenshots");
fs.mkdirSync(SHOTS, { recursive: true });

let failures = 0;
const step = async (name, fn) => {
  const t = Date.now();
  try { await fn(); console.log(`✔ ${name} (${((Date.now() - t) / 1000).toFixed(1)}s)`); }
  catch (e) { failures++; console.log(`✘ ${name}\n   ${String(e.message ?? e).split("\n")[0]}`); }
};
const expect = (c, m) => { if (!c) throw new Error(m); };
const counter = (page) => page.locator('[data-testid="counter"]').innerText();
const waitCounter = (page, re, timeout = 60000) =>
  page.waitForFunction((src) => new RegExp(src).test(document.querySelector('[data-testid="counter"]')?.textContent ?? ""), re.source, { timeout });

const browser = await chromium.launch({
  args: ["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream", `--use-file-for-fake-video-capture=${process.env.CAM3D_FAKE_CAMERA}`],
});
const phoneCtx = await browser.newContext({ ...devices["Pixel 7"], permissions: ["camera"], acceptDownloads: true });
const phone = await phoneCtx.newPage();
const phoneErrors = [];
let offline = false;
phone.on("console", (m) => { if (m.type() === "error" && !offline) phoneErrors.push(m.text()); });
let code = "";
let scanId = "";

await step("téléphone : clé du relais enregistrée (mauvaise clé refusée)", async () => {
  await phone.goto(`${CAPTURE}/settings/`);
  await phone.locator('[data-testid="relay-key"]').fill("mauvaise-cle-0000000");
  await phone.locator('[data-testid="relay-key-save"]').click();
  await phone.getByText("Clé refusée par le relais.").waitFor();
  await phone.locator('[data-testid="relay-key"]').fill(KEY);
  await phone.locator('[data-testid="relay-key-save"]').click();
  await phone.locator('[data-testid="relay-key-ok"]').waitFor();
  phoneErrors.length = 0; // the 403 of the deliberately wrong key above is expected
});

let N = 0; // frames kept by the continuous scan
await step("téléphone : scan continu (images choisies automatiquement), envoyées chiffrées", async () => {
  await phone.goto(`${CAPTURE}/`);
  await phone.locator('[data-testid="new-scan"]').click();
  await phone.waitForURL(/\/scan\/\?id=/);
  scanId = new URL(phone.url()).searchParams.get("id");
  await phone.locator('[data-testid="start-camera"]').click();
  await phone.locator('[data-testid="scan-toggle"]').waitFor();
  expect(await phone.locator('[data-testid="mode-auto"]').getAttribute("aria-pressed") === "true", "le scan continu n'est pas le mode par défaut");
  await phone.waitForTimeout(800);
  await phone.locator('[data-testid="scan-toggle"]').click();
  // the fake camera shows the 11 castle photos for 2 s each; a simulated compass turns 360° meanwhile
  const t0 = Date.now();
  const seen = new Set();
  while (Date.now() - t0 < 26000) {
    const heading = ((Date.now() - t0) / 22000) * 360 % 360;
    await phone.evaluate((h) => window.dispatchEvent(Object.assign(new Event("deviceorientation"), { alpha: (360 - h) % 360, beta: 85, gamma: 0 })), heading);
    const g = await phone.locator('[data-testid="auto-guidance"]').textContent().catch(() => null);
    if (g) seen.add(g);
    await phone.waitForTimeout(250);
  }
  await phone.screenshot({ path: path.join(SHOTS, "40-scan-continu.png") });
  await phone.locator('[data-testid="scan-toggle"]').click();
  // wait until the last frames being saved are counted (stable for 3 s)
  let last = -1;
  for (let stable = 0; stable < 3;) {
    await phone.waitForTimeout(1000);
    N = Number((await phone.locator('[data-testid="counter"]').innerText()).match(/^(\d+)/)[1]);
    stable = N === last ? stable + 1 : 0;
    last = N;
  }
  console.log(`   ${N} images retenues automatiquement ; consignes vues : ${[...seen].join(" | ")}`);
  expect(N >= 10 && N <= 18, `images retenues : ${N}`);
  expect([...seen].some((g) => /Déplacez-vous/.test(g)), "aucune consigne de déplacement affichée");
  const ring = await phone.locator('[data-testid="coverage"]').innerText();
  expect(/(\d+)° du tour/.test(ring) && Number(ring.match(/(\d+)°/)[1]) >= 270, `anneau : ${ring}`);
  await waitCounter(phone, new RegExp(`^${N} photos sur ce téléphone · ${N} chiffrées en ligne$`), 90000);
});

await step("le relais ne contient que des données chiffrées", async () => {
  const dir = path.join(DEV_DIR, "scans", scanId);
  const files = fs.readdirSync(dir);
  expect(files.length === N + 1 && files.includes("manifest.bin"), `fichiers: ${files.length}`);
  for (const f of files) {
    const b = fs.readFileSync(path.join(dir, f));
    expect(b.subarray(0, 4).toString() === "C3D1", `${f}: en-tête`);
    expect(!b.includes(Buffer.from([0xff, 0xd8, 0xff])) || b.indexOf(Buffer.from([0xff, 0xd8, 0xff])) > 16, `${f}: JPEG en clair ?`);
    expect(!b.includes(Buffer.from("IMG_")), `${f}: nom de fichier en clair`);
  }
});

await step("hors connexion : capture possible, application rouverte sans réseau", async () => {
  offline = true;
  await phoneCtx.setOffline(true);
  await phone.locator('[data-testid="mode-manual"]').click();
  for (let i = 0; i < 2; i++) { await phone.locator('[data-testid="shutter"]').click(); await phone.waitForTimeout(1350); }
  await waitCounter(phone, new RegExp(`^${N + 2} photos sur ce téléphone · ${N} chiffrées en ligne$`));
  await phone.reload();                       // served by the service worker
  await waitCounter(phone, new RegExp(`^${N + 2} photos sur ce téléphone · ${N} chiffrées en ligne$`));
  await phone.getByText(/Hors connexion : 2 photo\(s\) seront envoyées/).waitFor();
  await phone.screenshot({ path: path.join(SHOTS, "41-hors-connexion.png"), fullPage: true });
});

await step("retour du réseau : envoi automatique des photos en attente", async () => {
  await phoneCtx.setOffline(false);
  offline = false;
  await waitCounter(phone, new RegExp(`^${N + 2} photos sur ce téléphone · ${N + 2} chiffrées en ligne$`), 90000);
  await phone.getByText("Tout est envoyé et chiffré.").waitFor({ timeout: 60000 });
  code = (await phone.locator('[data-testid="transfer-code"]').inputValue()).trim();
  expect(code.startsWith("c3d1:"), "code absent");
});

await step("ordinateur : lien de transfert → cam3D local → projet avec toutes les photos", async () => {
  const pc = await browser.newContext({ viewport: { width: 1360, height: 900 } });
  const page = await pc.newPage();
  await page.goto(`${CAPTURE}/t/#${code}`);
  const href = await page.locator('[data-testid="open-local"]').getAttribute("href");
  expect(href.startsWith(`${CAM3D}/import/#`), href);
  await page.locator('[data-testid="open-local"]').click();
  await page.waitForURL(/\/import\//);
  await page.waitForFunction(() => (document.querySelector('[data-testid="relay-code"]'))?.value.startsWith("c3d1:"), null, { timeout: 15000 }).catch(() => { throw new Error("code non transmis"); });
  expect(!page.url().includes("c3d1"), "le code reste dans la barre d'adresse");
  await page.locator('[data-testid="relay-import"]').click();
  await page.waitForURL(/\/project\/\?id=/);
  const pid = new URL(page.url()).searchParams.get("id");
  await page.waitForFunction((n) => document.querySelector("h3")?.textContent === `${n} photos`, N + 2, { timeout: 120000 });
  await page.screenshot({ path: path.join(SHOTS, "42-import-pc.png") });
  globalThis.pid = pid;
  await pc.close();
});

await step("reconstruction sur l'ordinateur des photos prises à distance", async () => {
  const r = await fetch(`${CAM3D}/api/projects/${globalThis.pid}/reconstruct`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ profile: "fast", formats: ["dae"] }) });
  const jid = (await r.json()).id;
  let j;
  for (;;) { j = await (await fetch(`${CAM3D}/api/jobs/${jid}`)).json(); if (!["queued", "running"].includes(j.status)) break; await new Promise((s) => setTimeout(s, 2000)); }
  expect(j.status === "succeeded", j.error);
  const sfm = j.events.find((e) => e.stage === "sfm" && e.status === "finished");
  console.log(`   ${sfm?.message}`);
  const reg = Number(sfm.message.match(/^(\d+)\//)[1]);
  expect(reg >= N, `caméras enregistrées : ${reg} pour ${N + 2} photos`);
});

await step("sans relais : ZIP exporté du téléphone importé dans un projet", async () => {
  const [dl] = await Promise.all([phone.waitForEvent("download"), phone.locator('[data-testid="zip"]').click()]);
  const f = path.join(SHOTS, "scan.zip");
  await dl.saveAs(f);
  const pid = (await (await fetch(`${CAM3D}/api/projects`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: "ZIP" }) })).json()).id;
  const form = new FormData();
  form.append("files", new Blob([fs.readFileSync(f)], { type: "application/zip" }), "scan.zip");
  const res = await (await fetch(`${CAM3D}/api/projects/${pid}/photos`, { method: "POST", body: form })).json();
  expect(res.added.length === N + 2, `ajoutées: ${res.added?.length} ${JSON.stringify(res.rejected)}`);
});

await step("retrait immédiat du relais depuis le téléphone", async () => {
  await phone.getByText("Retirer ce scan du relais maintenant").click();
  await phone.waitForFunction(() => /0 chiffrée en ligne/.test(document.querySelector('[data-testid="counter"]')?.textContent ?? "") || !document.querySelector('[data-testid="transfer-code"]'));
  await phone.waitForTimeout(500);
  expect(!fs.existsSync(path.join(DEV_DIR, "scans", scanId)), "le scan est toujours sur le relais");
});

await step("application passée en arrière-plan : caméra libérée, puis rouverte au retour", async () => {
  const ctx = await browser.newContext({ ...devices["Pixel 7"], permissions: ["camera"] });
  await ctx.addInitScript(() => {
    const gum = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
    window.__streams = [];
    navigator.mediaDevices.getUserMedia = async (c) => { const s = await gum(c); window.__streams.push(s); return s; };
    window.__setVisibility = (v) => { Object.defineProperty(document, "visibilityState", { value: v, configurable: true }); document.dispatchEvent(new Event("visibilitychange")); };
  });
  const p = await ctx.newPage();
  await p.goto(`${CAPTURE}/`);
  await p.locator('[data-testid="new-scan"]').click();
  await p.waitForURL(/\/scan\//);
  await p.locator('[data-testid="start-camera"]').click();
  await p.locator('[data-testid="video-info"]').waitFor();
  await p.evaluate(() => window.__setVisibility("hidden"));
  const live = await p.evaluate(() => window.__streams.flatMap((s) => s.getTracks()).filter((t) => t.readyState === "live").length);
  expect(live === 0, `${live} piste(s) caméra encore actives en arrière-plan`);
  await p.evaluate(() => window.__setVisibility("visible"));
  await p.locator('[data-testid="video-info"]').waitFor({ timeout: 15000 });
  const audio = await p.evaluate(() => window.__streams.some((s) => s.getAudioTracks().length > 0));
  expect(!audio, "un flux micro a été demandé");
  await ctx.close();
});

await step("caméra qui ne renvoie aucune image : nouvel essai puis message, jamais d'écran noir muet", async () => {
  const ctx = await browser.newContext({ ...devices["iPhone 13"] });
  // simulate a browser that grants the camera but never delivers a frame
  await ctx.addInitScript(() => { navigator.mediaDevices.getUserMedia = async () => new MediaStream(); });
  const p = await ctx.newPage();
  await p.goto(`${CAPTURE}/`);
  await p.locator('[data-testid="new-scan"]').click();
  await p.waitForURL(/\/scan\//);
  const t = Date.now();
  await p.locator('[data-testid="start-camera"]').click();
  await p.getByText(/La caméra ne renvoie pas d’image/).waitFor({ timeout: 20000 });
  await p.getByRole("button", { name: "Réessayer" }).waitFor();
  console.log(`   message affiché après ${((Date.now() - t) / 1000).toFixed(0)} s (3 essais de résolution)`);
  await p.screenshot({ path: path.join(SHOTS, "43-camera-sans-image.png") });
  await ctx.close();
});

await step("aucune erreur console sur le téléphone (hors période sans réseau)", async () => {
  expect(phoneErrors.length === 0, phoneErrors.slice(0, 3).join(" | "));
});

await browser.close();
console.log(failures ? `\n${failures} échec(s)` : "\nTous les scénarios ont réussi.");
process.exit(failures ? 1 : 0);
