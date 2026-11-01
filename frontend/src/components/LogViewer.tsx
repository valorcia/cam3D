"use client";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { STAGE_LABELS } from "@/lib/format";

export function LogViewer({ projectId, refresh }: { projectId: string; refresh: number }) {
  const [logs, setLogs] = useState<{ name: string; size_bytes: number }[]>([]);
  const [sel, setSel] = useState<string | null>(null);
  const [text, setText] = useState("");
  useEffect(() => { api.logs(projectId).then(setLogs).catch(() => setLogs([])); }, [projectId, refresh]);
  useEffect(() => {
    if (!sel) return;
    api.log(projectId, sel, 400).then(setText).catch((e) => setText(String(e.message)));
  }, [projectId, sel, refresh]);
  if (!logs.length) return <p className="text-sm text-faint">Aucun journal pour l’instant.</p>;
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-1.5">
        {logs.map((l) => (
          <button key={l.name} onClick={() => setSel(l.name)} className={`chip ${sel === l.name ? "bg-accent/20 text-accent" : "bg-white/5 text-muted hover:text-text"}`}>
            {(STAGE_LABELS as Record<string, string>)[l.name] ?? (l.name === "pipeline" ? "Pipeline" : l.name === "worker" ? "Processus" : l.name)}
          </button>
        ))}
      </div>
      {sel && <pre className="max-h-80 overflow-auto rounded-xl bg-black/40 p-3 font-mono text-[11px] leading-relaxed text-muted" data-testid="log-text">{text || "…"}</pre>}
    </div>
  );
}
