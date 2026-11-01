"use client";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect } from "react";
import { useApp } from "@/lib/store";
import { IconCube, IconFolder, IconGear } from "./Icons";

const NAV = [
  { href: "/", label: "Accueil", icon: IconCube },
  { href: "/projects/", label: "Projets", icon: IconFolder },
  { href: "/settings/", label: "Paramètres", icon: IconGear },
];

export function Shell({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  const router = useRouter();
  const { init, authError, whoami, connected } = useApp();

  useEffect(() => { init(); }, [init]);
  useEffect(() => {
    // A phone that is not paired yet goes to the pairing screen.
    if (authError === 401 && !path.startsWith("/pair") && !path.startsWith("/setup")) router.replace("/pair/");
  }, [authError, path, router]);

  const desktopOnly = (href: string) => href === "/settings/" && whoami?.role === "device";
  // before pairing, navigation links would only bounce back to the pairing screen
  const bare = path.startsWith("/pair") || path.startsWith("/setup") || !whoami;

  return (
    <div className={`min-h-dvh sm:pb-0 ${bare ? "" : "pb-20"}`}>
      <header className="sticky top-0 z-30 border-b border-line bg-bg/80 backdrop-blur-xl">
        <div className="mx-auto flex h-14 max-w-6xl items-center justify-between px-4">
          <Link href="/" className="flex items-center gap-2 font-semibold tracking-tight">
            <span className="grid h-7 w-7 place-items-center rounded-lg bg-accent-strong/20 text-accent"><IconCube className="h-4 w-4" /></span>
            cam3D
          </Link>
          <nav className={`hidden items-center gap-1 ${bare ? "" : "sm:flex"}`}>
            {NAV.filter((n) => !desktopOnly(n.href)).map((n) => (
              <Link key={n.href} href={n.href}
                className={`rounded-lg px-3 py-1.5 text-sm transition-colors ${active(path, n.href) ? "bg-white/10 text-text" : "text-muted hover:text-text"}`}>
                {n.label}
              </Link>
            ))}
          </nav>
          <span title={connected ? "Connecté au moteur local" : "Connexion au moteur local…"}
            className="flex items-center gap-2 text-xs text-faint">
            <span className={`h-2 w-2 rounded-full ${connected ? "bg-ok" : authError === 0 ? "bg-danger" : "bg-warn animate-pulse"}`} />
            <span className="hidden md:inline">{whoami ? (whoami.role === "device" ? whoami.name : "Cet ordinateur") : ""}</span>
          </span>
        </div>
      </header>
      {authError === 0 && (
        <div className="mx-auto mt-4 max-w-6xl px-4">
          <div className="card border-danger/40 p-4 text-sm text-danger">Serveur cam3D injoignable. Lancez l’application sur l’ordinateur puis rechargez cette page.</div>
        </div>
      )}
      <main className="mx-auto max-w-6xl px-4 py-6 sm:py-10">{children}</main>
      <nav className={`fixed inset-x-0 bottom-0 z-30 border-t border-line bg-bg/90 backdrop-blur-xl sm:hidden ${bare ? "hidden" : ""}`} style={{ paddingBottom: "env(safe-area-inset-bottom)" }}>
        <div className="grid grid-cols-3">
          {NAV.filter((n) => !desktopOnly(n.href)).map((n) => (
            <Link key={n.href} href={n.href} className={`flex flex-col items-center gap-1 py-2.5 text-[11px] ${active(path, n.href) ? "text-accent" : "text-muted"}`}>
              <n.icon className="h-5 w-5" />{n.label}
            </Link>
          ))}
        </div>
      </nav>
    </div>
  );
}

function active(path: string, href: string) {
  return href === "/" ? path === "/" : path.startsWith(href.replace(/\/$/, ""));
}
