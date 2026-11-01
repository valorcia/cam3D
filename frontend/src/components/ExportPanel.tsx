"use client";
import { useState } from "react";
import { api, url } from "@/lib/api";
import { formatBytes } from "@/lib/format";
import type { ProjectDetail } from "@/lib/types";
import { IconDownload } from "./Icons";
import { ErrorBox, Spinner } from "./ui";

const SKETCHUP: { id: "light" | "standard" | "detailed"; title: string; text: string }[] = [
  { id: "light", title: "Léger", text: "≤ 50 000 faces, fluide sur tout ordinateur" },
  { id: "standard", title: "Standard", text: "≤ 150 000 faces, bon compromis" },
  { id: "detailed", title: "Détaillé", text: "≤ 400 000 faces, ordinateur récent" },
];

const FORMATS: { id: string; title: string; text: string; file: string }[] = [
  { id: "dae", title: "DAE complet", text: "COLLADA + textures dans un ZIP, tous les polygones. À importer via Fichier › Importer.", file: "model_dae.zip" },
  { id: "obj", title: "OBJ", text: "OBJ + MTL + textures dans un ZIP. Blender, 3ds Max, Rhino…", file: "model_obj.zip" },
  { id: "glb", title: "GLB", text: "glTF binaire, textures intégrées. Web, Blender, visionneuses.", file: "model.glb" },
  { id: "stl", title: "STL", text: "Géométrie seule, pour l’impression 3D. Les textures photographiques ne sont pas conservées.", file: "model.stl" },
  { id: "ply", title: "PLY", text: "Maillage sans texture + nuage de points dense (fichier séparé).", file: "model.ply" },
];

export function ExportPanel({ project, onChange }: { project: ProjectDetail; onChange: () => void }) {
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const files = new Map(project.exports.map((e) => [e.file, e]));
  const exporting = project.active_job?.kind === "export";

  async function make(fmt: string) {
    setBusy(fmt); setError(null);
    try { await api.requestExport(project.id, [fmt]); onChange(); } catch (e: any) { setError(e.message); }
    setBusy(null);
  }

  if (!project.has_model) {
    return <div className="card p-6 text-sm text-muted">Les exports seront disponibles après la reconstruction du modèle.</div>;
  }
  return (
    <div className="space-y-4">
      {project.calibration ? (
        <div className="card border-ok/30 bg-ok/5 p-4 text-sm text-ok" data-testid="export-scale">Échelle étalonnée : les exports sont en mètres.</div>
      ) : (
        <div className="card border-warn/30 bg-warn/5 p-4 text-sm text-warn" data-testid="export-scale">
          Échelle non étalonnée : les dimensions sont relatives. Étalonnez dans l’onglet Modèle 3D (deux points + distance connue) avant un usage métrique.
        </div>
      )}
      <section className="card space-y-3 p-4" data-testid="sketchup-profile">
        <div>
          <h3 className="font-medium">Export SketchUp</h3>
          <p className="mt-1 text-xs text-muted">Échelle appliquée, axes de SketchUp (Z en haut, murs alignés), nombre de faces réduit puis textures re-projetées depuis les photos, DAE + textures en ZIP, fichier vérifié automatiquement.</p>
        </div>
        <div className="grid gap-2 sm:grid-cols-3">
          {SKETCHUP.map((l) => {
            const ready = files.get(`model_sketchup_${l.id}.zip`);
            const running = project.active_job?.kind === "sketchup" && project.active_job.params?.level === l.id;
            return (
              <div key={l.id} className="rounded-xl border border-line p-3">
                <p className="text-sm font-medium">{l.title}</p>
                <p className="mb-2 text-xs text-muted">{l.text}</p>
                {ready ? (
                  <a className="btn-primary w-full" href={url(`/api/projects/${project.id}/exports/${ready.file}`)} download data-testid={`download-sketchup-${l.id}`}>
                    <IconDownload className="h-4 w-4" /> {formatBytes(ready.size_bytes)}
                  </a>
                ) : (
                  <button className="btn-ghost w-full" disabled={!!project.active_job || !!busy} data-testid={`sketchup-${l.id}`}
                    onClick={async () => { setBusy(l.id); setError(null); try { await api.sketchupExport(project.id, l.id); onChange(); } catch (e: any) { setError(e.message); } setBusy(null); }}>
                    {running ? <><Spinner /> Préparation…</> : "Générer"}
                  </button>
                )}
              </div>
            );
          })}
        </div>
      </section>
      {error && <ErrorBox>{error}</ErrorBox>}
      <div className="grid gap-3 sm:grid-cols-2">
        {FORMATS.map((f) => {
          const ready = files.get(f.file);
          return (
            <div key={f.id} className="card flex flex-col gap-3 p-4" data-testid={`export-${f.id}`}>
              <div>
                <h3 className="font-medium">{f.title}</h3>
                <p className="mt-1 text-xs text-muted">{f.text}</p>
              </div>
              <div className="mt-auto flex items-center gap-2">
                {ready ? (
                  <a className="btn-primary" href={url(`/api/projects/${project.id}/exports/${ready.file}`)} download data-testid={`download-${f.id}`}>
                    <IconDownload className="h-4 w-4" /> Télécharger · {formatBytes(ready.size_bytes)}
                  </a>
                ) : (
                  <button className="btn-ghost" onClick={() => make(f.id)} disabled={!!busy || exporting || !!project.active_job}>
                    {busy === f.id || (exporting && project.active_job?.formats.includes(f.id)) ? <><Spinner /> Génération…</> : "Générer"}
                  </button>
                )}
              </div>
            </div>
          );
        })}
      </div>
      <p className="text-xs text-faint">Fichiers DAE vérifiés automatiquement et par l’import dans Blender ; l’import dans SketchUp reste à valider sur une installation réelle.</p>
    </div>
  );
}
