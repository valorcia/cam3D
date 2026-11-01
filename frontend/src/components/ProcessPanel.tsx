"use client";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { formatDuration } from "@/lib/format";
import { useApp } from "@/lib/store";
import type { Job, ProjectDetail } from "@/lib/types";
import { IconPlay, IconRefresh, IconX } from "./Icons";
import { JobProgress } from "./JobProgress";
import { LogViewer } from "./LogViewer";
import { ErrorBox } from "./ui";

export function ProcessPanel({ project, onChange, onShowModel }: { project: ProjectDetail; onChange: () => void; onShowModel?: () => void }) {
  const { system, revision } = useApp();
  const [profile, setProfile] = useState(project.profile ?? "fast");
  const [jobs, setJobs] = useState<Job[]>([]);
  const [detail, setDetail] = useState<Job | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.projectJobs(project.id).then((js) => {
      const rec = js.filter((j) => j.kind === "reconstruct");
      setJobs(rec);
      const current = rec[0];
      if (current) api.job(current.id).then(setDetail).catch(() => undefined); else setDetail(null);
    }).catch((e) => setError(e.message));
  }, [project.id, revision, project.status]);

  const active = detail && (detail.status === "running" || detail.status === "queued");

  async function start(resume = false) {
    setBusy(true); setError(null);
    try { await api.reconstruct(project.id, profile, ["obj", "glb", "dae"], resume); onChange(); }
    catch (e: any) { setError(e.message); }
    setBusy(false);
  }

  const canStart = project.photo_count >= 3 && system?.reconstruction_available !== false;

  return (
    <div className="grid gap-6 lg:grid-cols-[1fr_380px]">
      <div className="space-y-4">
        {detail ? (
          <div className="card p-5"><JobProgress job={detail} /></div>
        ) : (
          <div className="card p-6 text-sm text-muted">Aucune reconstruction lancée pour ce projet.</div>
        )}
        {detail?.status === "succeeded" && project.has_model && (
          <div className="card flex flex-wrap items-center justify-between gap-3 border-ok/30 bg-ok/5 p-4" data-testid="job-success">
            <span className="text-sm">Modèle reconstruit : {project.model_faces?.toLocaleString("fr-FR")} faces.</span>
            <button className="btn-primary" onClick={onShowModel}>Voir le modèle 3D</button>
          </div>
        )}
        {active && (
          <button className="btn-danger" onClick={() => detail && api.cancelJob(detail.id).then(onChange).catch((e) => setError(e.message))} data-testid="cancel-job">
            <IconX className="h-4 w-4" /> Annuler le traitement
          </button>
        )}
        {detail && !active && detail.status !== "succeeded" && (
          <button className="btn-ghost" onClick={() => api.retryJob(detail.id).then(onChange).catch((e) => setError(e.message))}>
            <IconRefresh className="h-4 w-4" /> Relancer (reprend les étapes déjà terminées)
          </button>
        )}
        {error && <ErrorBox>{error}</ErrorBox>}
        <details className="card p-5">
          <summary className="cursor-pointer text-sm font-medium">Journaux techniques</summary>
          <div className="mt-4"><LogViewer projectId={project.id} refresh={revision} /></div>
        </details>
        {jobs.length > 1 && (
          <div className="card p-5">
            <h3 className="mb-2 text-sm font-medium">Historique</h3>
            <ul className="space-y-1 text-xs text-muted">
              {jobs.map((j) => <li key={j.id}>{new Date(j.created_at * 1000).toLocaleString("fr-FR")} · {j.profile} · {j.status}{j.duration_s ? ` · ${formatDuration(j.duration_s)}` : ""}</li>)}
            </ul>
          </div>
        )}
      </div>

      <aside className="card h-fit space-y-4 p-5">
        <h3 className="font-medium">Qualité</h3>
        <div className="space-y-2" role="radiogroup" aria-label="Profil de qualité">
          {(system?.profiles ?? [{ name: "fast", label: "Rapide", description: "" }, { name: "high", label: "Haute qualité", description: "" }, { name: "ultra", label: "Ultra", description: "" }]).map((p) => {
            const est = project.estimates?.[p.name];
            return (
              <label key={p.name} className={`flex cursor-pointer gap-3 rounded-xl border p-3 transition-colors ${profile === p.name ? "border-accent/60 bg-accent/5" : "border-line hover:border-line-strong"}`}>
                <input type="radio" name="profile" value={p.name} checked={profile === p.name} onChange={() => setProfile(p.name)} className="mt-1 accent-[#5b8cff]" disabled={!!active} />
                <span>
                  <span className="block text-sm font-medium">{p.label}</span>
                  <span className="block text-xs text-muted">{p.description}</span>
                  {/* Duration only when measured on this computer. */}
                  {est && <span className="mt-1 block text-xs text-accent">≈ {formatDuration(est.seconds)} d’après {est.based_on_runs} reconstruction{est.based_on_runs > 1 ? "s" : ""} sur cet ordinateur</span>}
                </span>
              </label>
            );
          })}
        </div>
        {project.photo_count < 3 && <p className="text-xs text-warn">Ajoutez au moins 3 photos (20 à 80 recommandées).</p>}
        <button className="btn-primary w-full" disabled={!canStart || !!active || busy} onClick={() => start(false)} data-testid="start-reconstruction">
          <IconPlay className="h-4 w-4" /> {project.has_model ? "Reconstruire à nouveau" : "Lancer la reconstruction"}
        </button>
        <p className="text-xs text-faint">Tout le calcul se fait sur cet ordinateur. Aucune photo n’est envoyée sur Internet.</p>
      </aside>
    </div>
  );
}
