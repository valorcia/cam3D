// Phase 6 end-to-end on a reconstructed project: measure, calibrate, crop, erase, rotate, undo, SketchUp export.
//   CAM3D_URL=http://127.0.0.1:8765 CAM3D_PROJECT=<id> node tests/e2e_edit.mjs
import { createRequire } from "node:module";
import fs from "node:fs";
import path from "node:path";

const require = createRequire(import.meta.url);
const { chromium } = require("playwright");
const BASE = process.env.CAM3D_URL ?? "http://127.0.0.1:8765";
const PID = process.env.CAM3D_PROJECT;
const SHOTS = process.env.CAM3D_SHOTS ?? path.resolve("tests/screenshots");
fs.mkdirSync(SHOTS, { recursive: true });

let failures = 0;
const step = async (name, fn) => {
  const t = Date.now();
  try { await fn(); console.log(`✔ ${name} (${((Date.now() - t) / 1000).toFixed(1)}s)`); }
  catch (e) { failures++; console.log(`✘ ${name}\n   ${String(e.message ?? e).split("\n")[0]}`); }
};
const expect = (c, m) => { if (!c) throw new Error(m); };
const project = async () => (await fetch(`${BASE}/api/projects/${PID}`)).json();
const waitIdle = async (page, timeout = 300000) => {
  const t = Date.now();
  for (;;) {
    const p = await project();
    if (!p.active_job) return p;
    if (Date.now() - t > timeout) throw new Error("traitement trop long");
    await page.waitForTimeout(1000);
  }
};

const browser = await chromium.launch({ args: ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"] });
const ctx = await browser.newContext({ viewport: { width: 1440, height: 950 }, acceptDownloads: true });
const page = await ctx.newPage();
const errors = [];
page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });

const canvas = () => page.locator('[data-testid="viewer"] canvas').first();
async function pickTwo() {
  const box = await canvas().boundingBox();
  const cx = box.x + box.width / 2, cy = box.y + box.height / 2;
  const tries = [[0, 0], [90, 10], [-90, 10], [60, -40], [-60, 40], [120, 30], [-120, -20], [30, 60]];
  for (const [dx, dy] of tries) {
    await page.mouse.click(cx + dx, cy + dy);
    await page.waitForTimeout(250);
    if (await page.getByText("Deux points choisis").count()) return;
  }
  throw new Error("impossible de toucher le modèle deux fois");
}

let facesBefore = 0;

await step("onglet Modèle 3D : visualiseur et panneau d'édition", async () => {
  const p = await project();
  facesBefore = p.model_faces;
  expect(p.edits.length === 0, "le projet a déjà des modifications");
  await page.goto(`${BASE}/project/?id=${PID}&tab=model`);
  await page.locator('[data-testid="viewer-faces"]').waitFor({ timeout: 60000 });
  await page.waitForFunction(() => !document.body.innerText.includes("Chargement"), null, { timeout: 60000 });
  await page.locator('[data-testid="calibration-status"]', { hasText: "Non étalonné" }).waitFor();
});

await step("mesure non étalonnée : affichée comme relative", async () => {
  await page.locator('[data-testid="tool-measure"]').click();
  await pickTwo();
  const v = await page.locator('[data-testid="measure-value"]').innerText();
  expect(/u \(non étalonné\)$/.test(v), `valeur: ${v}`);
  await page.screenshot({ path: path.join(SHOTS, "30-mesure-non-etalonnee.png") });
});

await step("étalonnage manuel (2 points + 1000 cm)", async () => {
  await page.locator('[data-testid="tool-calibrate"]').click();
  await pickTwo();
  await page.locator('[data-testid="calibration-distance"]').fill("1000");
  await page.getByRole("button", { name: "Enregistrer l’étalonnage" }).click();
  await page.locator('[data-testid="calibration-status"]', { hasText: "Étalonné manuellement" }).waitFor({ timeout: 15000 });
  const p = await project();
  expect(p.calibration?.method === "manual" && p.calibration.unit === "cm", "étalonnage absent");
  await page.locator('[data-testid="tool-measure"]').click();
  await pickTwo();
  const v = await page.locator('[data-testid="measure-value"]').innerText();
  expect(/ cm$/.test(v), `mesure étalonnée: ${v}`);
  await page.locator('[data-testid="tool-measure"]').click(); // off
});

await step("découpe par boîte : modèle réduit, original conservé", async () => {
  await page.locator('[data-testid="tool-crop"]').click();
  await page.locator('[data-testid="crop-panel"]').waitFor();
  const ymax = page.getByLabel("y maximum");
  await ymax.focus();
  for (let i = 0; i < 40; i++) await ymax.press("ArrowLeft");
  await page.screenshot({ path: path.join(SHOTS, "31-decoupe-boite.png") });
  await page.locator('[data-testid="apply-crop"]').click();
  const p = await waitIdle(page);
  expect(p.edits.length === 1 && p.edits[0].type === "crop_box", "découpe non enregistrée");
  expect(p.model_faces < facesBefore, `faces ${p.model_faces} >= ${facesBefore}`);
  await page.locator('[data-testid="edit-history"] li').first().waitFor();
});

await step("effacement d'une zone dessinée à l'écran", async () => {
  const before = (await project()).model_faces;
  await page.locator('[data-testid="viewer-faces"]').waitFor();
  await page.waitForTimeout(1500);
  await page.locator('[data-testid="tool-erase"]').click();
  const box = await canvas().boundingBox();
  await page.mouse.move(box.x + box.width * 0.30, box.y + box.height * 0.35);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width * 0.45, box.y + box.height * 0.6, { steps: 8 });
  await page.mouse.up();
  await page.locator('[data-testid="apply-erase"]').waitFor({ timeout: 10000 });
  await page.screenshot({ path: path.join(SHOTS, "32-zone-a-effacer.png") });
  await page.locator('[data-testid="apply-erase"]').click();
  const p = await waitIdle(page);
  expect(p.edits.length === 2 && p.model_faces < before, `faces ${p.model_faces} vs ${before}`);
});

await step("rotation 90° puis annulation", async () => {
  await page.locator('[data-testid="tool-rotate-y"]').click();
  let p = await waitIdle(page);
  expect(p.edits.length === 3 && p.edits[2].type === "rotate", "rotation absente");
  await page.locator('[data-testid="undo"]').click();
  await page.waitForTimeout(500);
  p = await waitIdle(page);
  expect(p.edits.length === 2, `historique: ${p.edits.length}`);
  await page.waitForTimeout(1500);
  await canvas().screenshot({ path: path.join(SHOTS, "33-apres-edition.png") });
  // the edited preview must still carry its photographic texture (glTF JSON chunk lists an image)
  const glb = Buffer.from(await (await fetch(`${BASE}/api/projects/${PID}/preview.glb`)).arrayBuffer());
  const jsonLen = glb.readUInt32LE(12);
  const gltf = JSON.parse(glb.subarray(20, 20 + jsonLen).toString());
  expect((gltf.images ?? []).length > 0 && (gltf.textures ?? []).length > 0, "aperçu édité sans texture");
});

await step("export SketchUp « Léger » : vérifié, étalonné, téléchargé", async () => {
  await page.getByRole("tab", { name: "Exports" }).click();
  await page.locator('[data-testid="export-scale"]', { hasText: "étalonnée" }).waitFor();
  await page.locator('[data-testid="sketchup-light"]').click();
  await page.locator('[data-testid="download-sketchup-light"]').waitFor({ timeout: 600000 });
  const [dl] = await Promise.all([page.waitForEvent("download"), page.locator('[data-testid="download-sketchup-light"]').click()]);
  const f = path.join(SHOTS, "model_sketchup_light.zip");
  await dl.saveAs(f);
  const buf = fs.readFileSync(f);
  expect(buf.subarray(0, 2).toString() === "PK" && buf.includes(Buffer.from("model_sketchup_light.dae")) && buf.includes(Buffer.from("textures/")), "zip invalide");
  const ex = await (await fetch(`${BASE}/api/projects/${PID}/exports`)).json();
  const su = ex.find((e) => e.file === "model_sketchup_light.zip");
  expect(su && /Vérification automatique : OK/.test(su.note) && /mètres \(étalonné\)/.test(su.note), `note: ${su?.note}`);
  await page.screenshot({ path: path.join(SHOTS, "34-export-sketchup.png") });
});

await step("aucune erreur console", async () => { expect(errors.length === 0, errors.slice(0, 3).join(" | ")); });

await browser.close();
console.log(failures ? `\n${failures} échec(s)` : "\nTous les scénarios ont réussi.");
process.exit(failures ? 1 : 0);
