"use client";
import { useEffect, useRef } from "react";
import { PROJECT_STATUS_LABEL } from "@/lib/format";

export function Spinner({ className = "h-4 w-4" }: { className?: string }) {
  return <span className={`inline-block animate-spin rounded-full border-2 border-current border-t-transparent ${className}`} role="status" aria-label="En cours" />;
}

const STATUS_STYLE: Record<string, string> = {
  empty: "bg-white/5 text-faint",
  ready: "bg-white/10 text-muted",
  queued: "bg-warn/10 text-warn",
  processing: "bg-accent/15 text-accent",
  done: "bg-ok/10 text-ok",
  failed: "bg-danger/10 text-danger",
  cancelled: "bg-white/5 text-muted",
  interrupted: "bg-warn/10 text-warn",
};

export function StatusBadge({ status }: { status: string }) {
  return (
    <span className={`chip ${STATUS_STYLE[status] ?? "bg-white/5 text-muted"}`}>
      {status === "processing" && <Spinner className="h-3 w-3" />}
      {PROJECT_STATUS_LABEL[status] ?? status}
    </span>
  );
}

export function Modal({ open, onClose, title, children }: { open: boolean; onClose: () => void; title: string; children: React.ReactNode }) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (open && !d.open) d.showModal();
    if (!open && d.open) d.close();
  }, [open]);
  return (
    <dialog ref={ref} onClose={onClose} onClick={(e) => e.target === ref.current && onClose()}
      className="m-auto w-[min(92vw,28rem)] rounded-2xl border border-line-strong bg-surface-2 p-0 text-text backdrop:bg-black/60 backdrop:backdrop-blur-sm">
      <div className="p-5">
        <h2 className="mb-3 text-base font-semibold">{title}</h2>
        {children}
      </div>
    </dialog>
  );
}

export function EmptyState({ icon, title, text, action }: { icon: React.ReactNode; title: string; text: string; action?: React.ReactNode }) {
  return (
    <div className="card flex flex-col items-center gap-3 px-6 py-12 text-center">
      <div className="grid h-12 w-12 place-items-center rounded-2xl bg-white/5 text-muted">{icon}</div>
      <h3 className="font-medium">{title}</h3>
      <p className="max-w-sm text-sm text-muted">{text}</p>
      {action}
    </div>
  );
}

export function ErrorBox({ children }: { children: React.ReactNode }) {
  return <div className="rounded-xl border border-danger/30 bg-danger/10 px-4 py-3 text-sm text-danger">{children}</div>;
}
