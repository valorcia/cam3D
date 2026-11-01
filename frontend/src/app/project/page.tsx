"use client";
import dynamic from "next/dynamic";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useState } from "react";
import { ExportPanel } from "@/components/ExportPanel";
import { IconBack } from "@/components/Icons";
import { PhotoPanel } from "@/components/PhotoPanel";
import { ProcessPanel } from "@/components/ProcessPanel";
import { ErrorBox, Spinner, StatusBadge } from "@/components/ui";
import { api, url } from "@/lib/api";
import { formatBytes, formatCount, formatDate } from "@/lib/format";
import { useApp } from "@/lib/store";
import type { ProjectDetail } from "@/lib/types";

const Viewer3D = dynamic(() => import("@/components/Viewer3D"), {
  ssr: false,
  loading: () => <div className="grid h-[62dvh] place-items-center rounded-2xl border border-line text-sm text-muted"><Spinner /></div>,
});

const TABS = [
  { id: "photos", label: "Photos" },
  { id: "process", label: "Reconstruction" },
  { id: "model", label: "Modèle 3D" },
  { id: "exports", label: "Exports" },
] as const;
type Tab = (typeof TABS)[number]["id"];

function ProjectView() {
  const params = useSearchParams();
  const router = useRouter();
  const id = params.get("id") ?? "";
  const tab = (params.get("tab") as Tab) || "photos";
  const { whoami, revision } = useApp();
  const [p, setP] = useState<ProjectDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState("");
  const [tick, setTick] = useState(0);
  const refresh = useCallback(() => setTick((t) => t + 1), []);

  useEffect(() => {
    if (!whoami || !id) return;
    api.project(id).then((d) => { setP(d); setName(d.name); setError(null); }).catch((e) => setError(e.message));
  }, [whoami, id, revision, tick]);

  const go = (t: Tab) => router.replace(`/project/?id=${id}&tab=${t}`, { scroll: false });

  if (error) return <ErrorBox>{error} <Link href="/projects/" className="underline">Retour aux projets</Link></ErrorBox>;
  if (!p) return <div className="flex items-center gap-2 text-sm text-muted"><Spinner /> Chargement…</div>;
  const locked = p.status === "queued" || p.status === "processing";
  // a video extraction job also refreshes the photo list when it finishes (revision bump)

  return (
    <div className="space-y-6">
      <div className="space-y-3">
        <Link href="/projects/" className="inline-flex items-center gap-1 text-sm text-muted hover:text-text"><IconBack className="h-4 w-4" /> Projets</Link>
        <div className="flex flex-wrap items-start justify-between gap-3">
          {editing ? (
            <form className="flex w-full max-w-lg gap-2" onSubmit={async (e) => { e.preventDefault(); await api.updateProject(p.id, { name }); setEditing(false); refresh(); }}>
              <input className="input" value={name} maxLength={120} autoFocus onChange={(e) => setName(e.target.value)} aria-label="Nom du projet" />
              <button className="btn-primary" disabled={!name.trim()}>OK</button>
            </form>
          ) : (
            <button className="text-left" onClick={() => setEditing(true)} title="Renommer">
              <h1 className="text-2xl font-semibold tracking-tight" data-testid="project-name">{p.name}</h1>
            </button>
          )}
          <StatusBadge status={p.status} />
        </div>
        <p className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted">
          <span>Créé le {formatDate(p.created_at)}</span>
          <span>{p.photo_count} photos</span>
          {p.model_faces ? <span>{formatCount(p.model_faces)} faces</span> : null}
          {p.model_size_bytes ? <span>Modèle {formatBytes(p.model_size_bytes)}</span> : null}
        </p>
      </div>

      <div className="flex gap-1 overflow-x-auto border-b border-line" role="tablist">
        {TABS.map((t) => (
          <button key={t.id} role="tab" aria-selected={tab === t.id} onClick={() => go(t.id)}
            className={`-mb-px whitespace-nowrap border-b-2 px-4 py-2.5 text-sm transition-colors ${tab === t.id ? "border-accent text-text" : "border-transparent text-muted hover:text-text"}`}>
            {t.label}{t.id === "process" && locked && <Spinner className="ml-2 h-3 w-3 align-[-1px]" />}
          </button>
        ))}
      </div>

      <div className="animate-in" key={tab}>
        {tab === "photos" && <PhotoPanel project={p} locked={locked} onChange={refresh} />}
        {tab === "process" && <ProcessPanel project={p} onChange={refresh} onShowModel={() => go("model")} />}
        {tab === "model" && (p.has_model ? (
          <Viewer3D
            modelUrl={url(`/api/projects/${p.id}/preview.glb?v=${Math.round(p.updated_at)}`)}
            fullModelUrl={p.preview?.decimated ? url(`/api/projects/${p.id}/preview.glb?full=true&v=${Math.round(p.updated_at)}`) : null}
            pointCloudUrl={p.preview?.pointcloud_points ? url(`/api/projects/${p.id}/pointcloud.ply?v=${Math.round(p.updated_at)}`) : null}
            info={p.preview}
            autoCapture={!p.thumbnail_3d}
            onCapture={(blob) => api.putThumbnail(p.id, blob).catch(() => undefined)}
          />
        ) : (
          <div className="card p-6 text-sm text-muted">Le modèle 3D apparaîtra ici après la reconstruction. <button className="text-accent hover:underline" onClick={() => go("process")}>Lancer la reconstruction</button></div>
        ))}
        {tab === "exports" && <ExportPanel project={p} onChange={refresh} />}
      </div>
    </div>
  );
}

export default function ProjectPage() {
  return <Suspense fallback={<div className="flex items-center gap-2 text-sm text-muted"><Spinner /> Chargement…</div>}><ProjectView /></Suspense>;
}
