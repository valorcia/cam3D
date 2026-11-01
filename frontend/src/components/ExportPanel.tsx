"use client";
import { useState } from "react";
import { api, url } from "@/lib/api";
import { formatBytes } from "@/lib/format";
import type { ProjectDetail } from "@/lib/types";
import { IconDownload } from "./Icons";
import { ErrorBox, Spinner } from "./ui";

const FORMATS: { id: string; title: string; text: string; file: string }[] = [
  { id: "dae", title: "SketchUp (DAE)", text: "COLLADA + textures dans un ZIP. Axe Z vers le haut, mètres. À importer via Fichier › Importer.", file: "model_dae.zip" },
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
      <div className="card border-warn/30 bg-warn/5 p-4 text-sm text-warn">
        Échelle non étalonnée : les dimensions du modèle sont relatives. L’outil d’étalonnage (deux points + distance connue) arrive dans une prochaine version ; d’ici là, mettez à l’échelle dans SketchUp avec l’outil Mètre.
      </div>
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
      <p className="text-xs text-faint">La compatibilité SketchUp est vérifiée par l’import dans Blender ; elle reste à valider sur une installation de SketchUp.</p>
    </div>
  );
}
