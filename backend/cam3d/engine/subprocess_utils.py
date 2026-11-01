"""Run external tools with live log streaming and cancellation."""
from __future__ import annotations

import os
import subprocess
import threading
from pathlib import Path
from typing import Callable

from .events import CancelToken, CancelledError


class ToolError(RuntimeError):
    def __init__(self, cmd: list[str], returncode: int, tail: str):
        self.cmd = cmd
        self.returncode = returncode
        self.tail = tail
        super().__init__(f"{Path(cmd[0]).name} a échoué (code {returncode}). Dernières lignes:\n{tail}")


def run_tool(
    cmd: list[str],
    cwd: str | Path | None = None,
    on_line: Callable[[str], None] | None = None,
    cancel: CancelToken | None = None,
    env: dict | None = None,
) -> str:
    """Run ``cmd``; stream stdout+stderr lines to ``on_line``; raise on failure.

    Returns the last ~40 lines of output (useful for error messages).
    """
    full_env = dict(os.environ)
    if env:
        full_env.update(env)
    proc = subprocess.Popen(
        [str(c) for c in cmd],
        cwd=str(cwd) if cwd else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=full_env,
        bufsize=1,
    )
    tail: list[str] = []

    def _watch_cancel() -> None:
        if cancel is None:
            return
        while proc.poll() is None:
            if cancel.cancelled:
                proc.kill()
                return
            cancel._ev.wait(0.5)

    watcher = threading.Thread(target=_watch_cancel, daemon=True)
    watcher.start()
    assert proc.stdout is not None
    for line in proc.stdout:
        line = line.rstrip("\n")
        tail.append(line)
        if len(tail) > 40:
            tail.pop(0)
        if on_line:
            on_line(line)
    proc.wait()
    if cancel is not None and cancel.cancelled:
        raise CancelledError("Traitement annulé par l'utilisateur")
    if proc.returncode != 0:
        raise ToolError([str(c) for c in cmd], proc.returncode, "\n".join(tail[-15:]))
    return "\n".join(tail)
