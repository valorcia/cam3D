"use client";
import { useEffect, useMemo, useState } from "react";
import { IconCube, IconDots } from "@/components/Icons";
import { ProjectCard } from "@/components/ProjectCard";
import { EmptyState, ErrorBox, Modal, Spinner } from "@/components/ui";
import { api } from "@/lib/api";
import { useApp } from "@/lib/store";
import type { Project } from "@/lib/types";

export default function ProjectsPage() {
  const { whoami, revision } = useApp();
  const [projects, setProjects] = useState<Project[] | null>(null);
  const [archived, setArchived] = useState(false);
  const [query, setQuery] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [menuFor, setMenuFor] = useState<Project | null>(null);
  const [rename, setRename] = useState<{ p: Project; name: string } | null>(null);
  const [confirmDelete, setConfirmDelete] = useState<Project | null>(null);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    if (!whoami) return;
    api.projects(archived).then(setProjects).catch((e) => setError(e.message));
  }, [whoami, archived, revision, tick]);

  const shown = useMemo(
    () => (projects ?? []).filter((p) => p.name.toLowerCase().includes(query.trim().toLowerCase())),
    [projects, query],
  );

  async function run(fn: () => Promise<unknown>) {
    setError(null);
    try { await fn(); setTick((t) => t + 1); } catch (e: any) { setError(e.message); }
    setMenuFor(null);
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Mes projets</h1>
          <p className="text-sm text-muted">{projects ? `${projects.length} projet${projects.length > 1 ? "s" : ""}` : "…"}</p>
        </div>
        <div className="flex w-full gap-2 sm:w-auto">
          <input className="input sm:w-64" placeholder="Rechercher…" value={query} onChange={(e) => setQuery(e.target.value)} aria-label="Rechercher un projet" />
          <button className={archived ? "btn-primary" : "btn-ghost"} onClick={() => setArchived(!archived)} aria-pressed={archived}>Archives</button>
        </div>
      </div>
      {error && <ErrorBox>{error}</ErrorBox>}
      {projects === null ? (
        <div className="flex items-center gap-2 text-sm text-muted"><Spinner /> Chargement…</div>
      ) : shown.length === 0 ? (
        <EmptyState icon={<IconCube />} title={query ? "Aucun résultat" : "Aucun projet"} text={query ? "Essayez un autre nom." : "Les projets créés apparaîtront ici."} />
      ) : (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {shown.map((p) => (
            <ProjectCard key={p.id} p={p} menu={
              <button className="grid h-8 w-8 place-items-center rounded-lg text-muted hover:bg-white/10 hover:text-text" aria-label={`Actions pour ${p.name}`} onClick={() => setMenuFor(p)}>
                <IconDots />
              </button>
            } />
          ))}
        </div>
      )}

      <Modal open={!!menuFor} onClose={() => setMenuFor(null)} title={menuFor?.name ?? ""}>
        {menuFor && (
          <div className="grid gap-2">
            <button className="btn-ghost justify-start" onClick={() => { setRename({ p: menuFor, name: menuFor.name }); setMenuFor(null); }}>Renommer</button>
            <button className="btn-ghost justify-start" onClick={() => run(() => api.duplicateProject(menuFor.id))}>Dupliquer</button>
            <button className="btn-ghost justify-start" onClick={() => run(() => api.updateProject(menuFor.id, { archived: !menuFor.archived }))}>{menuFor.archived ? "Désarchiver" : "Archiver"}</button>
            {whoami?.role === "desktop" && (
              <button className="btn-danger justify-start" onClick={() => { setConfirmDelete(menuFor); setMenuFor(null); }}>Supprimer…</button>
            )}
          </div>
        )}
      </Modal>

      <Modal open={!!rename} onClose={() => setRename(null)} title="Renommer le projet">
        {rename && (
          <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); run(() => api.updateProject(rename.p.id, { name: rename.name })); setRename(null); }}>
            <input className="input" autoFocus value={rename.name} maxLength={120} onChange={(e) => setRename({ ...rename, name: e.target.value })} aria-label="Nouveau nom" />
            <div className="flex justify-end gap-2">
              <button type="button" className="btn-ghost" onClick={() => setRename(null)}>Annuler</button>
              <button className="btn-primary" disabled={!rename.name.trim()}>Enregistrer</button>
            </div>
          </form>
        )}
      </Modal>

      <Modal open={!!confirmDelete} onClose={() => setConfirmDelete(null)} title="Supprimer définitivement ?">
        {confirmDelete && (
          <div className="space-y-4">
            <p className="text-sm text-muted">« {confirmDelete.name} » sera supprimé de cet ordinateur avec ses {confirmDelete.photo_count} photos originales, son modèle et ses exports. Cette action est irréversible. Pour le conserver sans l’afficher, archivez-le plutôt.</p>
            <div className="flex justify-end gap-2">
              <button className="btn-ghost" onClick={() => setConfirmDelete(null)}>Annuler</button>
              <button className="btn-danger" onClick={() => { const p = confirmDelete; setConfirmDelete(null); run(() => api.deleteProject(p.id)); }}>Supprimer</button>
            </div>
          </div>
        )}
      </Modal>
    </div>
  );
}
