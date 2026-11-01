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
import time
import traceback
from dataclasses import dataclass, asdict, field
from pathlib import Path

from . import __name__ as _pkg  # noqa: F401
from .events import CancelToken, CancelledError, EventCallback, Stage, StageEvent, StageLogger
from .mesh_io import TexturedModel, load_model, write_obj
from .profiles import QualityProfile, get_profile
from .stages.cleanup import run_cleanup
from .stages.export import run_exports, ExportResult, export_glb
from .stages.mvs import DenseResult, MeshResult, TextureResult, run_densify, run_mesh, run_refine, run_texture
from .stages.prepare import prepare_images
from .stages.sfm import SfmResult, run_sfm
from .subprocess_utils import ToolError
from .tools import ToolRegistry, discover_tools

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

            # 7. cleanup + canonical frame -----------------------------------
            current = Stage.CLEANUP
            lg = self._logger(current, project)
            try:
                model = load_model(Path(tex.obj_path))
                run_cleanup(model, lg, sfm.up_vector, self.cancel, report_path=work / "cleanup.json")
            finally:
                lg.close()
            # persist the canonical textured model inside the project
            for old in list((project / "meshes").glob(f"{model_name}*")) + list((project / "textures").glob(f"{model_name}*")):
                old.unlink()
            textures = write_obj(model, project / "meshes" / f"{model_name}.obj", texture_dir=project / "textures",
                                 texture_rel="../textures/")
            preview = export_glb(model, project / "previews", model_name)
            result.model_obj = str(project / "meshes" / f"{model_name}.obj")
            result.preview_glb = preview.path
            result.num_faces = model.num_faces
            result.num_vertices = model.num_vertices
            result.textures = [str(t) for t in textures]

            # 8. exports ------------------------------------------------------
            current = Stage.EXPORT
            if export_formats:
                lg = self._logger(current, project)
                try:
                    exports = run_exports(model, project / "exports", model_name, tuple(export_formats), lg, self.cancel,
                                          point_cloud=project / "reconstruction" / "dense.ply", unit_scale=model.unit_scale)
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
