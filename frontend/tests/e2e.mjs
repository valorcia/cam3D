// End-to-end UI test, real backend, real reconstruction.
//   CAM3D_URL=http://127.0.0.1:8765 CAM3D_PHOTOS=/path/to/jpgs CAM3D_LAN_URL=http://<lan-ip>:8765 node tests/e2e.mjs
// Screenshots are written to CAM3D_SHOTS (default ./tests/screenshots).
import { createRequire } from "node:module";
import fs from "node:fs";
import path from "node:path";

const require = createRequire(import.meta.url);
const { chromium } = require("playwright");

const BASE = process.env.CAM3D_URL ?? "http://127.0.0.1:8765";
const LAN = process.env.CAM3D_LAN_URL;
const PHOTOS = process.env.CAM3D_PHOTOS;
const SHOTS = process.env.CAM3D_SHOTS ?? path.resolve("tests/screenshots");
fs.mkdirSync(SHOTS, { recursive: true });
const photos = fs.readdirSync(PHOTOS).filter((f) => /\.(jpe?g|png)$/i.test(f)).map((f) => path.join(PHOTOS, f));

let failures = 0;
const step = async (name, fn) => {
  const t = Date.now();
  try { await fn(); console.log(`✔ ${name} (${((Date.now() - t) / 1000).toFixed(1)}s)`); }
  catch (e) { failures++; console.log(`✘ ${name}\n   ${String(e.message ?? e).split("\n")[0]}`); }
};
const expect = (cond, msg) => { if (!cond) throw new Error(msg); };

const browser = await chromium.launch({ args: ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"] });
const desktop = await browser.newContext({ viewport: { width: 1360, height: 900 }, acceptDownloads: true });
const page = await desktop.newPage();
const consoleErrors = [];
page.on("console", (m) => { if (m.type() === "error") consoleErrors.push(m.text()); });
const externalRequests = [];
page.on("request", (r) => {
  const u = new URL(r.url());
  // blob:/data: URLs are in-memory (e.g. textures embedded in the GLB), not network requests
  if (["http:", "https:", "ws:", "wss:"].includes(u.protocol) && !["127.0.0.1", "localhost"].includes(u.hostname)) externalRequests.push(r.url());
});

let projectUrl = "";

await step("accueil : actions et état du moteur", async () => {
  await page.goto(BASE + "/");
  await page.getByText("Scannez le réel en 3D.").waitFor();
  for (const t of ["Nouveau scan", "Importer des photos", "Mes projets", "Paramètres", "Derniers scans"]) {
    expect(await page.getByText(t, { exact: true }).first().isVisible(), `"${t}" absent`);
  }
  await page.locator('[title="Connecté au moteur local"]').waitFor({ timeout: 10000 });
  await page.screenshot({ path: path.join(SHOTS, "01-accueil.png") });
});

await step("nouveau scan + import des photos réelles", async () => {
  await page.getByRole("button", { name: /Nouveau scan/ }).click();
  await page.waitForURL(/\/project\/\?id=.*tab=photos/);
  projectUrl = page.url();
  await page.locator('[data-testid="photo-input"]').setInputFiles(photos);
  await page.locator('[data-testid="upload-report"]').waitFor({ timeout: 60000 });
  const report = await page.locator('[data-testid="upload-report"]').innerText();
  expect(report.includes(`${photos.length} photos ajoutées`), `rapport inattendu: ${report}`);
  await page.waitForFunction((n) => document.querySelectorAll('[data-testid="photo-grid"] img').length === n, photos.length);
  await page.screenshot({ path: path.join(SHOTS, "02-photos.png") });
});

await step("rejet d'un fichier non image", async () => {
  const bad = path.join(SHOTS, "pas-une-image.jpg");
  fs.writeFileSync(bad, "ceci n'est pas une image");
  await page.locator('[data-testid="photo-input"]').setInputFiles([bad]);
  await page.getByText(/pas-une-image\.jpg : Image illisible/).waitFor({ timeout: 15000 });
});

await step("reconstruction réelle (profil Rapide) avec suivi des étapes", async () => {
  await page.getByRole("tab", { name: "Reconstruction" }).click();
  await page.getByText("Aucune reconstruction lancée pour ce projet.").waitFor();
  // no invented duration before any measured run on this computer
  expect(!(await page.getByText(/d’après \d+ reconstruction/).count()), "estimation affichée sans historique");
  await page.locator('[data-testid="start-reconstruction"]').click();
  await page.locator('[data-stage="sfm"][data-status="running"], [data-stage="sfm"][data-status="finished"]').waitFor({ timeout: 120000 });
  await page.screenshot({ path: path.join(SHOTS, "03-reconstruction-en-cours.png") });
  await page.locator('[data-stage="export"][data-status="finished"]').waitFor({ timeout: 900000 });
  for (const s of ["prepare", "sfm", "dense", "mesh", "texture", "cleanup", "export"]) {
    expect(await page.locator(`[data-stage="${s}"][data-status="finished"]`).count() === 1, `étape ${s} non terminée`);
  }
  await page.screenshot({ path: path.join(SHOTS, "04-reconstruction-terminee.png") });
});

await step("visualiseur 3D : modèle chargé et rendu WebGL non vide", async () => {
  await page.getByRole("tab", { name: "Modèle 3D" }).click();
  await page.locator('[data-testid="viewer-faces"]').waitFor({ timeout: 60000 });
  await page.waitForFunction(() => !document.body.innerText.includes("Chargement"), null, { timeout: 60000 });
  await page.waitForTimeout(1500);
  const canvas = page.locator('[data-testid="viewer"] canvas').first();
  const shot = await canvas.screenshot({ path: path.join(SHOTS, "05-modele-texture.png") });
  expect(shot.length > 20000, "rendu vide");
  for (const [label, file] of [["Sans texture", "06-sans-texture"], ["Filaire", "07-filaire"], ["Nuage", "08-nuage"]]) {
    await page.locator('[data-testid="mode"]').getByRole("button", { name: label }).click();
    await page.waitForTimeout(label === "Nuage" ? 4000 : 800);
    await canvas.screenshot({ path: path.join(SHOTS, `${file}.png`) });
  }
  await page.locator('[data-testid="mode"]').getByRole("button", { name: "Texturé" }).click();
  await page.locator('[data-testid="cam"]').getByRole("button", { name: "Ortho" }).click();
  await page.locator('[data-testid="view"]').getByRole("button", { name: "Face" }).click();
  await page.waitForTimeout(800);
  await canvas.screenshot({ path: path.join(SHOTS, "09-ortho-face.png") });
  await page.locator('[data-testid="view"]').getByRole("button", { name: "Dessus" }).click();
  await page.waitForTimeout(800);
  await canvas.screenshot({ path: path.join(SHOTS, "10-ortho-dessus.png") });
});

await step("miniature 3D enregistrée automatiquement", async () => {
  const id = new URL(projectUrl).searchParams.get("id");
  let ok = false;
  for (let i = 0; i < 20 && !ok; i++) {
    const p = await (await page.request.get(`${BASE}/api/projects/${id}`)).json();
    ok = p.thumbnail_3d;
    if (!ok) await page.waitForTimeout(500);
  }
  expect(ok, "miniature 3D absente");
});

await step("exports : téléchargement du ZIP SketchUp (DAE + textures)", async () => {
  await page.getByRole("tab", { name: "Exports" }).click();
  const [dl] = await Promise.all([page.waitForEvent("download"), page.locator('[data-testid="download-dae"]').click()]);
  const f = path.join(SHOTS, "model_dae.zip");
  await dl.saveAs(f);
  const buf = fs.readFileSync(f);
  expect(buf.subarray(0, 2).toString() === "PK" && buf.length > 100000, "zip invalide");
  expect(buf.includes(Buffer.from("model.dae")) && buf.includes(Buffer.from("textures/")), "DAE ou textures absents du zip");
  await page.locator('[data-testid="export-stl"]').getByRole("button", { name: "Générer" }).click();
  await page.locator('[data-testid="download-stl"]').waitFor({ timeout: 120000 });
  await page.screenshot({ path: path.join(SHOTS, "11-exports.png") });
});

await step("bibliothèque : carte projet avec miniature, photos, taille", async () => {
  await page.goto(BASE + "/projects/");
  const card = page.locator('[data-testid="project-card"]').first();
  await card.waitFor();
  const text = await card.innerText();
  expect(/11 photos/.test(text) && /Modèle prêt/.test(text) && /Mo/.test(text), `carte incomplète: ${text}`);
  await page.screenshot({ path: path.join(SHOTS, "12-bibliotheque.png") });
});

await step("paramètres : diagnostic matériel et moteurs", async () => {
  await page.goto(BASE + "/settings/");
  await page.getByText("Reconstruction possible").waitFor();
  await page.getByText("OpenMVS", { exact: true }).waitFor();
  await page.screenshot({ path: path.join(SHOTS, "13-parametres.png"), fullPage: true });
});

if (LAN) {
  await step("téléphone (Android, réseau local) : appairage, accès, suppression interdite", async () => {
    const phoneCtx = await browser.newContext({ ...require("playwright").devices["Pixel 7"] });
    const phone = await phoneCtx.newPage();
    await phone.goto(LAN + "/");
    await phone.waitForURL(/\/pair\//, { timeout: 15000 });
    await page.goto(BASE + "/settings/");
    await page.locator('[data-testid="pair-start"]').click();
    const code = (await page.locator('[data-testid="pair-code"]').innerText()).trim();
    await phone.locator('[data-testid="pair-code-input"]').fill(code);
    await phone.screenshot({ path: path.join(SHOTS, "14-telephone-appairage.png") });
    await phone.getByRole("button", { name: "Demander l’accès" }).click();
    await page.locator('[data-testid="pair-request"]').waitFor({ timeout: 15000 });
    await page.screenshot({ path: path.join(SHOTS, "15-ordinateur-demande.png") });
    await page.getByRole("button", { name: "Autoriser" }).click();
    await phone.waitForURL(LAN + "/", { timeout: 15000 });
    await phone.getByText("Derniers scans").waitFor();
    await phone.locator('[data-testid="project-card"]').first().waitFor();
    await phone.screenshot({ path: path.join(SHOTS, "16-telephone-accueil.png") });
    const id = new URL(projectUrl).searchParams.get("id");
    await phone.goto(`${LAN}/project/?id=${id}&tab=model`);
    await phone.locator('[data-testid="viewer-faces"]').waitFor({ timeout: 60000 });
    await phone.waitForTimeout(2500);
    await phone.screenshot({ path: path.join(SHOTS, "17-telephone-modele.png") });
    const del = await phone.request.delete(`${LAN}/api/projects/${id}?confirm=true`);
    expect(del.status() === 403, `suppression par le téléphone: ${del.status()}`);
    await phoneCtx.close();
  });
}

await step("aucune requête vers Internet, aucune erreur console", async () => {
  expect(externalRequests.length === 0, `requêtes externes: ${externalRequests.slice(0, 3).join(", ")}`);
  // 415 = the deliberate rejection of the fake JPEG in the "rejet" step above
  const real = consoleErrors.filter((e) => !/favicon/.test(e) && !/status of 415/.test(e));
  expect(real.length === 0, `erreurs console: ${real.slice(0, 3).join(" | ")}`);
});

await browser.close();
console.log(failures ? `\n${failures} échec(s)` : "\nTous les scénarios ont réussi.");
process.exit(failures ? 1 : 0);
