"use client";
import { useState } from "react";
import { api } from "@/lib/api";
import { EDIT_LABELS, formatMeasure, type LengthUnit } from "@/lib/format";
import { useApp } from "@/lib/store";
import type { ProjectDetail } from "@/lib/types";
import type { RegionSelection, Tool } from "./Viewer3D";
import { ErrorBox, Modal, Spinner } from "./ui";

export type PanelMode = "none" | "measure" | "calibrate" | "crop" | "erase";
type Vec = [number, number, number];

interface Props {
  project: ProjectDetail;
  mode: PanelMode;
  setMode: (m: PanelMode) => void;
  points: Vec[];
  setPoints: (p: Vec[]) => void;
  region: RegionSelection | null;
  bounds: { min: Vec; max: Vec } | null;
  crop: { min: Vec; max: Vec } | null;
  setCrop: (c: { min: Vec; max: Vec } | null) => void;
  onChange: () => void;
}

export function toolFor(mode: PanelMode): Tool {
  return mode === "measure" || mode === "calibrate" ? "pick" : mode === "erase" ? "erase" : "orbit";
}

const AXES = ["x", "y", "z"] as const;

export function EditPanel({ project, mode, setMode, points, setPoints, region, bounds, crop, setCrop, onChange }: Props) {
  const job = project.active_job;
  const editing = job?.kind === "edit";
  const busy = !!job;
  const live = useApp((s) => (job ? s.jobEvents[job.id] : undefined));
  const last = live?.[live.length - 1];
  const [error, setError] = useState<string | null>(null);
  const [unit, setUnit] = useState<LengthUnit>(project.calibration?.unit ?? "cm");
  const [calDistance, setCalDistance] = useState("");
  const [simplifyTarget, setSimplifyTarget] = useState(Math.min(150000, Math.round((project.model_faces ?? 200000) / 2)));
  const [confirmReset, setConfirmReset] = useState(false);
  const cal = project.calibration;
  const dist = points.length === 2 ? Math.hypot(points[0][0] - points[1][0], points[0][1] - points[1][1], points[0][2] - points[1][2]) : null;

  async function run(fn: () => Promise<unknown>) {
    setError(null);
    try { await fn(); onChange(); } catch (e: any) { setError(e.message); }
  }
  const start = (m: PanelMode) => { setPoints([]); setCrop(null); setMode(mode === m ? "none" : m); if (m === "crop" && bounds && mode !== "crop") setCrop(bounds); };

  return (
    <div className="space-y-4" data-testid="edit-panel">
      {/* --- scale status (never present an uncalibrated measure as real) */}
      <section className="card space-y-3 p-4">
        <div className="flex items-center justify-between">
          <h3 className="font-medium">Mesures</h3>
          <span data-testid="calibration-status" className={`chip ${cal ? "bg-ok/10 text-ok" : "bg-warn/10 text-warn"}`}>
            {cal ? (cal.method === "manual" ? "Étalonné manuellement" : "Étalonné avec une source de référence") : "Non étalonné"}
          </span>
        </div>
        {!cal && <p className="text-xs text-muted">Sans étalonnage, les distances sont relatives : ce ne sont pas des mesures réelles.</p>}
        <div className="flex flex-wrap gap-2">
          <button className={mode === "measure" ? "btn-primary" : "btn-ghost"} onClick={() => start("measure")} disabled={busy} data-testid="tool-measure">Mesurer</button>
          <button className={mode === "calibrate" ? "btn-primary" : "btn-ghost"} onClick={() => start("calibrate")} disabled={busy} data-testid="tool-calibrate">Étalonner</button>
          <select className="input w-auto py-2" value={unit} onChange={(e) => setUnit(e.target.value as LengthUnit)} aria-label="Unité">
            <option value="mm">mm</option><option value="cm">cm</option><option value="m">m</option>
          </select>
        </div>
        {(mode === "measure" || mode === "calibrate") && (
          <p className="text-xs text-accent">{points.length < 2 ? `Touchez le modèle : point ${points.length + 1} sur 2` : "Deux points choisis"}</p>
        )}
        {mode === "measure" && dist != null && (
          <p className="text-lg font-semibold tabular-nums" data-testid="measure-value">{formatMeasure(dist, cal?.metres_per_unit, unit)}</p>
        )}
        {mode === "calibrate" && dist != null && (
          <form className="space-y-2" onSubmit={(e) => { e.preventDefault(); const d = parseFloat(calDistance.replace(",", ".")); if (d > 0) run(async () => { await api.setCalibration(project.id, points[0], points[1], d, unit); setMode("none"); setPoints([]); }); }}>
            <label className="block text-xs text-muted">Distance réelle entre ces deux points ({unit})
              <input className="input mt-1" inputMode="decimal" value={calDistance} onChange={(e) => setCalDistance(e.target.value)} placeholder="ex. 120" data-testid="calibration-distance" autoFocus />
            </label>
            <button className="btn-primary w-full" disabled={!calDistance}>Enregistrer l’étalonnage</button>
          </form>
        )}
        {cal && <button className="text-xs text-muted underline" onClick={() => run(() => api.clearCalibration(project.id))}>Retirer l’étalonnage</button>}
      </section>

      {/* --- cleaning */}
      <section className="card space-y-3 p-4">
        <div className="flex items-center justify-between">
          <h3 className="font-medium">Nettoyage</h3>
          {editing && <span className="chip bg-accent/15 text-accent"><Spinner className="h-3 w-3" /> {last?.message?.slice(0, 40) || "Mise à jour…"}</span>}
        </div>
        <p className="text-xs text-muted">L’original reconstruit est conservé : chaque opération peut être annulée.</p>
        <div className="grid grid-cols-2 gap-2">
          <button className={mode === "crop" ? "btn-primary" : "btn-ghost"} onClick={() => start("crop")} disabled={busy || !bounds} data-testid="tool-crop">Découper</button>
          <button className={mode === "erase" ? "btn-primary" : "btn-ghost"} onClick={() => start("erase")} disabled={busy} data-testid="tool-erase">Effacer une zone</button>
          <button className="btn-ghost" disabled={busy} onClick={() => run(() => api.addEdit(project.id, { type: "remove_components", min_fraction: 0.05 }))} data-testid="tool-components">Parties isolées</button>
          <button className="btn-ghost" disabled={busy} onClick={() => run(() => api.addEdit(project.id, { type: "recenter" }))} data-testid="tool-recenter">Recentrer</button>
        </div>
        <div className="flex items-center gap-2 text-xs text-muted">
          Pivoter de 90° :
          {AXES.map((a) => <button key={a} className="btn-ghost px-3 py-1.5 uppercase" disabled={busy} onClick={() => run(() => api.addEdit(project.id, { type: "rotate", axis: a, degrees: 90 }))} data-testid={`tool-rotate-${a}`}>{a}</button>)}
        </div>

        {mode === "crop" && crop && bounds && (
          <div className="space-y-2 rounded-xl border border-line p-3" data-testid="crop-panel">
            <p className="text-xs text-muted">Ce qui est hors de la boîte bleue sera retiré.</p>
            {AXES.map((ax, i) => {
              const lo = bounds.min[i], hi = bounds.max[i];
              const step = (hi - lo) / 200 || 0.01;
              return (
                <div key={ax} className="grid grid-cols-[1.5rem_1fr_1fr] items-center gap-2 text-xs">
                  <span className="uppercase text-muted">{ax}</span>
                  <input type="range" min={lo} max={hi} step={step} value={crop.min[i]} aria-label={`${ax} minimum`}
                    onChange={(e) => { const v = Math.min(+e.target.value, crop.max[i] - step); const m = [...crop.min] as Vec; m[i] = v; setCrop({ ...crop, min: m }); }} />
                  <input type="range" min={lo} max={hi} step={step} value={crop.max[i]} aria-label={`${ax} maximum`}
                    onChange={(e) => { const v = Math.max(+e.target.value, crop.min[i] + step); const m = [...crop.max] as Vec; m[i] = v; setCrop({ ...crop, max: m }); }} />
                </div>
              );
            })}
            <button className="btn-primary w-full" data-testid="apply-crop" onClick={() => run(async () => { await api.addEdit(project.id, { type: "crop_box", min: crop.min, max: crop.max }); setMode("none"); setCrop(null); })}>Appliquer la découpe</button>
          </div>
        )}
        {mode === "erase" && (
          <div className="space-y-2 rounded-xl border border-line p-3 text-xs">
            <p className="text-muted">Tracez un rectangle sur le modèle : tout ce qui s’y trouve, à travers toute la profondeur, sera effacé. Pour changer de point de vue, désactivez l’outil, tournez le modèle, puis réactivez-le.</p>
            {region ? (
              <button className="btn-danger w-full" data-testid="apply-erase" onClick={() => run(async () => { await api.addEdit(project.id, { type: "delete_region", matrix: region.matrix, polygon: region.polygon }); setMode("none"); })}>
                Effacer la sélection ({region.count.toLocaleString("fr-FR")} faces de l’aperçu)
              </button>
            ) : <p className="text-faint">Aucune sélection.</p>}
          </div>
        )}

        <details className="rounded-xl border border-line p-3">
          <summary className="cursor-pointer text-sm">Simplifier le maillage</summary>
          <div className="mt-2 space-y-2 text-xs">
            <p className="text-muted">Le maillage est réduit puis <b>re-texturé à partir des photos</b> (nouvel atlas, sans déformation des textures existantes). Compter environ une minute.</p>
            <input type="number" className="input" min={1000} step={1000} value={simplifyTarget} onChange={(e) => setSimplifyTarget(+e.target.value)} aria-label="Nombre de faces cible" />
            <button className="btn-ghost w-full" disabled={busy || simplifyTarget < 1000 || simplifyTarget >= (project.model_faces ?? 0)}
              onClick={() => run(() => api.addEdit(project.id, { type: "simplify", target_faces: simplifyTarget }))} data-testid="tool-simplify">
              Simplifier à {simplifyTarget.toLocaleString("fr-FR")} faces
            </button>
          </div>
        </details>

        {project.edits.length > 0 && (
          <div className="space-y-2 border-t border-line pt-3">
            <ol className="space-y-1 text-xs text-muted" data-testid="edit-history">
              {project.edits.map((op, i) => <li key={i}>{i + 1}. {EDIT_LABELS[op.type] ?? op.type}{op.type === "simplify" ? ` (${op.target_faces.toLocaleString("fr-FR")} faces)` : op.type === "rotate" ? ` ${op.axis.toUpperCase()} ${op.degrees}°` : ""}</li>)}
            </ol>
            <div className="flex gap-2">
              <button className="btn-ghost flex-1" disabled={busy} onClick={() => run(() => api.undoEdit(project.id))} data-testid="undo">Annuler la dernière</button>
              <button className="btn-ghost flex-1" disabled={busy} onClick={() => setConfirmReset(true)}>Revenir à l’original</button>
            </div>
          </div>
        )}
        {error && <ErrorBox>{error}</ErrorBox>}
      </section>

      <Modal open={confirmReset} onClose={() => setConfirmReset(false)} title="Revenir à l’original ?">
        <p className="text-sm text-muted">Les {project.edits.length} modification(s) seront retirées et le modèle reconstruit sera restauré. Les exports seront à régénérer.</p>
        <div className="mt-4 flex justify-end gap-2">
          <button className="btn-ghost" onClick={() => setConfirmReset(false)}>Annuler</button>
          <button className="btn-primary" onClick={() => { setConfirmReset(false); run(() => api.resetEdits(project.id)); }}>Restaurer</button>
        </div>
      </Modal>
    </div>
  );
}
