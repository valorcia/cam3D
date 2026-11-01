"""Project library: creation, photos, metadata, files.

SQLite is the index used for listing; every change is mirrored into
``<project>/metadata.json`` so a project folder stays self-describing
(copy it to another machine and it can be re-imported).
"""
from __future__ import annotations

import io
import json
import re
import shutil
import unicodedata
import uuid
from pathlib import Path
from typing import BinaryIO

import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError

from ..engine.stages.prepare import sharpness_score
from .config import Settings
from .db import Database, now

PHOTO_EXT = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp", ".tif", ".tiff"}
PROJECT_SUBDIRS = ("originals", "processed", "reconstruction", "meshes", "textures", "previews", "exports", "logs")
_ID_RE = re.compile(r"^[a-f0-9]{12}$")


class ProjectError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def safe_filename(name: str) -> str:
    """ASCII, no path components, no leading dots; keeps the extension."""
    name = Path(name.replace("\\", "/")).name
    name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._")
    return name[:120] or "photo"


class ProjectStore:
    def __init__(self, settings: Settings, db: Database) -> None:
        self.settings = settings
        self.db = db
        settings.ensure_dirs()

    # ------------------------------------------------------------- helpers
    def path(self, project_id: str) -> Path:
        if not _ID_RE.match(project_id or ""):
            raise ProjectError("Identifiant de projet invalide", 404)
        return self.settings.projects_dir / project_id

    def get(self, project_id: str) -> dict:
        row = self.db.one("SELECT * FROM projects WHERE id = ?", (project_id,))
        if not row or not self.path(project_id).exists():
            raise ProjectError("Projet introuvable", 404)
        row["archived"] = bool(row["archived"])
        row["calibration"] = json.loads(row["calibration"]) if row.get("calibration") else None
        row["has_model"] = (self.path(project_id) / "previews" / "model.glb").exists()
        row["has_thumbnail"] = (self.path(project_id) / "previews" / "thumb.jpg").exists()
        row["thumbnail_3d"] = (self.path(project_id) / "previews" / "thumb_3d").exists()
        return row

    def _touch(self, project_id: str, **values) -> None:
        values["updated_at"] = now()
        self.db.update("projects", {"id": project_id}, values)
        self.write_metadata(project_id)

    def write_metadata(self, project_id: str) -> None:
        p = self.get(project_id)
        p["photos"] = self.list_photos(project_id)
        p["format"] = "cam3d-project/1"
        (self.path(project_id) / "metadata.json").write_text(json.dumps(p, indent=2, ensure_ascii=False), encoding="utf-8")

    # ------------------------------------------------------------- CRUD
    def create(self, name: str) -> dict:
        name = (name or "").strip() or "Nouveau scan"
        if len(name) > 120:
            raise ProjectError("Nom trop long (120 caractères maximum)")
        pid = uuid.uuid4().hex[:12]
        root = self.path(pid)
        for sub in PROJECT_SUBDIRS:
            (root / sub).mkdir(parents=True, exist_ok=True)
        t = now()
        self.db.insert("projects", {"id": pid, "name": name, "created_at": t, "updated_at": t, "status": "empty"})
        self.write_metadata(pid)
        return self.get(pid)

    def list(self, include_archived: bool = False) -> list[dict]:
        rows = self.db.all("SELECT id FROM projects ORDER BY updated_at DESC")
        out = []
        for r in rows:
            try:
                p = self.get(r["id"])
            except ProjectError:
                continue
            if p["archived"] and not include_archived:
                continue
            out.append(p)
        return out

    def rename(self, project_id: str, name: str) -> dict:
        self.get(project_id)
        name = (name or "").strip()
        if not name or len(name) > 120:
            raise ProjectError("Nom invalide (1 à 120 caractères)")
        self._touch(project_id, name=name)
        return self.get(project_id)

    def set_archived(self, project_id: str, archived: bool) -> dict:
        self.get(project_id)
        self._touch(project_id, archived=1 if archived else 0)
        return self.get(project_id)

    def duplicate(self, project_id: str) -> dict:
        src = self.get(project_id)
        if src["status"] in ("queued", "processing"):
            raise ProjectError("Impossible de dupliquer un projet en cours de traitement", 409)
        new_id = uuid.uuid4().hex[:12]
        shutil.copytree(self.path(project_id), self.path(new_id))
        t = now()
        values = {k: src[k] for k in ("status", "photo_count", "profile", "model_faces", "model_size_bytes")}
        values["status"] = "done" if src["status"] == "done" else ("ready" if src["photo_count"] else "empty")
        self.db.insert("projects", {"id": new_id, "name": f"{src['name']} (copie)", "created_at": t, "updated_at": t,
                                    "calibration": json.dumps(src["calibration"]) if src["calibration"] else None, **values})
        for ph in self.db.all("SELECT * FROM photos WHERE project_id = ?", (project_id,)):
            ph["project_id"] = new_id
            self.db.insert("photos", ph)
        self.write_metadata(new_id)
        return self.get(new_id)

    def delete(self, project_id: str) -> None:
        p = self.get(project_id)
        if p["status"] in ("queued", "processing"):
            raise ProjectError("Annulez le traitement en cours avant de supprimer le projet", 409)
        shutil.rmtree(self.path(project_id), ignore_errors=True)
        self.db.execute("DELETE FROM photos WHERE project_id = ?", (project_id,))
        self.db.execute("DELETE FROM jobs WHERE project_id = ?", (project_id,))
        self.db.execute("DELETE FROM projects WHERE id = ?", (project_id,))

    def set_status(self, project_id: str, status: str, **extra) -> None:
        try:
            self._touch(project_id, status=status, **extra)
        except ProjectError:
            pass  # project deleted meanwhile

    # ------------------------------------------------------------- photos
    def list_photos(self, project_id: str) -> list[dict]:
        rows = self.db.all("SELECT * FROM photos WHERE project_id = ? ORDER BY name", (project_id,))
        for r in rows:
            r["warnings"] = json.loads(r["warnings"]) if r.get("warnings") else []
            r.pop("project_id", None)
        return rows

    def add_photo(self, project_id: str, filename: str, stream: BinaryIO) -> dict:
        p = self.get(project_id)
        if p["status"] in ("queued", "processing"):
            raise ProjectError("Traitement en cours : ajout de photos impossible", 409)
        if p["photo_count"] >= self.settings.max_photos_per_project:
            raise ProjectError(f"Limite de {self.settings.max_photos_per_project} photos atteinte", 413)
        ext = Path(filename or "").suffix.lower()
        if ext not in PHOTO_EXT:
            raise ProjectError(f"Format non pris en charge : {ext or 'inconnu'} (JPEG, PNG, HEIC, WebP, TIFF)", 415)
        limit = self.settings.max_photo_mb * 1024 * 1024
        buf = io.BytesIO()
        while True:
            chunk = stream.read(1024 * 1024)
            if not chunk:
                break
            buf.write(chunk)
            if buf.tell() > limit:
                raise ProjectError(f"Fichier trop volumineux (maximum {self.settings.max_photo_mb} Mo)", 413)
        data = buf.getvalue()
        if len(data) == 0:
            raise ProjectError("Fichier vide", 400)
        # validate that this really is a decodable image (not just a renamed file)
        if ext in {".heic", ".heif"}:
            try:
                import pillow_heif

                pillow_heif.register_heif_opener()
            except ImportError:
                raise ProjectError("HEIC non pris en charge sur cet ordinateur : réglez l'iPhone sur « Le plus compatible » (JPEG)", 415)
        try:
            with Image.open(io.BytesIO(data)) as probe:
                probe.verify()
            img = ImageOps.exif_transpose(Image.open(io.BytesIO(data)))
            img.load()
        except (UnidentifiedImageError, OSError, SyntaxError) as e:
            raise ProjectError(f"Image illisible ou corrompue ({e.__class__.__name__})", 415)
        w, h = img.size
        if min(w, h) < 480:
            raise ProjectError(f"Résolution trop faible ({w}×{h}) : 640×480 minimum", 422)
        gray = np.asarray(img.convert("L"))
        sharp = sharpness_score(gray)
        bright = float(gray.mean())
        warnings = []
        if sharp < 25:
            warnings.append("floue")
        if bright < 30:
            warnings.append("trop sombre")
        elif bright > 235:
            warnings.append("surexposée")

        name = safe_filename(filename)
        if Path(name).suffix.lower() != ext:
            name = f"{Path(name).stem}{ext}"
        originals = self.path(project_id) / "originals"
        stem, i = Path(name).stem, 1
        while (originals / name).exists():
            name = f"{stem}_{i}{ext}"
            i += 1
        (originals / name).write_bytes(data)  # original bytes, untouched (EXIF kept)

        thumb = self.path(project_id) / "previews" / "thumb.jpg"
        if not thumb.exists():
            t = img.convert("RGB")
            t.thumbnail((512, 512))
            t.save(thumb, "JPEG", quality=85)
        self.db.insert("photos", {"project_id": project_id, "name": name, "size_bytes": len(data), "width": w, "height": h,
                                  "sharpness": round(sharp, 1), "brightness": round(bright, 1),
                                  "warnings": warnings, "created_at": now()})
        count = self.db.one("SELECT COUNT(*) AS n FROM photos WHERE project_id = ?", (project_id,))["n"]
        status = p["status"] if p["status"] not in ("empty",) else "ready"
        self._touch(project_id, photo_count=count, status=status)
        return {"name": name, "size_bytes": len(data), "width": w, "height": h,
                "sharpness": round(sharp, 1), "brightness": round(bright, 1), "warnings": warnings}

    def add_zip(self, project_id: str, filename: str, stream: BinaryIO) -> tuple[list[dict], list[dict]]:
        """Photos packed in a ZIP (e.g. exported by cam3D Capture). Only image members are read,
        names are flattened (no path traversal), sizes are checked before extraction."""
        import tempfile
        import zipfile

        added: list[dict] = []
        rejected: list[dict] = []
        limit_total = self.settings.max_video_mb * 1024 * 1024
        with tempfile.TemporaryFile() as tmp:
            size = 0
            while chunk := stream.read(4 * 1024 * 1024):
                size += len(chunk)
                if size > limit_total:
                    raise ProjectError(f"Archive trop volumineuse (maximum {self.settings.max_video_mb} Mo)", 413)
                tmp.write(chunk)
            tmp.seek(0)
            try:
                zf = zipfile.ZipFile(tmp)
            except zipfile.BadZipFile:
                raise ProjectError("Archive ZIP illisible", 415)
            members = [m for m in zf.infolist() if not m.is_dir() and Path(m.filename).suffix.lower() in PHOTO_EXT
                       and not Path(m.filename).name.startswith(".")]
            if not members:
                raise ProjectError("Aucune photo dans cette archive", 422)
            for m in members:
                name = Path(m.filename.replace("\\", "/")).name
                if m.file_size > self.settings.max_photo_mb * 1024 * 1024:
                    rejected.append({"file": name, "error": f"Fichier trop volumineux (maximum {self.settings.max_photo_mb} Mo)", "status": 413})
                    continue
                try:
                    with zf.open(m) as fh:
                        added.append(self.add_photo(project_id, name, fh))
                except ProjectError as e:
                    rejected.append({"file": name, "error": str(e), "status": e.status})
        return added, rejected

    def delete_photo(self, project_id: str, name: str) -> None:
        p = self.get(project_id)
        if p["status"] in ("queued", "processing"):
            raise ProjectError("Traitement en cours : suppression impossible", 409)
        name = safe_filename(name)
        f = self.path(project_id) / "originals" / name
        if not f.exists():
            raise ProjectError("Photo introuvable", 404)
        f.unlink()
        self.db.execute("DELETE FROM photos WHERE project_id = ? AND name = ?", (project_id, name))
        count = self.db.one("SELECT COUNT(*) AS n FROM photos WHERE project_id = ?", (project_id,))["n"]
        self._touch(project_id, photo_count=count, status=p["status"] if count else "empty")

    def photo_path(self, project_id: str, name: str) -> Path:
        self.get(project_id)
        f = self.path(project_id) / "originals" / safe_filename(name)
        if not f.exists():
            raise ProjectError("Photo introuvable", 404)
        return f

    # ------------------------------------------------------------- results
    def refresh_model_info(self, project_id: str) -> None:
        root = self.path(project_id)
        res_file = root / "pipeline_result.json"
        faces = None
        pv = root / "previews" / "preview.json"
        if pv.exists():
            try:
                faces = json.loads(pv.read_text(encoding="utf-8")).get("full_faces")
            except ValueError:
                faces = None
        if faces is None and res_file.exists():
            try:
                faces = json.loads(res_file.read_text(encoding="utf-8")).get("num_faces")
            except Exception:
                faces = None
        size = sum(f.stat().st_size for d in ("meshes", "textures") for f in (root / d).glob("*") if f.is_file())
        self._touch(project_id, model_faces=faces, model_size_bytes=size or None)

    def list_exports(self, project_id: str) -> list[dict]:
        d = self.path(project_id) / "exports"
        meta = {}
        if (d / "exports.json").exists():
            try:
                for e in json.loads((d / "exports.json").read_text(encoding="utf-8")):
                    meta[Path(e["path"]).name] = e
            except Exception:
                pass
        out = []
        for f in sorted(d.glob("*")):
            if f.is_file() and f.name != "exports.json":
                e = meta.get(f.name, {})
                out.append({"file": f.name, "size_bytes": f.stat().st_size, "format": e.get("format"),
                            "textured": e.get("textured"), "note": e.get("note", "")})
        return out

    def export_path(self, project_id: str, filename: str) -> Path:
        self.get(project_id)
        f = self.path(project_id) / "exports" / safe_filename(filename)
        if not f.is_file():
            raise ProjectError("Export introuvable", 404)
        return f

    def set_thumbnail(self, project_id: str, data: bytes) -> None:
        self.get(project_id)
        if len(data) > 5 * 1024 * 1024:
            raise ProjectError("Miniature trop volumineuse", 413)
        try:
            img = Image.open(io.BytesIO(data))
            img.load()
        except Exception:
            raise ProjectError("Miniature illisible", 415)
        img = img.convert("RGB")
        img.thumbnail((512, 512))
        img.save(self.path(project_id) / "previews" / "thumb.jpg", "JPEG", quality=85)
        (self.path(project_id) / "previews" / "thumb_3d").write_text("1", encoding="utf-8")  # rendered from the model
        self._touch(project_id)
