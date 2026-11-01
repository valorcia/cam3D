"""Reconstruction worker process.

Run by the server's JobManager in a separate process so that a native crash
(OpenMVS, COLMAP) or a cancellation never takes the API down:

    python -m cam3d.worker reconstruct <project_dir> --profile fast --formats obj,glb,dae [--resume]
    python -m cam3d.worker export <project_dir> --formats dae,obj

Protocol: one JSON object per stdout line, prefixed with ``CAM3D `` (other
output is ignored by the server). Cancellation: the server creates
``<project_dir>/processed/CANCEL``; the worker notices it within 0.5 s and
stops at the next checkpoint (external tools are killed).
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from dataclasses import asdict
from pathlib import Path

PREFIX = "CAM3D "


def emit(obj: dict) -> None:
    sys.stdout.write(PREFIX + json.dumps(obj, default=str) + "\n")
    sys.stdout.flush()


def _event_to_dict(ev) -> dict:
    return {"type": "event", "stage": ev.stage.value, "status": ev.status, "message": ev.message,
            "progress": ev.progress, "detail": ev.detail, "timestamp": ev.timestamp}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="cam3d.worker")
    p.add_argument("kind", choices=["reconstruct", "export"])
    p.add_argument("project")
    p.add_argument("--profile", default="fast")
    p.add_argument("--formats", default="obj,glb,dae")
    p.add_argument("--resume", action="store_true")
    a = p.parse_args(argv)

    from .engine.events import CancelToken

    project = Path(a.project)
    cancel_file = project / "processed" / "CANCEL"
    cancel_file.unlink(missing_ok=True)
    cancel = CancelToken()

    def watch() -> None:
        while not cancel.cancelled:
            if cancel_file.exists():
                cancel.cancel()
                return
            time.sleep(0.5)

    threading.Thread(target=watch, daemon=True).start()
    formats = tuple(f.strip() for f in a.formats.split(",") if f.strip())

    if a.kind == "reconstruct":
        from .engine.pipeline import ReconstructionPipeline

        pipe = ReconstructionPipeline(callback=lambda ev: emit(_event_to_dict(ev)), cancel=cancel)
        res = pipe.run(project / "originals", project, profile=a.profile, export_formats=formats, resume=a.resume)
        emit({"type": "result", "result": res.to_dict()})
        return 0 if res.success else 3

    # export only
    from .engine.events import Stage, StageLogger
    from .engine.mesh_io import load_obj
    from .engine.stages.export import run_exports

    obj = project / "meshes" / "model.obj"
    if not obj.exists():
        emit({"type": "result", "result": {"success": False, "error": "Aucun modèle reconstruit dans ce projet", "error_stage": "export"}})
        return 3
    try:
        model = load_obj(obj)
        calib = project / "processed" / "calibration.json"
        if calib.exists():
            model.unit_scale = json.loads(calib.read_text(encoding="utf-8")).get("metres_per_unit")
        lg = StageLogger(Stage.EXPORT, project / "logs", lambda ev: emit(_event_to_dict(ev)))
        try:
            res = run_exports(model, project / "exports", "model", formats, lg, cancel,
                              point_cloud=project / "reconstruction" / "dense.ply", unit_scale=model.unit_scale)
        finally:
            lg.close()
        emit({"type": "result", "result": {"success": True, "exports": [asdict(r) for r in res]}})
        return 0
    except Exception as e:  # noqa: BLE001
        emit({"type": "result", "result": {"success": False, "error": f"{type(e).__name__}: {e}", "error_stage": "export"}})
        return 3


if __name__ == "__main__":
    sys.exit(main())
