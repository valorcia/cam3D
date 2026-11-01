"""Test double for ``cam3d.worker`` (used ONLY by the API tests).

It speaks the real worker protocol so the JobManager can be tested in
milliseconds. Behaviour is selected by the project name file STUB_MODE in
processed/: "ok" (default), "fail", "slow" (waits for CANCEL), "crash".
"""
import json
import sys
import time
from pathlib import Path


def emit(o):
    print("CAM3D " + json.dumps(o), flush=True)


kind, project = sys.argv[1], Path(sys.argv[2])
mode_file = project / "processed" / "STUB_MODE"
mode = mode_file.read_text().strip() if mode_file.exists() else "ok"
print("noise line that the server must ignore", flush=True)
emit({"type": "event", "stage": "prepare", "status": "started", "message": "start", "progress": None, "detail": {}})
emit({"type": "event", "stage": "prepare", "status": "progress", "message": "1/2", "progress": 0.5, "detail": {}})
if mode == "slow":
    for _ in range(200):
        if (project / "processed" / "CANCEL").exists():
            emit({"type": "event", "stage": "prepare", "status": "failed", "message": "annulé", "progress": None, "detail": {}})
            emit({"type": "result", "result": {"success": False, "error": "annulé", "error_stage": "prepare"}})
            sys.exit(3)
        time.sleep(0.05)
if mode == "hang":  # ignores CANCEL: must be killed by the server
    time.sleep(60)
if mode == "crash":
    sys.exit(-11 if sys.platform != "win32" else 11)
if mode == "fail":
    emit({"type": "result", "result": {"success": False, "error": "COLMAP n'a pu enregistrer aucune caméra", "error_stage": "sfm"}})
    sys.exit(3)
(project / "previews").mkdir(exist_ok=True)
(project / "previews" / "model.glb").write_bytes(b"glTF")
emit({"type": "event", "stage": "prepare", "status": "finished", "message": "ok", "progress": None, "detail": {"duration": 0.1}})
emit({"type": "result", "result": {"success": True, "stages": {"prepare": {"status": "finished"}}}})
