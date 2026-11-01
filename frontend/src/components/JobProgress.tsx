"use client";
import { useEffect, useMemo, useState } from "react";
import { failureAdvice, formatDuration, reduceStages } from "@/lib/format";
import { useApp } from "@/lib/store";
import type { Job } from "@/lib/types";
import { IconCheck, IconX } from "./Icons";
import { ErrorBox, Spinner } from "./ui";

export function JobProgress({ job }: { job: Job }) {
  const live = useApp((s) => s.jobEvents[job.id]);
  const seed = useApp((s) => s.seedEvents);
  useEffect(() => { if (job.events?.length) seed(job.id, job.events); }, [job.id, job.events, seed]);
  const events = live?.length ? live : job.events ?? [];
  const stages = useMemo(() => reduceStages(events), [events]);
  const [now, setNow] = useState(Date.now() / 1000);
  const active = job.status === "running" || job.status === "queued";
  useEffect(() => {
    if (!active) return;
    const t = setInterval(() => setNow(Date.now() / 1000), 1000);
    return () => clearInterval(t);
  }, [active]);
  const elapsed = job.started_at ? (job.finished_at ?? now) - job.started_at : null;
  const shown = stages.filter((s) => !(job.kind === "export" && s.id !== "export"));

  return (
    <div className="space-y-4" data-testid="job-progress">
      <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
        <span className="text-muted">
          {job.status === "queued" ? `En file d’attente${job.queue_position ? ` (position ${job.queue_position})` : ""}` :
            job.status === "running" ? "Traitement en cours" :
              job.status === "succeeded" ? "Terminé" : job.status === "cancelled" ? "Annulé" :
                job.status === "interrupted" ? "Interrompu" : "Échec"}
          {job.profile && job.kind === "reconstruct" ? ` · profil ${job.profile === "fast" ? "Rapide" : job.profile === "high" ? "Haute qualité" : "Ultra"}` : ""}
        </span>
        {elapsed != null && <span className="text-faint">Durée : {formatDuration(elapsed)}</span>}
      </div>
      <ol className="space-y-1.5">
        {shown.map((s) => (
          <li key={s.id} className={`rounded-xl border px-3.5 py-2.5 transition-colors ${s.status === "running" ? "border-accent/40 bg-accent/5" : "border-line"}`} data-stage={s.id} data-status={s.status}>
            <div className="flex items-center gap-3">
              <span className="grid h-6 w-6 shrink-0 place-items-center">
                {s.status === "finished" ? <IconCheck className="h-5 w-5 text-ok" /> :
                  s.status === "failed" ? <IconX className="h-5 w-5 text-danger" /> :
                    s.status === "running" ? <Spinner className="h-4 w-4 text-accent" /> :
                      <span className={`h-2 w-2 rounded-full ${s.status === "skipped" ? "bg-white/20" : "bg-white/10"}`} />}
              </span>
              <span className={`flex-1 text-sm ${s.status === "pending" || s.status === "skipped" ? "text-faint" : ""}`}>{s.label}{s.status === "skipped" ? " — ignoré" : ""}</span>
              {s.duration != null && <span className="text-xs text-faint">{formatDuration(s.duration)}</span>}
              {s.status === "running" && s.progress != null && <span className="text-xs tabular-nums text-accent">{Math.round(s.progress * 100)} %</span>}
            </div>
            {s.status === "running" && (
              <div className="ml-9 mt-2 space-y-1.5">
                {/* A bar only when the engine measured progress; otherwise an activity indicator. */}
                {s.progress != null ? (
                  <div className="h-1 overflow-hidden rounded-full bg-white/10"><div className="h-full bg-accent transition-[width] duration-500" style={{ width: `${s.progress * 100}%` }} /></div>
                ) : (
                  <div className="h-1 overflow-hidden rounded-full bg-white/10"><div className="h-full w-1/3 animate-[slide_1.4s_ease-in-out_infinite] rounded-full bg-accent/60" /></div>
                )}
                {s.message && <p className="truncate text-xs text-muted">{s.message}</p>}
              </div>
            )}
            {s.status === "finished" && s.message && <p className="ml-9 mt-0.5 truncate text-xs text-faint">{s.message}</p>}
          </li>
        ))}
      </ol>
      {job.status === "failed" && job.error && (
        <ErrorBox>
          <p className="font-medium">La reconstruction a échoué{job.error_stage ? ` à l’étape « ${stages.find((s) => s.id === job.error_stage)?.label ?? job.error_stage} »` : ""}.</p>
          {failureAdvice(job.error_stage, job.error) && <p className="mt-1 text-text/90">{failureAdvice(job.error_stage, job.error)}</p>}
          <details className="mt-2"><summary className="cursor-pointer text-xs">Détail technique</summary><pre className="mt-1 whitespace-pre-wrap text-xs opacity-80">{job.error}</pre></details>
        </ErrorBox>
      )}
    </div>
  );
}
