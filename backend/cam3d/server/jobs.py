"""Job manager: queue, isolated worker processes, events, cancellation.

* One job runs at a time (photogrammetry saturates CPU and RAM); others wait
  in a FIFO queue.
* Each job is a separate OS process (``python -m cam3d.worker``) started in
  its own process group, so cancelling can kill OpenMVS children too and a
  native crash only fails the job.
* Events from the worker are stored (``logs/events.jsonl``), kept in memory
  for late subscribers, and broadcast to WebSocket subscribers.
* On server start, jobs left ``running``/``queued`` by a crash or a reboot are
  marked ``interrupted``; ``retry`` relaunches them with ``--resume`` so
  finished stages are not recomputed.
"""
from __future__ import annotations

import asyncio
import json
import os
import signal
import statistics
import subprocess
import sys
import threading
import time
import uuid
from collections import deque
from pathlib import Path

from ..engine.profiles import PROFILES
from ..engine.stages.export import FORMATS
from .config import Settings
from .db import Database, now
from .projects import ProjectError, ProjectStore

PREFIX = "CAM3D "
ACTIVE = ("queued", "running")


class JobManager:
    def __init__(self, settings: Settings, db: Database, projects: ProjectStore) -> None:
        self.settings = settings
        self.db = db
        self.projects = projects
        self._queue: deque[str] = deque()
        self._cv = threading.Condition()
        self._stopping = False
        self._procs: dict[str, subprocess.Popen] = {}
        self._cancel_requested: set[str] = set()
        self._recent: dict[str, deque] = {}
        self._subs: list[tuple[asyncio.AbstractEventLoop, asyncio.Queue]] = []
        self._subs_lock = threading.Lock()
        self._thread = threading.Thread(target=self._loop, name="cam3d-jobs", daemon=True)
        self._recover()

    # ------------------------------------------------------------ lifecycle
    def _recover(self) -> None:
        for j in self.db.all("SELECT * FROM jobs WHERE status IN ('queued','running')"):
            self.db.update("jobs", {"id": j["id"]}, {"status": "interrupted", "finished_at": now(),
                                                    "error": "Traitement interrompu (arrêt de l'application). Relancez-le pour reprendre."})
            if j["kind"] == "reconstruct":
                self.projects.set_status(j["project_id"], "interrupted")

    def start(self) -> None:
        if not self._thread.is_alive():
            self._thread.start()

    def stop(self) -> None:
        with self._cv:
            self._stopping = True
            self._cv.notify_all()
        for jid in list(self._procs):
            self.cancel(jid, grace_s=2.0)
        self._thread.join(timeout=5)

    # ------------------------------------------------------------ queries
    def _row(self, job_id: str) -> dict:
        j = self.db.one("SELECT * FROM jobs WHERE id = ?", (job_id,))
        if not j:
            raise ProjectError("Tâche introuvable", 404)
        j["formats"] = json.loads(j["formats"]) if j.get("formats") else []
        j["params"] = json.loads(j["params"]) if j.get("params") else {}
        j["stages"] = json.loads(j["stages"]) if j.get("stages") else {}
        j["resume"] = bool(j["resume"])
        j["queue_position"] = (list(self._queue).index(job_id) + 1) if job_id in self._queue else None
        return j

    def get(self, job_id: str, with_events: bool = False) -> dict:
        j = self._row(job_id)
        if with_events:
            j["events"] = list(self._recent.get(job_id, []))
            if not j["events"]:
                j["events"] = self._read_events_file(j)
        return j

    def _read_events_file(self, j: dict, limit: int = 300) -> list[dict]:
        f = self.projects.settings.projects_dir / j["project_id"] / "logs" / "events.jsonl"
        if not f.exists():
            return []
        out = []
        with open(f, encoding="utf-8") as fh:
            for line in fh:
                try:
                    e = json.loads(line)
                except ValueError:
                    continue
                if e.get("job_id") == j["id"]:
                    out.append(e)
        return out[-limit:]

    def list(self, project_id: str | None = None, limit: int = 50) -> list[dict]:
        if project_id:
            rows = self.db.all("SELECT id FROM jobs WHERE project_id = ? ORDER BY created_at DESC LIMIT ?", (project_id, limit))
        else:
            rows = self.db.all("SELECT id FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,))
        return [self._row(r["id"]) for r in rows]

    def active_job(self, project_id: str) -> dict | None:
        r = self.db.one("SELECT id FROM jobs WHERE project_id = ? AND status IN ('queued','running') ORDER BY created_at DESC LIMIT 1", (project_id,))
        return self._row(r["id"]) if r else None

    def estimate(self, profile: str, num_images: int) -> dict | None:
        """Median seconds-per-image of past successful runs on *this* machine.

        Returns None when there is no history: the UI must then not show any
        duration (no invented estimates)."""
        rows = self.db.all("SELECT duration_s, num_images FROM jobs WHERE kind = 'reconstruct' AND status = 'succeeded' "
                           "AND profile = ? AND num_images > 0 AND duration_s > 0 AND resume = 0 ORDER BY finished_at DESC LIMIT 20", (profile,))
        if not rows or num_images <= 0:
            return None
        per_image = statistics.median(r["duration_s"] / r["num_images"] for r in rows)
        return {"seconds": round(per_image * num_images), "based_on_runs": len(rows),
                "method": "médiane du temps par image des reconstructions réussies sur cet ordinateur"}

    # ------------------------------------------------------------ commands
    def submit(self, project_id: str, kind: str = "reconstruct", profile: str = "fast",
               formats: list[str] | tuple[str, ...] = ("obj", "glb", "dae"), resume: bool = False,
               params: dict | None = None) -> dict:
        p = self.projects.get(project_id)
        if kind not in ("reconstruct", "export", "video", "edit", "sketchup", "relay"):
            raise ProjectError("Type de tâche inconnu")
        if profile not in PROFILES:
            raise ProjectError(f"Profil inconnu : {profile}")
        formats = [f.lower() for f in formats]
        bad = [f for f in formats if f not in FORMATS]
        if bad:
            raise ProjectError(f"Format(s) inconnu(s) : {', '.join(bad)}")
        if self.active_job(project_id):
            raise ProjectError("Un traitement est déjà en cours pour ce projet", 409)
        if kind == "reconstruct" and p["photo_count"] < 3:
            raise ProjectError("Au moins 3 photos sont nécessaires (20 à 80 recommandées)", 422)
        if kind in ("export", "edit", "sketchup"):
            if not (self.projects.path(project_id) / "meshes" / "model.obj").exists():
                raise ProjectError("Aucun modèle à exporter : lancez d'abord une reconstruction", 409)
            if kind == "export" and not formats:
                raise ProjectError("Aucun format demandé")
        if kind == "video" and not (params or {}).get("video"):
            raise ProjectError("Aucune vidéo indiquée")
        jid = uuid.uuid4().hex[:12]
        self.db.insert("jobs", {"id": jid, "project_id": project_id, "kind": kind, "profile": profile,
                                "formats": formats, "resume": 1 if resume else 0, "status": "queued",
                                "created_at": now(), "num_images": p["photo_count"], "params": params or {}})
        if kind == "reconstruct":
            self.projects.set_status(project_id, "queued", last_job_id=jid, profile=profile)
        with self._cv:
            self._queue.append(jid)
            self._cv.notify_all()
        self._broadcast({"type": "job_queued", "job_id": jid, "project_id": project_id, "kind": kind})
        return self._row(jid)

    def retry(self, job_id: str) -> dict:
        j = self._row(job_id)
        if j["status"] in ACTIVE:
            raise ProjectError("La tâche est encore active", 409)
        return self.submit(j["project_id"], j["kind"], j["profile"] or "fast", j["formats"], resume=(j["kind"] == "reconstruct"))

    def cancel(self, job_id: str, grace_s: float | None = None) -> dict:
        j = self._row(job_id)
        if j["status"] not in ACTIVE:
            raise ProjectError("La tâche n'est pas en cours", 409)
        with self._cv:
            if job_id in self._queue:
                self._queue.remove(job_id)
                self.db.update("jobs", {"id": job_id}, {"status": "cancelled", "finished_at": now()})
                if j["kind"] == "reconstruct":
                    self.projects.set_status(j["project_id"], self._idle_status(j["project_id"]))
                self._broadcast({"type": "job_finished", "job_id": job_id, "project_id": j["project_id"], "status": "cancelled"})
                return self._row(job_id)
        self._cancel_requested.add(job_id)
        proj = self.projects.path(j["project_id"])
        (proj / "processed").mkdir(parents=True, exist_ok=True)
        (proj / "processed" / "CANCEL").write_text("cancel", encoding="utf-8")
        grace = self.settings.cancel_grace_s if grace_s is None else grace_s

        def _force() -> None:
            proc = self._procs.get(job_id)
            if proc is not None and proc.poll() is None:
                self._kill_tree(proc)

        threading.Timer(grace, _force).start()
        self._broadcast({"type": "job_cancelling", "job_id": job_id, "project_id": j["project_id"]})
        return self._row(job_id)

    def _idle_status(self, project_id: str) -> str:
        root = self.projects.path(project_id)
        if (root / "previews" / "model.glb").exists():
            return "done"
        p = self.projects.get(project_id)
        return "ready" if p["photo_count"] else "empty"

    # ------------------------------------------------------------ events
    def subscribe(self) -> asyncio.Queue:
        loop = asyncio.get_running_loop()
        q: asyncio.Queue = asyncio.Queue()
        with self._subs_lock:
            self._subs.append((loop, q))
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        with self._subs_lock:
            self._subs = [(l, s) for (l, s) in self._subs if s is not q]

    def _broadcast(self, msg: dict) -> None:
        with self._subs_lock:
            subs = list(self._subs)
        for loop, q in subs:
            try:
                loop.call_soon_threadsafe(q.put_nowait, msg)
            except RuntimeError:  # loop closed
                self.unsubscribe(q)

    def _import_frames(self, project_id: str, frames: list[str]) -> int:
        """Register frames selected by the worker as project photos (same validation as uploads)."""
        added = 0
        for f in frames:
            fp = Path(f)
            if not fp.exists():
                continue
            try:
                with open(fp, "rb") as fh:
                    self.projects.add_photo(project_id, fp.name, fh)
                added += 1
            except ProjectError:
                pass
            finally:
                fp.unlink(missing_ok=True)
        return added

    # ------------------------------------------------------------ worker
    @staticmethod
    def _kill_tree(proc: subprocess.Popen) -> None:
        try:
            if os.name == "nt":
                subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True)
            else:
                os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            pass

    def _loop(self) -> None:
        while True:
            with self._cv:
                while not self._queue and not self._stopping:
                    self._cv.wait()
                if self._stopping:
                    return
                jid = self._queue.popleft()
            try:
                self._run(jid)
            except Exception as e:  # never let the queue thread die
                self.db.update("jobs", {"id": jid}, {"status": "failed", "finished_at": now(), "error": f"Erreur interne : {e}"})

    def _run(self, jid: str) -> None:
        j = self._row(jid)
        pid = j["project_id"]
        try:
            proj = self.projects.path(pid)
            self.projects.get(pid)
        except ProjectError:
            self.db.update("jobs", {"id": jid}, {"status": "failed", "finished_at": now(), "error": "Projet supprimé"})
            return
        (proj / "logs").mkdir(parents=True, exist_ok=True)
        (proj / "processed").mkdir(parents=True, exist_ok=True)
        (proj / "processed" / "CANCEL").unlink(missing_ok=True)
        cmd = list(self.settings.worker_cmd or [self.settings.worker_python, "-m", "cam3d.worker"])
        cmd += [j["kind"], str(proj), "--profile", j["profile"] or "fast", "--formats", ",".join(j["formats"])]
        if j["resume"]:
            cmd.append("--resume")
        if j["kind"] == "video":
            cmd += ["--video", j["params"]["video"]]
        if j["kind"] == "edit":
            ops_file = proj / "processed" / f"edits_pending_{jid}.json"
            ops_file.write_text(json.dumps({"ops": j["params"].get("ops", [])}), encoding="utf-8")
            cmd += ["--ops-file", str(ops_file)]
        if j["kind"] == "sketchup":
            cmd += ["--level", j["params"].get("level", "standard")]
        started = now()
        self.db.update("jobs", {"id": jid}, {"status": "running", "started_at": started})
        if j["kind"] == "reconstruct":
            self.projects.set_status(pid, "processing")
        self._broadcast({"type": "job_started", "job_id": jid, "project_id": pid, "kind": j["kind"]})
        recent = self._recent.setdefault(jid, deque(maxlen=400))
        kwargs: dict = {}
        if os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
        else:
            kwargs["start_new_session"] = True
        env = dict(os.environ, PYTHONUNBUFFERED="1")
        result: dict | None = None
        with open(proj / "logs" / "worker.log", "a", encoding="utf-8") as errlog, \
                open(proj / "logs" / "events.jsonl", "a", encoding="utf-8") as evlog:
            errlog.write(f"\n=== job {jid} {time.strftime('%Y-%m-%d %H:%M:%S')} : {' '.join(cmd)}\n")
            errlog.flush()
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=errlog, text=True, encoding="utf-8",
                                    errors="replace", env=env, bufsize=1, **kwargs)
            self._procs[jid] = proc
            try:
                assert proc.stdout is not None
                for line in proc.stdout:
                    if not line.startswith(PREFIX):
                        errlog.write(line)
                        continue
                    try:
                        msg = json.loads(line[len(PREFIX):])
                    except ValueError:
                        continue
                    if msg.get("type") == "result":
                        result = msg.get("result") or {}
                        continue
                    if msg.get("type") != "event":
                        continue
                    msg.update(job_id=jid, project_id=pid)
                    recent.append(msg)
                    evlog.write(json.dumps(msg, default=str) + "\n")
                    evlog.flush()
                    if msg.get("status") in ("started", "finished", "failed", "skipped"):
                        self.db.update("jobs", {"id": jid}, {"current_stage": msg.get("stage")})
                    self._broadcast({**msg, "type": "job_event"})
                proc.wait()
            finally:
                self._procs.pop(jid, None)
        (proj / "processed" / f"edits_pending_{jid}.json").unlink(missing_ok=True)
        (proj / "processed" / "relay_code.json").unlink(missing_ok=True)
        cancelled = jid in self._cancel_requested
        self._cancel_requested.discard(jid)
        (proj / "processed" / "CANCEL").unlink(missing_ok=True)
        finished = now()
        values: dict = {"finished_at": finished, "duration_s": round(finished - started, 3)}
        if result is not None and result.get("stages"):
            values["stages"] = result["stages"]
        if cancelled:
            values.update(status="cancelled", error="Traitement annulé par l'utilisateur")
        elif result is not None and result.get("success"):
            values.update(status="succeeded", error=None)
        else:
            err = (result or {}).get("error") or (
                f"Le processus de traitement s'est arrêté de façon inattendue (code {proc.returncode}). "
                f"Consultez logs/worker.log.")
            values.update(status="failed", error=err, error_stage=(result or {}).get("error_stage"))
        if j["kind"] in ("video", "relay") and values["status"] == "succeeded":
            # import BEFORE publishing "succeeded": clients must see every photo once the job is done
            added = self._import_frames(pid, (result or {}).get("frames") or [])
            values["stages"] = {**(values.get("stages") or {}), j["kind"]: {"status": "finished", "frames_added": added}}
            if j["kind"] == "video" and added < 3:
                values.update(status="failed", error=f"Seulement {added} image(s) valide(s) extraite(s) de la vidéo")
            if j["kind"] == "relay" and added == 0:
                values.update(status="failed", error="Aucune photo valide dans ce scan")
        self.db.update("jobs", {"id": jid}, values)
        if j["kind"] == "edit" and values["status"] == "succeeded":
            try:
                self.projects.refresh_model_info(pid)
            except ProjectError:
                pass
        if j["kind"] == "reconstruct":
            try:
                if values["status"] == "succeeded":
                    self.projects.refresh_model_info(pid)
                    self.projects.set_status(pid, "done")
                elif values["status"] == "cancelled":
                    self.projects.set_status(pid, "cancelled")
                else:
                    self.projects.set_status(pid, "failed")
            except ProjectError:
                pass
        self._broadcast({"type": "job_finished", "job_id": jid, "project_id": pid, "status": values["status"],
                         "error": values.get("error")})
