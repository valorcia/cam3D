"""End-to-end reconstruction pipeline.

Project folder layout (see ARCHITECTURE.md)::

    <project>/
        metadata.json
        originals/          user photos (never modified)
        processed/          working copies + COLMAP/OpenMVS workspaces
            images/  database.db  sparse/  dense/  mvs/  images.json  sfm.json
            stages/<stage>.json      per-stage results (resume support)
        reconstruction/     sparse.ply, dense.ply
        meshes/             model.obj + model.mtl (textured, cleaned, Y up)
        textures/           model_<i>.jpg
        previews/           model.glb (browser preview)
        exports/            user exports (zip bundles, glb, stl, ply)
        logs/               one log per stage + pipeline.log

The pipeline is synchronous; the server runs it in a worker thread/process
and consumes :class:`StageEvent` objects through ``callback``.
"""
from __future__ import annotations

import json
import os
import shutil

import numpy as np
import time
import traceback
from dataclasses import dataclass, asdict, field
from pathlib import Path

from . import __name__ as _pkg  # noqa: F401
from .events import CancelToken, CancelledError, EventCallback, Stage, StageEvent, StageLogger
from .mesh_io import TexturedModel, load_model, write_obj
from .profiles import QualityProfile, get_profile
from .stages.cleanup import remove_small_components, run_cleanup
from .stages.export import ExportResult, export_glb, run_exports
from .stages.mvs import (DenseResult, MeshResult, TextureResult, decimate_mesh, run_densify, run_mesh, run_refine,
                         run_texture)
from .stages.prepare import prepare_images
from .stages.sfm import SfmResult, run_sfm
from .subprocess_utils import ToolError
from .tools import ToolRegistry, discover_tools
from .events import fmt_int

PREVIEW_MAX_FACES = 250_000      # above this, the browser preview is a decimated, re-textured copy
PREVIEW_TARGET_FACES = 200_000
PREVIEW_MAX_POINTS = 500_000     # point cloud shown in the viewer (≈7.5 Mo)


class _LogOnly:
    """Logger adapter: sub-steps of a stage are reported as log lines only."""

    def __init__(self, parent: StageLogger) -> None:
        self.p = parent

    def start(self, message: str = "") -> None:
        if message:
            self.p.log(message)

    def log(self, message: str) -> None:
        self.p.log(message)

    def progress(self, value: float, message: str = "") -> None:
        pass

    def raw(self, line: str) -> None:
        self.p.raw(line)

    def finish(self, message: str = "", **_) -> float:
        if message:
            self.p.log(message)
        return 0.0

    def fail(self, message: str, **_) -> None:
        self.p.log(message)

    def skip(self, message: str) -> None:
        self.p.log(message)


def write_aligned_pointclouds(dense_ply: Path, transform: np.ndarray, full_out: Path, preview_out: Path,
                              max_points: int = PREVIEW_MAX_POINTS) -> int:
    """Dense cloud expressed in the model's canonical frame (full + subsampled copy)."""
    import open3d as o3d

    pc = o3d.io.read_point_cloud(str(dense_ply))
    n = len(pc.points)
    if n == 0:
        return 0
    pc.transform(np.asarray(transform, dtype=np.float64))
    pc.normals = o3d.utility.Vector3dVector(np.zeros((0, 3)))
    o3d.io.write_point_cloud(str(full_out), pc, write_ascii=False)
    if n > max_points:
        pc = pc.random_down_sample(max_points / n)
    write_ply_points(preview_out, np.asarray(pc.points), np.asarray(pc.colors) if pc.has_colors() else None)
    return len(pc.points)


def write_ply_points(path: Path, xyz: np.ndarray, rgb01: np.ndarray | None) -> None:
    """Compact binary PLY: float32 xyz (+ uint8 rgb) = 15 bytes/point."""
    n = len(xyz)
    fields = [("x", "<f4"), ("y", "<f4"), ("z", "<f4")]
    if rgb01 is not None and len(rgb01) == n:
        fields += [("red", "u1"), ("green", "u1"), ("blue", "u1")]
    arr = np.empty(n, dtype=fields)
    arr["x"], arr["y"], arr["z"] = xyz[:, 0], xyz[:, 1], xyz[:, 2]
    header = ["ply", "format binary_little_endian 1.0", f"element vertex {n}",
              "property float x", "property float y", "property float z"]
    if len(fields) == 6:
        c = np.clip(np.round(rgb01 * 255), 0, 255).astype(np.uint8)
        arr["red"], arr["green"], arr["blue"] = c[:, 0], c[:, 1], c[:, 2]
        header += ["property uchar red", "property uchar green", "property uchar blue"]
    header.append("end_header")
    with open(path, "wb") as fh:
        fh.write(("\n".join(header) + "\n").encode("ascii"))
        fh.write(arr.tobytes())


ALL_STAGES = [Stage.PREPARE, Stage.SFM, Stage.DENSE, Stage.MESH, Stage.REFINE, Stage.TEXTURE, Stage.CLEANUP, Stage.EXPORT]


@dataclass
class PipelineResult:
    success: bool
    project_dir: str
    profile: str
    duration_s: float
    stages: dict[str, dict] = field(default_factory=dict)   # stage -> {status, duration, ...}
    model_obj: str | None = None
    preview_glb: str | None = None
    num_faces: int | None = None
    num_vertices: int | None = None
    textures: list[str] = field(default_factory=list)
    exports: list[dict] = field(default_factory=list)
    error: str | None = None
    error_stage: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


class ReconstructionPipeline:
    def __init__(self, tools: ToolRegistry | None = None, callback: EventCallback | None = None,
                 cancel: CancelToken | None = None, threads: int = 0) -> None:
        self.tools = tools or discover_tools()
        self.callback = callback
        self.cancel = cancel or CancelToken()
        self.threads = threads or (os.cpu_count() or 2)
        self._stage_info: dict[str, dict] = {}

    # ------------------------------------------------------------------ utils
    def _cb(self, ev: StageEvent) -> None:
        info = self._stage_info.setdefault(ev.stage.value, {"status": "pending"})
        if ev.status in ("started", "finished", "failed", "skipped"):
            info["status"] = {"started": "running"}.get(ev.status, ev.status)
            if ev.status == "started":
                info["started_at"] = ev.timestamp
            if "duration" in ev.detail:
                info["duration"] = round(ev.detail["duration"], 2)
            info["message"] = ev.message
            for k, v in ev.detail.items():
                if k not in ("duration",) and isinstance(v, (int, float, str, bool, list)):
                    info[k] = v
        if self.callback:
            self.callback(ev)

    def _logger(self, stage: Stage, project: Path) -> StageLogger:
        return StageLogger(stage, project / "logs", self._cb)

    def check_requirements(self) -> list[str]:
        problems = []
        if not (self.tools.pycolmap and self.tools.pycolmap.available):
            problems.append("pycolmap n'est pas installé (pip install pycolmap).")
        if not self.tools.openmvs_available:
            missing = [b for b, t in self.tools.openmvs.items() if not t.available and b != "RefineMesh"]
            problems.append("OpenMVS introuvable (" + ", ".join(missing) + "). Voir INSTALLATION.md.")
        return problems

    # ------------------------------------------------------------------ main
    def run(self, source_images: Path, project_dir: Path, profile: QualityProfile | str = "fast",
            export_formats: tuple[str, ...] = ("obj", "glb", "dae"), model_name: str = "model",
            resume: bool = False) -> PipelineResult:
        t0 = time.time()
        profile = get_profile(profile) if isinstance(profile, str) else profile
        project = Path(project_dir)
        work = project / "processed"
        for sub in ("originals", "processed", "reconstruction", "meshes", "textures", "previews", "exports", "logs"):
            (project / sub).mkdir(parents=True, exist_ok=True)
        self._stage_info = {s.value: {"status": "pending"} for s in ALL_STAGES}
        result = PipelineResult(False, str(project), profile.name, 0.0, self._stage_info)
        plog = open(project / "logs" / "pipeline.log", "a", encoding="utf-8")
        plog.write(f"\n=== run {time.strftime('%Y-%m-%d %H:%M:%S')} profile={profile.name} resume={resume}\n")
        plog.write(f"tools: {json.dumps(self.tools.to_dict(), default=str)[:2000]}\n")

        problems = self.check_requirements()
        if problems:
            result.error = " ".join(problems)
            result.error_stage = Stage.PREPARE.value
            result.duration_s = time.time() - t0
            plog.write("requirements failed: " + result.error + "\n")
            plog.close()
            return result

        # copy originals (if the source is not already the project's originals folder)
        originals = project / "originals"
        source_images = Path(source_images)
        if source_images.resolve() != originals.resolve():
            for p in source_images.iterdir():
                if p.is_file() and not (originals / p.name).exists():
                    shutil.copy2(p, originals / p.name)

        stage_dir = work / "stages"
        stage_dir.mkdir(parents=True, exist_ok=True)

        def done(stage: Stage) -> dict | None:
            f = stage_dir / f"{stage.value}.json"
            if resume and f.exists():
                try:
                    d = json.loads(f.read_text(encoding="utf-8"))
                    if d.get("profile") == profile.name:
                        return d
                except Exception:
                    return None
            return None

        def save(stage: Stage, payload: dict) -> None:
            payload = dict(payload, profile=profile.name)
            (stage_dir / f"{stage.value}.json").write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")

        current = Stage.PREPARE
        try:
            # 1. prepare ------------------------------------------------------
            current = Stage.PREPARE
            if not done(current):
                lg = self._logger(current, project)
                try:
                    prepare_images(originals, work, profile, lg, self.cancel)
                finally:
                    lg.close()
                save(current, {"ok": True})
            else:
                self._cb(StageEvent(current, "skipped", "Préparation déjà effectuée (reprise)"))

            # 2. sfm ----------------------------------------------------------
            current = Stage.SFM
            d = done(current)
            if d:
                sfm = SfmResult(**{k: v for k, v in d.items() if k in SfmResult.__dataclass_fields__})
                self._cb(StageEvent(current, "skipped", "Caméras déjà estimées (reprise)"))
            else:
                lg = self._logger(current, project)
                try:
                    sfm = run_sfm(work, profile, lg, self.cancel, num_threads=self.threads)
                finally:
                    lg.close()
                save(current, asdict(sfm))
            shutil.copyfile(Path(sfm.sparse_dir) / "points.ply", project / "reconstruction" / "sparse.ply")

            # 3. dense --------------------------------------------------------
            current = Stage.DENSE
            d = done(current)
            if d and Path(d["dense_ply"]).exists():
                dense = DenseResult(**{k: v for k, v in d.items() if k in DenseResult.__dataclass_fields__})
                self._cb(StageEvent(current, "skipped", "Nuage dense déjà calculé (reprise)"))
            else:
                lg = self._logger(current, project)
                try:
                    dense = run_densify(work, profile, self.tools, lg, self.cancel, self.threads)
                finally:
                    lg.close()
                save(current, asdict(dense))
            shutil.copyfile(dense.dense_ply, project / "reconstruction" / "dense.ply")

            # 4. mesh ---------------------------------------------------------
            current = Stage.MESH
            d = done(current)
            if d and Path(d["mesh_ply"]).exists():
                mesh = MeshResult(**{k: v for k, v in d.items() if k in MeshResult.__dataclass_fields__})
                self._cb(StageEvent(current, "skipped", "Maillage déjà calculé (reprise)"))
            else:
                lg = self._logger(current, project)
                try:
                    mesh = run_mesh(work, profile, self.tools, lg, dense, self.cancel, self.threads)
                finally:
                    lg.close()
                save(current, asdict(mesh))

            # 5. refine (optional) -------------------------------------------
            current = Stage.REFINE
            lg = self._logger(current, project)
            try:
                mesh = run_refine(work, profile, self.tools, lg, mesh, self.cancel, self.threads)
            finally:
                lg.close()

            # 6. texture ------------------------------------------------------
            current = Stage.TEXTURE
            d = done(current)
            if d and Path(d["obj_path"]).exists():
                tex = TextureResult(**{k: v for k, v in d.items() if k in TextureResult.__dataclass_fields__})
                self._cb(StageEvent(current, "skipped", "Texturage déjà effectué (reprise)"))
            else:
                lg = self._logger(current, project)
                try:
                    tex = run_texture(work, profile, self.tools, lg, mesh, self.cancel, self.threads)
                finally:
                    lg.close()
                save(current, asdict(tex))

            # 7. cleanup + canonical frame + previews ------------------------
            current = Stage.CLEANUP
            lg = self._logger(current, project)
            try:
                model = load_model(Path(tex.obj_path))
                rep = run_cleanup(model, lg, sfm.up_vector, self.cancel, report_path=work / "cleanup.json",
                                  camera_center=sfm.camera_center)
                M = np.asarray(rep.transform)
                sub = _LogOnly(lg)
                # persist the canonical textured model inside the project
                for old in list((project / "meshes").glob(f"{model_name}*")) + list((project / "textures").glob(f"{model_name}*")):
                    old.unlink()
                for old in (project / "previews").glob("model*.glb"):
                    old.unlink()
                textures = write_obj(model, project / "meshes" / f"{model_name}.obj", texture_dir=project / "textures",
                                     texture_rel="../textures/")
                n_pts = write_aligned_pointclouds(Path(dense.dense_ply), M, project / "reconstruction" / "dense_aligned.ply",
                                                  project / "previews" / "pointcloud.ply")
                sub.log(f"Nuage de points aligné : {fmt_int(n_pts)} points pour l'aperçu")
                preview_info = {"decimated": False, "faces": model.num_faces, "full_faces": model.num_faces,
                                "pointcloud_points": n_pts}
                if model.num_faces > PREVIEW_MAX_FACES:
                    export_glb(model, project / "previews", f"{model_name}_full")
                    try:
                        sub.log(f"Aperçu allégé : décimation à {fmt_int(PREVIEW_TARGET_FACES)} faces puis re-texturage")
                        pply = decimate_mesh(mesh, PREVIEW_TARGET_FACES, self.tools, sub, self.cancel, self.threads)  # type: ignore[arg-type]
                        ptex = run_texture(work, profile, self.tools, sub, mesh, self.cancel, self.threads,  # type: ignore[arg-type]
                                           mesh_override=pply, output_name="preview", allow_raw_fallback=False)
                        pmodel = load_model(Path(ptex.obj_path))
                        remove_small_components(pmodel)
                        if pmodel.num_faces > PREVIEW_MAX_FACES:
                            raise RuntimeError(f"aperçu non allégé ({pmodel.num_faces} faces)")
                        pmodel.apply_transform(M)
                        export_glb(pmodel, project / "previews", model_name)
                        preview_info.update(decimated=True, faces=pmodel.num_faces)
                    except CancelledError:
                        raise
                    except Exception as e:  # preview is a convenience: never fail the run for it
                        sub.log(f"Aperçu allégé impossible ({e}) : l'aperçu utilisera le modèle complet")
                        export_glb(model, project / "previews", model_name)
                else:
                    export_glb(model, project / "previews", model_name)
                (project / "previews" / "preview.json").write_text(json.dumps(preview_info, indent=2), encoding="utf-8")
                # keep an untouched copy for non-destructive editing; a new reconstruction
                # also invalidates edits and the scale calibration (new geometry / scale)
                from .edit_runner import save_originals
                save_originals(project, model)
                (work / "calibration.json").unlink(missing_ok=True)
                sub.log("Copie originale du modèle conservée (les modifications ne la toucheront jamais)")
            finally:
                lg.close()
            result.model_obj = str(project / "meshes" / f"{model_name}.obj")
            result.preview_glb = str(project / "previews" / f"{model_name}.glb")
            result.num_faces = model.num_faces
            result.num_vertices = model.num_vertices
            result.textures = [str(t) for t in textures]

            # 8. exports ------------------------------------------------------
            current = Stage.EXPORT
            if export_formats:
                lg = self._logger(current, project)
                try:
                    exports = run_exports(model, project / "exports", model_name, tuple(export_formats), lg, self.cancel,
                                          point_cloud=project / "reconstruction" / "dense_aligned.ply", unit_scale=model.unit_scale)
                finally:
                    lg.close()
                result.exports = [asdict(e) for e in exports]
            else:
                self._cb(StageEvent(current, "skipped", "Aucun export demandé"))
            result.success = True
        except CancelledError as e:
            result.error = str(e)
            result.error_stage = current.value
            self._cb(StageEvent(current, "failed", str(e)))
        except ToolError as e:
            result.error = str(e)
            result.error_stage = current.value
            self._cb(StageEvent(current, "failed", str(e)))
            plog.write(traceback.format_exc())
        except Exception as e:  # noqa: BLE001
            result.error = f"{type(e).__name__}: {e}"
            result.error_stage = current.value
            self._cb(StageEvent(current, "failed", result.error))
            plog.write(traceback.format_exc())
        finally:
            result.duration_s = round(time.time() - t0, 1)
            result.stages = self._stage_info
            (project / "pipeline_result.json").write_text(json.dumps(result.to_dict(), indent=2), encoding="utf-8")
            plog.write(f"result: success={result.success} duration={result.duration_s}s error={result.error}\n")
            plog.close()
        return result
