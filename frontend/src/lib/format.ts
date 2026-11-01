import type { JobEvent, StageId, StageStatus } from "./types";

export function formatBytes(n: number | null | undefined): string {
  if (n == null) return "—";
  if (n < 1024) return `${n} o`;
  const units = ["Ko", "Mo", "Go", "To"];
  let v = n / 1024;
  let i = 0;
  while (v >= 1024 && i < units.length - 1) { v /= 1024; i++; }
  return `${v.toLocaleString("fr-FR", { maximumFractionDigits: v < 10 ? 1 : 0 })} ${units[i]}`;
}

export function formatDuration(s: number | null | undefined): string {
  if (s == null) return "—";
  s = Math.round(s);
  if (s < 60) return `${s} s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m} min ${String(s % 60).padStart(2, "0")} s`;
  return `${Math.floor(m / 60)} h ${String(m % 60).padStart(2, "0")} min`;
}

export function formatDate(ts: number): string {
  return new Date(ts * 1000).toLocaleString("fr-FR", { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });
}

export function formatCount(n: number | null | undefined): string {
  return n == null ? "—" : n.toLocaleString("fr-FR");
}

export const STAGE_ORDER: StageId[] = ["prepare", "sfm", "dense", "mesh", "refine", "texture", "cleanup", "export"];

export const STAGE_LABELS: Record<StageId, string> = {
  prepare: "Préparation",
  sfm: "Analyse des images",
  dense: "Reconstruction dense",
  mesh: "Maillage",
  refine: "Raffinement",
  texture: "Texturage",
  cleanup: "Optimisation",
  export: "Exportation",
};

export interface StageView {
  id: StageId;
  label: string;
  status: StageStatus;
  message: string;
  /** Only set when the engine measured it (never invented). */
  progress: number | null;
  duration: number | null;
}

/** Fold a stream of job events into a per-stage view. Pure: unit-tested. */
export function reduceStages(events: Pick<JobEvent, "stage" | "status" | "message" | "progress" | "detail">[]): StageView[] {
  const map = new Map<StageId, StageView>(
    STAGE_ORDER.map((id) => [id, { id, label: STAGE_LABELS[id], status: "pending", message: "", progress: null, duration: null }]),
  );
  for (const e of events) {
    const s = map.get(e.stage);
    if (!s) continue;
    switch (e.status) {
      case "started":
        s.status = "running"; s.message = e.message; s.progress = null; break;
      case "progress":
        s.status = "running"; if (e.progress != null) s.progress = e.progress; if (e.message) s.message = e.message; break;
      case "log":
        if (s.status === "pending") s.status = "running";
        s.message = e.message; break;
      case "finished":
        s.status = "finished"; s.message = e.message; s.progress = null;
        s.duration = typeof e.detail?.duration === "number" ? (e.detail.duration as number) : null; break;
      case "failed":
        s.status = "failed"; s.message = e.message; s.progress = null; break;
      case "skipped":
        s.status = "skipped"; s.message = e.message; break;
    }
  }
  return STAGE_ORDER.map((id) => map.get(id)!);
}

export const PROJECT_STATUS_LABEL: Record<string, string> = {
  empty: "Sans photo",
  ready: "Prêt",
  queued: "En file d'attente",
  processing: "Reconstruction…",
  done: "Modèle prêt",
  failed: "Échec",
  cancelled: "Annulé",
  interrupted: "Interrompu",
};

/** Human advice for common failures (shown under the raw error). */
export function failureAdvice(stage: string | null, error: string | null): string | null {
  const e = (error ?? "").toLowerCase();
  if (stage === "sfm" || e.includes("caméra")) {
    return "Les photos ne se recouvrent pas assez. Reprenez la capture en tournant lentement autour de l'objet, avec 60 à 80 % de recouvrement entre deux photos et sans zones floues.";
  }
  if (stage === "dense" && e.includes("pauvre")) {
    return "L'objet manque de texture visible (surface unie, brillante ou transparente). Ajoutez des repères visuels autour ou photographiez avec une lumière diffuse.";
  }
  if (e.includes("annul")) return null;
  if (e.includes("mémoire") || e.includes("memory") || e.includes("killed")) {
    return "Mémoire insuffisante : essayez le profil Rapide ou moins de photos.";
  }
  return null;
}

export type LengthUnit = "mm" | "cm" | "m";
const PER_M: Record<LengthUnit, number> = { mm: 1000, cm: 100, m: 1 };

/** A measured distance: real units only when calibrated, otherwise explicitly relative. */
export function formatMeasure(modelDistance: number, metresPerUnit: number | null | undefined, unit: LengthUnit = "m"): string {
  if (!metresPerUnit) return `${modelDistance.toLocaleString("fr-FR", { maximumFractionDigits: 3 })} u (non étalonné)`;
  const v = modelDistance * metresPerUnit * PER_M[unit];
  return `${v.toLocaleString("fr-FR", { maximumFractionDigits: unit === "mm" ? 0 : unit === "cm" ? 1 : 3 })} ${unit}`;
}

export const EDIT_LABELS: Record<string, string> = {
  crop_box: "Découpe (boîte)",
  delete_region: "Zone effacée",
  remove_components: "Parties isolées supprimées",
  rotate: "Rotation",
  recenter: "Recentrage",
  simplify: "Simplification",
};
