"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { IconCube, IconFolder, IconGear, IconImages, IconPlus } from "@/components/Icons";
import { ProjectCard } from "@/components/ProjectCard";
import { EmptyState, ErrorBox, Spinner } from "@/components/ui";
import { api, uploadPhotos } from "@/lib/api";
import { useApp } from "@/lib/store";
import type { Project } from "@/lib/types";

export default function Home() {
  const router = useRouter();
  const { system, whoami, revision } = useApp();
  const [projects, setProjects] = useState<Project[] | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!whoami) return;
    api.projects().then(setProjects).catch((e) => setError(e.message));
  }, [whoami, revision]);

  const defaultName = () => `Scan du ${new Date().toLocaleDateString("fr-FR", { day: "numeric", month: "long" })}`;

  async function newScan() {
    setBusy("new"); setError(null);
    try {
      const p = await api.createProject(defaultName());
      router.push(`/project/?id=${p.id}&tab=photos`);
    } catch (e: any) { setError(e.message); setBusy(null); }
  }

  async function importPhotos(files: FileList | null) {
    if (!files?.length) return;
    setBusy("import"); setError(null);
    try {
      const p = await api.createProject(defaultName());
      await uploadPhotos(p.id, Array.from(files));
      router.push(`/project/?id=${p.id}&tab=photos`);
    } catch (e: any) { setError(e.message); setBusy(null); }
  }

  const actions = [
    { key: "new", icon: IconPlus, title: "Nouveau scan", text: "Créer un projet et ajouter des photos", onClick: newScan, primary: true },
    { key: "import", icon: IconImages, title: "Importer des photos", text: "Depuis l’ordinateur ou la galerie", onClick: () => fileInput.current?.click() },
    { key: "projects", icon: IconFolder, title: "Mes projets", text: "Bibliothèque de vos modèles", href: "/projects/" },
    ...(whoami?.role === "desktop" ? [{ key: "settings", icon: IconGear, title: "Paramètres", text: "Matériel, moteurs, téléphone", href: "/settings/" }] : []),
  ];

  return (
    <div className="space-y-10">
      <section className="animate-in">
        <h1 className="text-3xl font-semibold tracking-tight sm:text-4xl">Scannez le réel en 3D.</h1>
        <p className="mt-2 max-w-xl text-muted">Photographiez un objet ou un lieu : cam3D reconstruit un modèle texturé, sur votre ordinateur, sans abonnement ni cloud.</p>
      </section>

      {system && !system.reconstruction_available && (
        <ErrorBox>Le moteur de reconstruction n’est pas complètement installé sur cet ordinateur. {whoami?.role === "desktop" && <Link href="/settings/" className="underline">Voir le diagnostic</Link>}</ErrorBox>
      )}
      {error && <ErrorBox>{error}</ErrorBox>}

      <section className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <input ref={fileInput} type="file" accept="image/*" multiple hidden onChange={(e) => importPhotos(e.target.files)} data-testid="home-import-input" />
        {actions.map((a, i) => {
          const inner = (
            <>
              <span className={`grid h-10 w-10 place-items-center rounded-xl ${a.primary ? "bg-white/15" : "bg-white/5 text-accent"}`}>
                {busy === a.key ? <Spinner /> : <a.icon />}
              </span>
              <span>
                <span className="block font-medium">{a.title}</span>
                <span className={`block text-xs ${a.primary ? "text-white/75" : "text-muted"}`}>{a.text}</span>
              </span>
            </>
          );
          const cls = `card flex min-h-32 flex-col justify-between gap-4 p-4 text-left transition-all hover:-translate-y-0.5 animate-in ${a.primary ? "border-transparent bg-accent-strong text-white hover:bg-accent-strong/90" : "hover:border-line-strong"}`;
          return "href" in a && a.href ? (
            <Link key={a.key} href={a.href} className={cls} style={{ animationDelay: `${i * 40}ms` }}>{inner}</Link>
          ) : (
            <button key={a.key} onClick={a.onClick} disabled={!!busy} className={cls} style={{ animationDelay: `${i * 40}ms` }}>{inner}</button>
          );
        })}
      </section>

      <section>
        <div className="mb-4 flex items-end justify-between">
          <h2 className="text-lg font-semibold">Derniers scans</h2>
          {projects && projects.length > 0 && <Link href="/projects/" className="text-sm text-accent hover:underline">Tout voir</Link>}
        </div>
        {projects === null ? (
          <div className="flex items-center gap-2 text-sm text-muted"><Spinner /> Chargement…</div>
        ) : projects.length === 0 ? (
          <EmptyState icon={<IconCube />} title="Aucun scan pour l’instant" text="Créez votre premier scan : 20 à 80 photos prises en tournant autour de l’objet suffisent." />
        ) : (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {projects.slice(0, 6).map((p) => <ProjectCard key={p.id} p={p} />)}
          </div>
        )}
      </section>
    </div>
  );
}
