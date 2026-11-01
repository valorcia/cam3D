"""FastAPI application: the local API used by the web UI and phones.

All routes live under ``/api``. Authorisation: see ``security.py``.
"""
from __future__ import annotations

import asyncio
import io
import json
import time
from urllib.parse import quote
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

from fastapi import Depends, FastAPI, File, HTTPException, Query, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from .. import __version__
from ..engine.events import STAGE_LABELS, Stage
from ..engine.hardware import detect_hardware
from ..engine.profiles import PROFILES
from ..engine.stages.export import FORMATS
from ..engine.tools import discover_tools
from .config import Settings
from .db import Database
from .jobs import JobManager
from .network import lan_addresses
from .projects import ProjectError, ProjectStore
from .security import PairingError, PairingManager
from .tls import TlsPaths, ca_info
from ..engine.edit import EditState as EditStateLazy

LOG_STAGES = [s.value for s in Stage] + ["pipeline", "worker"]
TOKEN_COOKIE = "cam3d_token"


@dataclass
class Principal:
    role: str           # "desktop" | "device"
    name: str


class ProjectCreate(BaseModel):
    name: str = Field(default="Nouveau scan", max_length=120)


class ProjectPatch(BaseModel):
    name: str | None = Field(default=None, max_length=120)
    archived: bool | None = None


class ReconstructRequest(BaseModel):
    profile: str = "fast"
    formats: list[str] = Field(default_factory=lambda: ["obj", "glb", "dae"])
    resume: bool = False


class ExportRequest(BaseModel):
    formats: list[str] = Field(default_factory=list)
    sketchup_level: str | None = None


class EditRequest(BaseModel):
    op: dict


class CalibrationRequest(BaseModel):
    p1: list[float] = Field(min_length=3, max_length=3)
    p2: list[float] = Field(min_length=3, max_length=3)
    distance: float = Field(gt=0)
    unit: str = Field(pattern="^(mm|cm|m)$")


class PairClaim(BaseModel):
    code: str = Field(min_length=6, max_length=6)
    device_name: str = Field(default="Téléphone", max_length=60)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    settings.ensure_dirs()
    db = Database(settings.db_path)
    projects = ProjectStore(settings, db)
    jobs = JobManager(settings, db, projects)
    pairing = PairingManager(settings, db)
    cache: dict = {}

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        jobs.start()
        yield
        await run_in_threadpool(jobs.stop)
        db.close()

    app = FastAPI(title="cam3D API", version=__version__, lifespan=lifespan)
    app.state.settings, app.state.db, app.state.projects, app.state.jobs, app.state.pairing = settings, db, projects, jobs, pairing
    # Dev UI (Next.js on :3000) talks to the API on :8765 from the same machine.
    app.add_middleware(CORSMiddleware, allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?",
                       allow_methods=["*"], allow_headers=["*"])

    @app.exception_handler(ProjectError)
    async def _project_error(_: Request, e: ProjectError):
        return JSONResponse({"detail": str(e)}, status_code=e.status)

    @app.exception_handler(PairingError)
    async def _pairing_error(_: Request, e: PairingError):
        return JSONResponse({"detail": str(e)}, status_code=e.status)

    # ------------------------------------------------------------------ auth
    def _principal_from(host: str, headers, query, cookies) -> Principal | None:
        if host in settings.trusted_hosts:
            return Principal("desktop", "Cet ordinateur")
        token = None
        auth = headers.get("authorization", "")
        if auth.lower().startswith("bearer "):
            token = auth[7:].strip()
        token = token or cookies.get(TOKEN_COOKIE) or query.get("token")
        dev = pairing.check_token(token)
        return Principal("device", dev["name"]) if dev else None

    def principal(request: Request) -> Principal:
        p = _principal_from(request.client.host if request.client else "", request.headers, request.query_params, request.cookies)
        if p is None:
            raise HTTPException(401, "Appareil non autorisé : appairez-le depuis l'ordinateur (QR code)")
        return p

    def desktop_only(p: Principal = Depends(principal)) -> Principal:
        if p.role != "desktop":
            raise HTTPException(403, "Action réservée à l'ordinateur")
        return p

    # ------------------------------------------------------------------ system
    @app.get("/api/health")
    def health():
        return {"status": "ok", "version": __version__}

    @app.get("/api/system")
    def system(_: Principal = Depends(principal), refresh: bool = False):
        if refresh or "system" not in cache:
            hw = detect_hardware(settings.data_dir)
            tools = discover_tools()
            cache["system"] = {
                "hardware": hw.to_dict(), "tools": tools.to_dict(),
                "reconstruction_available": bool(tools.pycolmap and tools.pycolmap.available and tools.openmvs_available),
                "video_import_available": bool(tools.ffmpeg and tools.ffmpeg.available),
            }
        return {**cache["system"], "version": __version__, "data_dir": str(settings.data_dir),
                "profiles": [{"name": p.name, "label": p.label, "description": p.description} for p in PROFILES.values()],
                "export_formats": list(FORMATS),
                "stages": [{"id": s.value, "label": STAGE_LABELS[s]} for s in Stage]}

    @app.get("/api/estimate")
    def estimate(profile: str, images: int, _: Principal = Depends(principal)):
        if profile not in PROFILES:
            raise HTTPException(400, "Profil inconnu")
        return {"estimate": jobs.estimate(profile, images)}

    # ------------------------------------------------------------------ projects
    @app.get("/api/projects")
    def list_projects(archived: bool = False, _: Principal = Depends(principal)):
        return projects.list(include_archived=archived)

    @app.post("/api/projects", status_code=201)
    def create_project(body: ProjectCreate, _: Principal = Depends(principal)):
        return projects.create(body.name)

    @app.get("/api/projects/{pid}")
    def get_project(pid: str, _: Principal = Depends(principal)):
        p = projects.get(pid)
        p["photos"] = projects.list_photos(pid)
        p["exports"] = projects.list_exports(pid)
        p["active_job"] = jobs.active_job(pid)
        p["estimates"] = {name: jobs.estimate(name, p["photo_count"]) for name in PROFILES}
        cf = projects.path(pid) / "processed" / "calibration.json"
        p["calibration"] = json.loads(cf.read_text(encoding="utf-8")) if cf.exists() else None
        p["edits"] = EditStateLazy.load(projects.path(pid) / "processed" / "edits.json").ops
        pj = projects.path(pid) / "previews" / "preview.json"
        try:
            p["preview"] = json.loads(pj.read_text(encoding="utf-8")) if pj.exists() else None
        except ValueError:
            p["preview"] = None
        return p

    @app.patch("/api/projects/{pid}")
    def patch_project(pid: str, body: ProjectPatch, _: Principal = Depends(principal)):
        if body.name is not None:
            projects.rename(pid, body.name)
        if body.archived is not None:
            projects.set_archived(pid, body.archived)
        return projects.get(pid)

    @app.post("/api/projects/{pid}/duplicate", status_code=201)
    def duplicate_project(pid: str, _: Principal = Depends(principal)):
        return projects.duplicate(pid)

    @app.delete("/api/projects/{pid}")
    def delete_project(pid: str, confirm: bool = False, _: Principal = Depends(desktop_only)):
        if not confirm:
            raise HTTPException(400, "Suppression définitive : confirmation requise (?confirm=true)")
        projects.delete(pid)
        return {"deleted": pid}

    @app.get("/api/projects/{pid}/thumbnail.jpg")
    def thumbnail(pid: str, _: Principal = Depends(principal)):
        f = projects.path(pid) / "previews" / "thumb.jpg"
        if not f.exists():
            raise HTTPException(404, "Pas de miniature")
        return FileResponse(f, media_type="image/jpeg", headers={"Cache-Control": "no-cache"})

    @app.put("/api/projects/{pid}/thumbnail.jpg")
    async def put_thumbnail(pid: str, request: Request, _: Principal = Depends(principal)):
        data = await request.body()
        await run_in_threadpool(projects.set_thumbnail, pid, data)
        return {"ok": True}

    @app.get("/api/projects/{pid}/preview.glb")
    def preview(pid: str, full: bool = False, _: Principal = Depends(principal)):
        d = projects.path(pid) / "previews"
        f = d / "model_full.glb" if full and (d / "model_full.glb").exists() else d / "model.glb"
        if not f.exists():
            raise HTTPException(404, "Aucun modèle reconstruit")
        return FileResponse(f, media_type="model/gltf-binary", headers={"Cache-Control": "no-cache"})

    @app.get("/api/projects/{pid}/pointcloud.ply")
    def pointcloud(pid: str, _: Principal = Depends(principal)):
        f = projects.path(pid) / "previews" / "pointcloud.ply"
        if not f.exists():
            raise HTTPException(404, "Nuage de points indisponible")
        return FileResponse(f, media_type="application/octet-stream", headers={"Cache-Control": "no-cache"})

    # ------------------------------------------------------------------ photos
    @app.get("/api/projects/{pid}/photos")
    def list_photos(pid: str, _: Principal = Depends(principal)):
        projects.get(pid)
        return projects.list_photos(pid)

    @app.post("/api/projects/{pid}/photos")
    async def upload_photos(pid: str, files: list[UploadFile] = File(...), _: Principal = Depends(principal)):
        projects.get(pid)
        added, rejected = [], []
        for f in files:
            try:
                info = await run_in_threadpool(projects.add_photo, pid, f.filename or "photo.jpg", f.file)
                added.append(info)
            except ProjectError as e:
                rejected.append({"file": f.filename, "error": str(e), "status": e.status})
            finally:
                await f.close()
        if not added and rejected:
            return JSONResponse({"added": [], "rejected": rejected}, status_code=rejected[0]["status"])
        return {"added": added, "rejected": rejected, "photo_count": projects.get(pid)["photo_count"]}

    @app.get("/api/projects/{pid}/photos/{name}")
    def get_photo(pid: str, name: str, thumb: bool = False, _: Principal = Depends(principal)):
        f = projects.photo_path(pid, name)
        if not thumb:
            return FileResponse(f)
        from PIL import Image, ImageOps

        img = ImageOps.exif_transpose(Image.open(f)).convert("RGB")
        img.thumbnail((320, 320))
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=80)
        return Response(buf.getvalue(), media_type="image/jpeg")

    @app.delete("/api/projects/{pid}/photos/{name}")
    def delete_photo(pid: str, name: str, _: Principal = Depends(principal)):
        projects.delete_photo(pid, name)
        return {"deleted": name}

    VIDEO_EXT = {".mp4", ".mov", ".m4v", ".webm", ".mkv", ".avi", ".3gp"}

    @app.post("/api/projects/{pid}/video", status_code=202)
    async def upload_video(pid: str, file: UploadFile = File(...), _: Principal = Depends(principal)):
        p = projects.get(pid)
        if p["status"] in ("queued", "processing") or jobs.active_job(pid):
            raise HTTPException(409, "Un traitement est déjà en cours pour ce projet")
        if not system(_)["video_import_available"]:
            raise HTTPException(503, "FFmpeg n'est pas installé : import vidéo indisponible")
        from .projects import safe_filename

        ext = Path(file.filename or "").suffix.lower()
        if ext not in VIDEO_EXT:
            raise HTTPException(415, f"Format vidéo non pris en charge : {ext or 'inconnu'} (MP4, MOV, WebM…)")
        name = safe_filename(file.filename or f"video{ext}")
        dest_dir = projects.path(pid) / "originals" / "videos"
        dest_dir.mkdir(parents=True, exist_ok=True)
        stem, i, dest = Path(name).stem, 1, dest_dir / name
        while dest.exists():
            dest = dest_dir / f"{stem}_{i}{ext}"
            i += 1
        limit = settings.max_video_mb * 1024 * 1024
        size = 0
        try:
            with open(dest, "wb") as out:
                while chunk := await file.read(4 * 1024 * 1024):
                    size += len(chunk)
                    if size > limit:
                        raise HTTPException(413, f"Vidéo trop volumineuse (maximum {settings.max_video_mb} Mo)")
                    out.write(chunk)
        except HTTPException:
            dest.unlink(missing_ok=True)
            raise
        finally:
            await file.close()
        if size == 0:
            dest.unlink(missing_ok=True)
            raise HTTPException(400, "Fichier vide")
        return jobs.submit(pid, "video", "fast", [], params={"video": dest.name})

    # ------------------------------------------------------------------ jobs
    @app.post("/api/projects/{pid}/reconstruct", status_code=202)
    def reconstruct(pid: str, body: ReconstructRequest, _: Principal = Depends(principal)):
        sysinfo = system(_)
        if not sysinfo["reconstruction_available"]:
            raise HTTPException(503, "Moteur de reconstruction indisponible (COLMAP/OpenMVS manquant) : lancez « cam3d doctor »")
        return jobs.submit(pid, "reconstruct", body.profile, body.formats, body.resume)

    @app.get("/api/projects/{pid}/jobs")
    def project_jobs(pid: str, _: Principal = Depends(principal)):
        projects.get(pid)
        return jobs.list(pid)

    @app.get("/api/jobs")
    def all_jobs(_: Principal = Depends(principal)):
        return jobs.list()

    @app.get("/api/jobs/{jid}")
    def get_job(jid: str, _: Principal = Depends(principal)):
        return jobs.get(jid, with_events=True)

    @app.post("/api/jobs/{jid}/cancel")
    def cancel_job(jid: str, _: Principal = Depends(principal)):
        return jobs.cancel(jid)

    @app.post("/api/jobs/{jid}/retry", status_code=202)
    def retry_job(jid: str, _: Principal = Depends(principal)):
        return jobs.retry(jid)

    # ------------------------------------------------------------------ logs
    @app.get("/api/projects/{pid}/logs")
    def list_logs(pid: str, _: Principal = Depends(principal)):
        d = projects.path(pid) / "logs"
        projects.get(pid)
        return [{"name": f.stem, "size_bytes": f.stat().st_size} for f in sorted(d.glob("*.log"))]

    @app.get("/api/projects/{pid}/logs/{name}", response_class=PlainTextResponse)
    def get_log(pid: str, name: str, tail: int = Query(400, ge=1, le=20000), _: Principal = Depends(principal)):
        if name not in LOG_STAGES:
            raise HTTPException(404, "Journal inconnu")
        f = projects.path(pid) / "logs" / f"{name}.log"
        projects.get(pid)
        if not f.exists():
            raise HTTPException(404, "Journal vide")
        lines = f.read_text(encoding="utf-8", errors="replace").splitlines()
        return "\n".join(lines[-tail:])

    # ------------------------------------------------------------------ exports
    @app.get("/api/projects/{pid}/exports")
    def list_exports(pid: str, _: Principal = Depends(principal)):
        return projects.list_exports(pid)

    @app.post("/api/projects/{pid}/exports", status_code=202)
    def request_export(pid: str, body: ExportRequest, _: Principal = Depends(principal)):
        if body.sketchup_level:
            from ..engine.sketchup import LEVELS

            if body.sketchup_level not in LEVELS:
                raise HTTPException(400, "Niveau SketchUp inconnu (light, standard, detailed)")
            return jobs.submit(pid, "sketchup", "fast", [], params={"level": body.sketchup_level})
        return jobs.submit(pid, "export", "fast", body.formats)

    # ------------------------------------------------------------------ editing (non destructive)
    from ..engine.edit import EditError, EditState, validate_op

    def _edits_path(pid: str) -> Path:
        return projects.path(pid) / "processed" / "edits.json"

    @app.get("/api/projects/{pid}/edits")
    def get_edits(pid: str, _: Principal = Depends(principal)):
        projects.get(pid)
        return {"ops": EditState.load(_edits_path(pid)).ops}

    @app.post("/api/projects/{pid}/edits", status_code=202)
    def add_edit(pid: str, body: EditRequest, _: Principal = Depends(principal)):
        try:
            op = validate_op(body.op)
        except EditError as e:
            raise HTTPException(400, str(e))
        ops = EditState.load(_edits_path(pid)).ops + [op]
        return jobs.submit(pid, "edit", "fast", [], params={"ops": ops, "action": op["type"]})

    @app.post("/api/projects/{pid}/edits/undo", status_code=202)
    def undo_edit(pid: str, _: Principal = Depends(principal)):
        ops = EditState.load(_edits_path(pid)).ops
        if not ops:
            raise HTTPException(409, "Aucune modification à annuler")
        return jobs.submit(pid, "edit", "fast", [], params={"ops": ops[:-1], "action": "undo"})

    @app.post("/api/projects/{pid}/edits/reset", status_code=202)
    def reset_edits(pid: str, confirm: bool = False, _: Principal = Depends(principal)):
        if not confirm:
            raise HTTPException(400, "Confirmation requise (?confirm=true) : toutes les modifications seront retirées")
        return jobs.submit(pid, "edit", "fast", [], params={"ops": [], "action": "reset"})

    # ------------------------------------------------------------------ scale calibration
    def _calib_path(pid: str) -> Path:
        return projects.path(pid) / "processed" / "calibration.json"

    @app.put("/api/projects/{pid}/calibration")
    def set_calibration(pid: str, body: CalibrationRequest, _: Principal = Depends(principal)):
        projects.get(pid)
        if jobs.active_job(pid):
            raise HTTPException(409, "Un traitement est en cours pour ce projet")
        import numpy as np

        d_model = float(np.linalg.norm(np.subtract(body.p2, body.p1)))
        if d_model <= 1e-9:
            raise HTTPException(400, "Les deux points sont confondus")
        metres = body.distance * {"mm": 1e-3, "cm": 1e-2, "m": 1.0}[body.unit]
        calib = {"method": "manual", "metres_per_unit": metres / d_model, "p1": body.p1, "p2": body.p2,
                 "distance": body.distance, "unit": body.unit, "model_distance": d_model, "created_at": time.time()}
        _calib_path(pid).write_text(json.dumps(calib, indent=2), encoding="utf-8")
        _clear_exports(pid)
        projects.set_status(pid, projects.get(pid)["status"])  # touch + metadata.json
        return calib

    @app.delete("/api/projects/{pid}/calibration")
    def delete_calibration(pid: str, _: Principal = Depends(principal)):
        projects.get(pid)
        if jobs.active_job(pid):
            raise HTTPException(409, "Un traitement est en cours pour ce projet")
        _calib_path(pid).unlink(missing_ok=True)
        _clear_exports(pid)
        return {"method": None}

    def _clear_exports(pid: str) -> None:
        import shutil

        d = projects.path(pid) / "exports"
        shutil.rmtree(d, ignore_errors=True)
        d.mkdir(exist_ok=True)

    @app.get("/api/projects/{pid}/exports/{filename}")
    def download_export(pid: str, filename: str, _: Principal = Depends(principal)):
        f = projects.export_path(pid, filename)
        name = projects.get(pid)["name"]
        nice = "".join(c if c.isalnum() or c in "-_ " else "_" for c in name).strip() or "cam3d"
        return FileResponse(f, filename=f"{nice}_{f.name}")

    # ------------------------------------------------------------------ TLS (phone camera)
    def _tls_state() -> dict:
        st = getattr(app.state, "tls", None) or {}
        return {"enabled": bool(st.get("enabled")), "https_port": st.get("https_port"),
                "http_port": st.get("http_port"), "ca": ca_info(TlsPaths(settings.tls_dir)) if st.get("enabled") else None}

    @app.get("/api/tls")
    def tls_info():
        return _tls_state()  # public, non-sensitive: the phone needs it before pairing

    @app.get("/api/tls/ca.crt")
    def tls_ca():
        f = TlsPaths(settings.tls_dir).ca_crt
        if not f.exists():
            raise HTTPException(404, "HTTPS local non activé")
        return FileResponse(f, media_type="application/x-x509-ca-cert", filename="cam3d-ca.crt")

    # ------------------------------------------------------------------ pairing
    @app.post("/api/pair/sessions", status_code=201)
    def pair_session(request: Request, next: str = "", _: Principal = Depends(desktop_only)):
        s = pairing.create_session()
        tls = _tls_state()
        http_port = tls["http_port"] or request.url.port or 80
        nxt = f"&next={quote(next, safe='')}" if next.startswith("/") else ""
        ips = lan_addresses()
        # The QR opens the setup page over HTTP (works before any certificate is installed);
        # it then offers HTTPS (camera in the browser) or plain HTTP (gallery / native camera).
        urls = [f"http://{ip}:{http_port}/setup/?code={s.code}{nxt}" for ip in ips]
        https_urls = [f"https://{ip}:{tls['https_port']}/pair/?code={s.code}{nxt}" for ip in ips] if tls["enabled"] else []
        return {"id": s.id, "code": s.code, "expires_at": s.expires_at, "urls": urls, "https_urls": https_urls,
                "secure": tls["enabled"]}

    @app.get("/api/pair/qr.svg")
    def pair_qr(url: str, _: Principal = Depends(desktop_only)):
        import qrcode
        import qrcode.image.svg

        img = qrcode.make(url, image_factory=qrcode.image.svg.SvgPathImage, box_size=10)
        buf = io.BytesIO()
        img.save(buf)
        return Response(buf.getvalue(), media_type="image/svg+xml")

    @app.post("/api/pair/claim", status_code=201)
    def pair_claim(body: PairClaim):
        r = pairing.claim(body.code, body.device_name)
        return {"request_id": r.id, "secret": r.secret, "status": r.status}

    @app.get("/api/pair/requests/{rid}")
    def pair_poll(rid: str, secret: str, request: Request):
        res = pairing.poll(rid, secret)
        if res.get("token"):
            # The phone's browser also receives the token as an HttpOnly cookie so that
            # <img>, model downloads and the WebSocket are authorised without exposing
            # it in URLs (and therefore in access logs).
            resp = JSONResponse(res)
            resp.set_cookie(TOKEN_COOKIE, res["token"], max_age=settings.device_token_ttl_s, httponly=True,
                            samesite="strict", secure=request.url.scheme == "https")
            return resp
        return res

    @app.get("/api/pair/pending")
    def pair_pending(_: Principal = Depends(desktop_only)):
        return [{"id": r.id, "device_name": r.device_name, "created_at": r.created_at} for r in pairing.pending()]

    @app.post("/api/pair/requests/{rid}/approve")
    def pair_approve(rid: str, _: Principal = Depends(desktop_only)):
        r = pairing.decide(rid, True)
        return {"id": r.id, "status": r.status}

    @app.post("/api/pair/requests/{rid}/reject")
    def pair_reject(rid: str, _: Principal = Depends(desktop_only)):
        r = pairing.decide(rid, False)
        return {"id": r.id, "status": r.status}

    @app.get("/api/devices")
    def devices(_: Principal = Depends(desktop_only)):
        return pairing.list_devices()

    @app.delete("/api/devices/{did}")
    def revoke_device(did: str, _: Principal = Depends(desktop_only)):
        pairing.revoke(did)
        return {"revoked": did}

    @app.get("/api/whoami")
    def whoami(request: Request):
        # Auth probe used by the UI before pairing: answers 200 with role "anonymous"
        # rather than 401 (every other route still requires authorisation).
        p = _principal_from(request.client.host if request.client else "", request.headers, request.query_params, request.cookies)
        return {"role": p.role, "name": p.name} if p else {"role": "anonymous", "name": ""}

    # ------------------------------------------------------------------ events
    @app.websocket("/api/events")
    async def events(ws: WebSocket):
        p = _principal_from(ws.client.host if ws.client else "", ws.headers, ws.query_params, ws.cookies)
        if p is None:
            await ws.close(code=4401)
            return
        await ws.accept()
        q = jobs.subscribe()
        try:
            while True:
                try:
                    msg = await asyncio.wait_for(q.get(), timeout=20)
                except asyncio.TimeoutError:
                    msg = {"type": "ping"}
                await ws.send_json(msg)
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            jobs.unsubscribe(q)

    # ------------------------------------------------------------------ web UI (phase 4)
    ui = Path(__file__).resolve().parents[3] / "frontend" / "out"
    if ui.is_dir():
        app.mount("/", StaticFiles(directory=ui, html=True), name="ui")

    return app
