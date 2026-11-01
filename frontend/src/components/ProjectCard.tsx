"use client";
import Link from "next/link";
import { url } from "@/lib/api";
import { formatBytes, formatDate } from "@/lib/format";
import type { Project } from "@/lib/types";
import { IconCube } from "./Icons";
import { StatusBadge } from "./ui";

export function ProjectCard({ p, menu }: { p: Project; menu?: React.ReactNode }) {
  return (
    <div className="card group relative overflow-hidden transition-colors hover:border-line-strong animate-in" data-testid="project-card">
      <Link href={`/project/?id=${p.id}`} className="block">
        <div className="relative aspect-[4/3] bg-surface-2">
          {p.has_thumbnail ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={url(`/api/projects/${p.id}/thumbnail.jpg?v=${Math.round(p.updated_at)}`)} alt="" loading="lazy"
              className="h-full w-full object-cover transition-transform duration-300 group-hover:scale-[1.02]" />
          ) : (
            <div className="grid h-full place-items-center text-faint"><IconCube className="h-10 w-10" /></div>
          )}
          <div className="absolute left-3 top-3"><StatusBadge status={p.status} /></div>
          {p.archived && <span className="chip absolute right-3 top-3 bg-black/60 text-muted">Archivé</span>}
        </div>
        <div className="space-y-1 p-4">
          <h3 className="truncate font-medium">{p.name}</h3>
          <p className="text-xs text-muted">{formatDate(p.created_at)}</p>
          <p className="flex flex-wrap gap-x-3 text-xs text-faint">
            <span>{p.photo_count} photo{p.photo_count > 1 ? "s" : ""}</span>
            {p.model_size_bytes ? <span>Modèle {formatBytes(p.model_size_bytes)}</span> : null}
            {p.model_faces ? <span>{p.model_faces.toLocaleString("fr-FR")} faces</span> : null}
          </p>
        </div>
      </Link>
      {menu && <div className="absolute bottom-3 right-3">{menu}</div>}
    </div>
  );
}
