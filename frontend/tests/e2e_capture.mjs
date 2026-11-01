// Phase 5 end-to-end: phone capture over local HTTPS, HTTP fallback, video import, reconstruction.
//   CAM3D_URL=http://127.0.0.1:8765 CAM3D_LAN_IP=<ip> CAM3D_FAKE_CAMERA=/path/camera.y4m \
//   CAM3D_VIDEO=/path/walk.mp4 CAM3D_PHOTOS=/path/jpgs node tests/e2e_capture.mjs
// Prerequisite (simulates a phone that installed the cam3D certificate): add <data>/tls/ca.crt to the
// browser trust store, e.g. `certutil -A -d sql:$HOME/.pki/nssdb -n cam3d -t C,, -i ca.crt`.
// HTTPS errors are NOT ignored: the test fails if the certificate chain is not trusted.
import { createRequire } from "node:module";
import fs from "node:fs";
import path from "node:path";

const require = createRequire(import.meta.url);
const { chromium, devices } = require("playwright");
const BASE = process.env.CAM3D_URL ?? "http://127.0.0.1:8765";
const IP = process.env.CAM3D_LAN_IP;
const SHOTS = process.env.CAM3D_SHOTS ?? path.resolve("tests/screenshots");
fs.mkdirSync(SHOTS, { recursive: true });

let failures = 0;
const step = async (name, fn) => {
  const t = Date.now();
  try { await fn(); console.log(`✔ ${name} (${((Date.now() - t) / 1000).toFixed(1)}s)`); }
  catch (e) { failures++; console.log(`✘ ${name}\n   ${String(e.message ?? e).split("\n")[0]}`); }
};
const expect = (c, m) => { if (!c) throw new Error(m); };
const api = async (method, p, body) => {
  const r = await fetch(BASE + p, { method, headers: { "Content-Type": "application/json" }, body: body ? JSON.stringify(body) : undefined });
  if (!r.ok) throw new Error(`${method} ${p}: ${r.status} ${await r.text()}`);
  return r.json();
};
const waitJob = async (jid, timeoutMs) => {
  const t = Date.now();
  for (;;) {
    const j = await api("GET", `/api/jobs/${jid}`);
    if (!["queued", "running"].includes(j.status)) return j;
    if (Date.now() - t > timeoutMs) throw new Error(`job ${jid} still ${j.status}`);
    await new Promise((r) => setTimeout(r, 2000));
  }
};

const browser = await chromium.launch({
  args: ["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream",
    `--use-file-for-fake-video-capture=${process.env.CAM3D_FAKE_CAMERA}`],
});
const pixel = devices["Pixel 7"];
let pidCapture = "";

await step("QR → page d'installation (HTTP) : certificat téléchargeable, lien HTTPS proposé", async () => {
  pidCapture = (await api("POST", "/api/projects", { name: "Capture téléphone" })).id;
  const s = await api("POST", `/api/pair/sessions?next=${encodeURIComponent(`/capture/?id=${pidCapture}`)}`);
  expect(s.secure && s.urls[0].startsWith(`http://${IP}:8765/setup/`), `urls: ${s.urls}`);
  globalThis.session = s;
});

const phoneCtx = await browser.newContext({ ...pixel, permissions: ["camera"] });
const phone = await phoneCtx.newPage();
const phoneErrors = [];
phone.on("console", (m) => { if (m.type() === "error") phoneErrors.push(m.text()); });

await step("téléphone : installation guidée puis bascule en HTTPS de confiance", async () => {
  await phone.goto(globalThis.session.urls[0]);
  await phone.locator('[data-testid="continue-https"]').waitFor();
  const ca = await phone.request.get(`http://${IP}:8765/api/tls/ca.crt`);
  expect(ca.ok() && (await ca.text()).includes("BEGIN CERTIFICATE"), "certificat non téléchargeable");
  await phone.screenshot({ path: path.join(SHOTS, "20-telephone-installation.png"), fullPage: true });
  await phone.locator('[data-testid="continue-https"]').click();
  await phone.waitForURL(new RegExp(`^https://${IP.replace(/\./g, "\\.")}:8443/pair/`));
  expect(await phone.evaluate(() => window.isSecureContext), "contexte non sécurisé");
});

await step("téléphone : appairage approuvé sur l'ordinateur puis ouverture de la capture", async () => {
  await phone.getByRole("button", { name: "Demander l’accès" }).click();
  let req;
  for (let i = 0; i < 20 && !req; i++) { req = (await api("GET", "/api/pair/pending"))[0]; if (!req) await phone.waitForTimeout(500); }
  expect(req, "aucune demande en attente");
  await api("POST", `/api/pair/requests/${req.id}/approve`);
  await phone.waitForURL(/\/capture\/\?id=/, { timeout: 15000 });
  await phone.locator('[data-testid="shutter"]').waitFor({ timeout: 15000 });
});

await step("capture dans le navigateur : 16 photos, transfert automatique vers l'ordinateur", async () => {
  await phone.waitForTimeout(1500);
  await phone.screenshot({ path: path.join(SHOTS, "21-telephone-viseur.png") });
  for (let i = 0; i < 16; i++) {
    await phone.locator('[data-testid="shutter"]').click();
    await phone.waitForTimeout(1350); // the fake camera shows each castle photo for 2 s
  }
  await phone.waitForFunction(() => /16 photos · 16 envoyées/.test(document.querySelector('[data-testid="capture-counter"]')?.textContent ?? ""), null, { timeout: 120000 });
  await phone.screenshot({ path: path.join(SHOTS, "22-telephone-capture.png") });
  const p = await api("GET", `/api/projects/${pidCapture}`);
  expect(p.photo_count === 16, `photos côté ordinateur: ${p.photo_count}`);
  expect(p.photos[0].width >= 1280, `résolution ${p.photos[0].width}`);
});

await step("suppression d'une photo depuis la bande de capture", async () => {
  await phone.locator('[data-testid="capture-strip"] button[aria-label="Supprimer cette photo"]').first().click();
  await phone.waitForFunction(() => /15 photos/.test(document.querySelector('[data-testid="capture-counter"]')?.textContent ?? ""));
  let n = 0;
  for (let i = 0; i < 10; i++) { n = (await api("GET", `/api/projects/${pidCapture}`)).photo_count; if (n === 15) break; await phone.waitForTimeout(300); }
  expect(n === 15, `photos après suppression: ${n}`);
});

await step("reconstruction des photos prises dans le navigateur", async () => {
  const job = await api("POST", `/api/projects/${pidCapture}/reconstruct`, { profile: "fast", formats: ["dae"] });
  const j = await waitJob(job.id, 900000);
  expect(j.status === "succeeded", `échec: ${j.error}`);
  const p = await api("GET", `/api/projects/${pidCapture}`);
  const sfm = j.events.find((e) => e.stage === "sfm" && e.status === "finished");
  console.log(`   ${sfm?.message} · ${p.model_faces} faces`);
  expect(p.model_faces > 10000, "modèle trop petit");
});

await step("repli HTTP sans certificat : appareil photo natif / galerie", async () => {
  const s = await api("POST", `/api/pair/sessions?next=${encodeURIComponent(`/capture/?id=${pidCapture}`)}`);
  const ctx = await browser.newContext({ ...pixel });
  const p2 = await ctx.newPage();
  await p2.goto(s.urls[0]);
  await p2.locator('[data-testid="continue-http"]').click();
  await p2.getByRole("button", { name: "Demander l’accès" }).click();
  let req;
  for (let i = 0; i < 20 && !req; i++) { req = (await api("GET", "/api/pair/pending"))[0]; if (!req) await p2.waitForTimeout(500); }
  await api("POST", `/api/pair/requests/${req.id}/approve`);
  await p2.waitForURL(/\/capture\/\?id=/, { timeout: 15000 });
  expect(!(await p2.evaluate(() => window.isSecureContext)), "devrait être en HTTP");
  await p2.locator('[data-testid="native-camera"]').waitFor({ state: "attached" });
  expect(await p2.locator('[data-testid="native-camera"]').getAttribute("capture") === "environment", "attribut capture absent");
  await p2.screenshot({ path: path.join(SHOTS, "23-telephone-repli-http.png") });
  const photos = fs.readdirSync(process.env.CAM3D_PHOTOS).filter((f) => /\.jpe?g$/i.test(f)).slice(0, 2).map((f) => path.join(process.env.CAM3D_PHOTOS, f));
  await p2.locator('[data-testid="gallery-input"]').setInputFiles(photos);
  await p2.waitForFunction(() => /17 photos|2 photos · 2 envoyées/.test(document.querySelector('[data-testid="capture-counter"]')?.textContent ?? ""), null, { timeout: 60000 });
  await ctx.close();
});

await step("ordinateur : import vidéo depuis l'interface, images extraites ajoutées", async () => {
  const ctx = await browser.newContext({ viewport: { width: 1360, height: 900 } });
  const page = await ctx.newPage();
  const pid = (await api("POST", "/api/projects", { name: "Import vidéo" })).id;
  await page.goto(`${BASE}/project/?id=${pid}&tab=photos`);
  await page.locator('[data-testid="video-button"]').waitFor();
  await page.locator('[data-testid="video-input"]').setInputFiles(process.env.CAM3D_VIDEO);
  await page.waitForFunction(() => /^\d+ photos?$/.test(document.querySelector("h3")?.textContent ?? "") && Number((document.querySelector("h3")?.textContent ?? "0").split(" ")[0]) >= 10, null, { timeout: 180000 });
  const p = await api("GET", `/api/projects/${pid}`);
  expect(p.photo_count === 11, `images extraites: ${p.photo_count}`);
  await page.screenshot({ path: path.join(SHOTS, "24-import-video.png") });
  await page.locator('[data-testid="phone-capture"]').click();
  await page.getByAltText("QR code").waitFor();
  await page.screenshot({ path: path.join(SHOTS, "25-qr-capture.png") });
  await ctx.close();
});

await step("aucune erreur console sur le téléphone", async () => {
  expect(phoneErrors.length === 0, phoneErrors.slice(0, 3).join(" | "));
});

await browser.close();
console.log(failures ? `\n${failures} échec(s)` : "\nTous les scénarios ont réussi.");
process.exit(failures ? 1 : 0);
