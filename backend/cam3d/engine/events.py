"""Progress / logging primitives shared by all stages.

The engine never prints; it emits :class:`StageEvent` objects through a
callback and writes per-stage log files. Progress is only reported when it is
actually measured (e.g. image N/M); otherwise ``progress`` stays ``None`` and
the UI shows an activity indicator for the current stage.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Callable


class Stage(str, Enum):
    PREPARE = "prepare"
    SFM = "sfm"
    DENSE = "dense"
    MESH = "mesh"
    REFINE = "refine"
    TEXTURE = "texture"
    CLEANUP = "cleanup"
    EXPORT = "export"


STAGE_LABELS = {
    Stage.PREPARE: "Préparation",
    Stage.SFM: "Analyse des images",
    Stage.DENSE: "Reconstruction dense",
    Stage.MESH: "Maillage",
    Stage.REFINE: "Raffinement",
    Stage.TEXTURE: "Texturage",
    Stage.CLEANUP: "Optimisation",
    Stage.EXPORT: "Exportation",
}


@dataclass
class StageEvent:
    stage: Stage
    status: str            # "started" | "progress" | "log" | "finished" | "failed" | "skipped"
    message: str = ""
    progress: float | None = None   # 0..1 when measurable, else None
    detail: dict = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


EventCallback = Callable[[StageEvent], None]


class CancelledError(RuntimeError):
    pass


class CancelToken:
    def __init__(self) -> None:
        self._ev = threading.Event()

    def cancel(self) -> None:
        self._ev.set()

    @property
    def cancelled(self) -> bool:
        return self._ev.is_set()

    def check(self) -> None:
        if self._ev.is_set():
            raise CancelledError("Traitement annulé par l'utilisateur")


class StageLogger:
    """Writes a stage log file and forwards events to the pipeline callback."""

    def __init__(self, stage: Stage, log_dir: Path, callback: EventCallback | None = None) -> None:
        self.stage = stage
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.log_dir / f"{stage.value}.log"
        self._fh = open(self.path, "a", encoding="utf-8")
        self._cb = callback
        self._t0 = time.time()

    def _emit(self, status: str, message: str = "", progress: float | None = None, **detail) -> None:
        if message:
            self._fh.write(f"[{time.strftime('%H:%M:%S')}] {message}\n")
            self._fh.flush()
        if self._cb:
            self._cb(StageEvent(self.stage, status, message, progress, detail))

    def start(self, message: str = "") -> None:
        self._emit("started", message or f"{STAGE_LABELS[self.stage]} : démarrage")

    def log(self, message: str) -> None:
        self._emit("log", message)

    def progress(self, value: float, message: str = "") -> None:
        self._emit("progress", message, progress=max(0.0, min(1.0, value)))

    def raw(self, line: str) -> None:
        """Verbatim external-tool output (goes to file, not to UI events)."""
        self._fh.write(line.rstrip("\n") + "\n")
        self._fh.flush()

    def finish(self, message: str = "", **detail) -> float:
        dt = time.time() - self._t0
        self._emit("finished", message or f"{STAGE_LABELS[self.stage]} : terminé en {dt:.1f}s", duration=dt, **detail)
        return dt

    def fail(self, message: str, **detail) -> None:
        self._emit("failed", message, duration=time.time() - self._t0, **detail)

    def skip(self, message: str) -> None:
        self._emit("skipped", message)

    def close(self) -> None:
        self._fh.close()
