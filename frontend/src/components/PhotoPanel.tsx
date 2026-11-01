"use client";
import { useRef, useState } from "react";
import { api, uploadPhotos, url } from "@/lib/api";
import { formatBytes } from "@/lib/format";
import type { ProjectDetail } from "@/lib/types";
import { IconAlert, IconImages, IconTrash, IconUpload } from "./Icons";
import { ErrorBox } from "./ui";

const TIPS = [
  "Tournez lentement autour de l’objet, en gardant toujours une partie commune entre deux photos (60 à 80 %).",
  "Faites 2 ou 3 tours à des hauteurs différentes, puis quelques vues du dessus.",
  "Évitez le flou de bougé : lumière suffisante, mouvements lents.",
  "Évitez les reflets forts, les surfaces transparentes et les fonds uniformes.",
  "Pensez aux zones cachées (dessous, creux) si vous voulez les obtenir.",
  "20 photos minimum recommandées ; 40 à 80 pour un bon résultat.",
];

export function PhotoPanel({ project, locked, onChange }: { project: ProjectDetail; locked: boolean; onChange: () => void }) {
  const input = useRef<HTMLInputElement>(null);
  const [progress, setProgress] = useState<number | null>(null);
  const [report, setReport] = useState<{ added: number; rejected: { file: string; error: string }[] } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [drag, setDrag] = useState(false);

  async function upload(files: File[]) {
    if (!files.length || locked) return;
    setError(null); setReport(null); setProgress(0);
    try {
      const r = await uploadPhotos(project.id, files, setProgress);
      setReport({ added: r.added.length, rejected: r.rejected ?? [] });
      onChange();
    } catch (e: any) { setError(e.message); }
    setProgress(null);
  }

  async function remove(name: string) {
    try { await api.deletePhoto(project.id, name); onChange(); } catch (e: any) { setError(e.message); }
  }

  const warned = project.photos.filter((p) => p.warnings.length).length;

  return (
    <div className="grid gap-6 lg:grid-cols-[1fr_300px]">
      <div className="space-y-4">
        <div
          onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
          onDragLeave={() => setDrag(false)}
          onDrop={(e) => { e.preventDefault(); setDrag(false); upload(Array.from(e.dataTransfer.files).filter((f) => f.type.startsWith("image/") || /\.(heic|heif)$/i.test(f.name))); }}
          className={`card flex flex-col items-center gap-3 border-dashed px-6 py-8 text-center transition-colors ${drag ? "border-accent bg-accent/5" : ""}`}
        >
          <IconUpload className="h-7 w-7 text-accent" />
          <p className="text-sm text-muted">Glissez vos photos ici ou</p>
          <input ref={input} type="file" accept="image/*,.heic,.heif" multiple hidden data-testid="photo-input"
            onChange={(e) => { upload(Array.from(e.target.files ?? [])); e.target.value = ""; }} />
          <button className="btn-primary" disabled={locked || progress !== null} onClick={() => input.current?.click()}>
            <IconImages className="h-4 w-4" /> Choisir des photos
          </button>
          {locked && <p className="text-xs text-warn">Traitement en cours : les photos ne peuvent pas être modifiées.</p>}
          {progress !== null && (
            <div className="w-full max-w-sm">
              <div className="h-1.5 overflow-hidden rounded-full bg-white/10"><div className="h-full bg-accent transition-[width]" style={{ width: `${Math.round(progress * 100)}%` }} /></div>
              <p className="mt-1.5 text-xs text-muted">Transfert {Math.round(progress * 100)} %{progress >= 1 ? " — vérification des images…" : ""}</p>
            </div>
          )}
        </div>
        {error && <ErrorBox>{error}</ErrorBox>}
        {report && (
          <div className="card space-y-1 p-4 text-sm" data-testid="upload-report">
            <p>{report.added} photo{report.added > 1 ? "s" : ""} ajoutée{report.added > 1 ? "s" : ""}.</p>
            {report.rejected.map((r) => <p key={r.file} className="text-danger">{r.file} : {r.error}</p>)}
          </div>
        )}

        <div className="flex items-center justify-between">
          <h3 className="font-medium">{project.photo_count} photo{project.photo_count > 1 ? "s" : ""}</h3>
          {warned > 0 && <span className="chip bg-warn/10 text-warn"><IconAlert className="h-3.5 w-3.5" />{warned} à vérifier</span>}
        </div>
        <div className="grid grid-cols-3 gap-2 sm:grid-cols-4 md:grid-cols-6" data-testid="photo-grid">
          {project.photos.map((ph) => (
            <figure key={ph.name} className="group relative aspect-square overflow-hidden rounded-xl bg-surface-2">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={url(`/api/projects/${project.id}/photos/${encodeURIComponent(ph.name)}?thumb=true`)} alt={ph.name} loading="lazy" className="h-full w-full object-cover" />
              {ph.warnings.length > 0 && (
                <span className="chip absolute left-1.5 top-1.5 bg-black/70 text-warn" title={`Netteté ${ph.sharpness}, luminosité ${ph.brightness}`}>{ph.warnings.join(", ")}</span>
              )}
              {!locked && (
                <button onClick={() => remove(ph.name)} aria-label={`Supprimer ${ph.name}`}
                  className="absolute right-1.5 top-1.5 grid h-7 w-7 place-items-center rounded-lg bg-black/60 text-text opacity-100 transition-opacity sm:opacity-0 sm:group-hover:opacity-100">
                  <IconTrash className="h-4 w-4" />
                </button>
              )}
              <figcaption className="absolute inset-x-0 bottom-0 truncate bg-gradient-to-t from-black/70 px-1.5 pb-1 pt-4 text-[10px] text-muted">{ph.width}×{ph.height} · {formatBytes(ph.size_bytes)}</figcaption>
            </figure>
          ))}
        </div>
      </div>
      <aside className="card h-fit space-y-3 p-5">
        <h3 className="font-medium">Conseils de prise de vue</h3>
        <ul className="space-y-2 text-sm text-muted">
          {TIPS.map((t) => <li key={t} className="flex gap-2"><span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-accent" />{t}</li>)}
        </ul>
        <p className="text-xs text-faint">Les photos floues, trop sombres ou surexposées sont signalées ; elles sont écartées automatiquement lors de la reconstruction.</p>
      </aside>
    </div>
  );
}
