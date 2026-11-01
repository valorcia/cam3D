export function Spinner({ className = "h-4 w-4" }: { className?: string }) {
  return <span className={`inline-block animate-spin rounded-full border-2 border-current border-t-transparent ${className}`} role="status" aria-label="En cours" />;
}

export function Logo() {
  return (
    <span className="flex items-center gap-2 font-semibold tracking-tight">
      <span className="grid h-7 w-7 place-items-center rounded-lg bg-accent-strong/20 text-accent">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8} className="h-4 w-4"><path d="M12 3 4 7.5v9L12 21l8-4.5v-9L12 3Z" /><path d="m4 7.5 8 4.5 8-4.5M12 12v9" /></svg>
      </span>
      cam3D <span className="font-normal text-muted">Capture</span>
    </span>
  );
}

export function ErrorBox({ children }: { children: React.ReactNode }) {
  return <div className="rounded-xl border border-danger/30 bg-danger/10 px-4 py-3 text-sm text-danger">{children}</div>;
}
