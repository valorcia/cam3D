"""Replays the edit list on the project's original model and writes the results.

Inputs (written by the reconstruction pipeline, never modified afterwards):
  meshes/original/model.obj (+ .mtl, textures)   full textured model, canonical frame
  previews/original/model.glb                    browser preview (may be decimated)
  previews/original/pointcloud.ply               preview point cloud
  reconstruction/dense_aligned_original.ply      full dense cloud, canonical frame

Outputs (derived, regenerable):
  meshes/model.obj + textures/model_*.jpg, previews/model.glb (+ model_full.glb),
  previews/pointcloud.ply, reconstruction/dense_aligned.ply, previews/preview.json.
Existing exports are deleted because they no longer match the model.
"""
from __future__ import annotations

import copy
import hashlib
import json
import shutil
from pathlib import Path

import numpy as np

from .edit import EditError, EditState, apply_geometric_op, apply_to_points, rigid_matrix
from .events import CancelToken, StageLogger
from .mesh_io import TexturedModel, load_model, load_obj, write_obj
from .profiles import get_profile
from .retexture import simplify_and_retexture
from .stages.export import export_glb
from .tools import ToolRegistry
from .events import fmt_int

PREVIEW_MAX_FACES = 250_000


def _read_points(path: Path) -> tuple[np.ndarray, np.ndarray | None]:
    import open3d as o3d

    pc = o3d.io.read_point_cloud(str(path))
    return np.asarray(pc.points), (np.asarray(pc.colors) if pc.has_colors() else None)


def _write_points(path: Path, pts: np.ndarray, cols: np.ndarray | None, compact: bool) -> None:
    if compact:
        from .pipeline import write_ply_points

        write_ply_points(path, pts, cols)
        return
    import open3d as o3d

    pc = o3d.geometry.PointCloud(o3d.utility.Vector3dVector(pts))
    if cols is not None:
        pc.colors = o3d.utility.Vector3dVector(cols)
    o3d.io.write_point_cloud(str(path), pc, write_ascii=False)


def originals_exist(project: Path) -> bool:
    return (Path(project) / "meshes" / "original" / "model.obj").exists()


def save_originals(project: Path, model: TexturedModel, reset_edits: bool = True) -> None:
    """Called by the pipeline right after reconstruction (before any edit)."""
    project = Path(project)
    d = project / "meshes" / "original"
    if d.exists():
        shutil.rmtree(d)
    write_obj(model, d / "model.obj")  # self-contained: textures next to the OBJ
    pd = project / "previews" / "original"
    pd.mkdir(parents=True, exist_ok=True)
    for name in ("model.glb", "model_full.glb", "pointcloud.ply", "preview.json"):
        src = project / "previews" / name
        if src.exists():
            shutil.copyfile(src, pd / name)
        else:
            (pd / name).unlink(missing_ok=True)
    dense = project / "reconstruction" / "dense_aligned.ply"
    if dense.exists():
        shutil.copyfile(dense, project / "reconstruction" / "dense_aligned_original.ply")
    if reset_edits:
        EditState([]).save(project / "processed" / "edits.json")
        shutil.rmtree(project / "processed" / "edits_cache", ignore_errors=True)
        (project / "processed" / "edits_rigid.json").unlink(missing_ok=True)


def replay(project: Path, ops: list[dict], tools: ToolRegistry, logger: StageLogger,
           cancel: CancelToken | None = None) -> dict:
    project = Path(project)
    if not originals_exist(project):
        current = project / "meshes" / "model.obj"
        if not current.exists() or EditState.load(project / "processed" / "edits.json").ops:
            raise EditError("Aucun modèle original : reconstruisez d'abord le projet.")
        save_originals(project, load_obj(current), reset_edits=False)  # project made before editing existed
    logger.start(f"Application de {len(ops)} modification(s) au modèle original")
    model = load_obj(project / "meshes" / "original" / "model.obj")
    pinfo_path = project / "previews" / "original" / "preview.json"
    pinfo = json.loads(pinfo_path.read_text(encoding="utf-8")) if pinfo_path.exists() else {"decimated": False}
    preview: TexturedModel | None = None
    if pinfo.get("decimated") and (project / "previews" / "original" / "model.glb").exists():
        preview = load_model(project / "previews" / "original" / "model.glb")
    pc_prev = project / "previews" / "original" / "pointcloud.ply"
    pc_full = project / "reconstruction" / "dense_aligned_original.ply"
    pts_prev = _read_points(pc_prev) if pc_prev.exists() else None
    pts_full = _read_points(pc_full) if pc_full.exists() else None
    profile_name = "fast"
    stage_meta = project / "processed" / "stages" / "texture.json"
    if stage_meta.exists():
        profile_name = json.loads(stage_meta.read_text(encoding="utf-8")).get("profile", "fast")
    profile = get_profile(profile_name)

    rigid = np.eye(4)
    cache_dir = project / "processed" / "edits_cache"
    report = []
    for i, op in enumerate(ops):
        if cancel:
            cancel.check()
        if op["type"] == "simplify":
            key = hashlib.sha256(json.dumps(ops[: i + 1], sort_keys=True).encode()).hexdigest()[:16]
            cached = cache_dir / key / "model.obj"
            if cached.exists():
                logger.log(f"Simplification à {fmt_int(op['target_faces'])} faces (résultat en cache)")
                model = load_obj(cached)
            else:
                logger.log(f"Simplification à {fmt_int(op['target_faces'])} faces avec re-texturage depuis les photos")
                model = simplify_and_retexture(model, project, op["target_faces"], profile, tools, logger, cancel,
                                               name=f"edit_{key}", extra_transform=rigid)
                write_obj(model, cached)
            if preview is not None and preview.num_faces > model.num_faces:
                preview = None  # the simplified model is lighter than the old preview: show it directly
            report.append({"op": "simplify", "faces": model.num_faces})
            continue
        M = rigid_matrix(model.bounds(), op) if op["type"] in ("rotate", "recenter") else None
        r = apply_geometric_op(model, op, M)
        if preview is not None:
            try:
                apply_geometric_op(preview, op, M)
            except EditError:
                preview = None
        for name in ("prev", "full"):
            cur = pts_prev if name == "prev" else pts_full
            if cur is not None and op["type"] != "remove_components":
                cur = apply_to_points(cur[0], cur[1], op, M)
                if name == "prev":
                    pts_prev = cur
                else:
                    pts_full = cur
        if M is not None:
            rigid = M @ rigid
        report.append({"op": op["type"], **r})
        logger.progress((i + 1) / max(1, len(ops)), f"{op['type']} : {fmt_int(r['faces'])} faces")

    # ---- write derived outputs
    for f in list((project / "meshes").glob("model.*")) + list((project / "textures").glob("model_*")):
        f.unlink()
    write_obj(model, project / "meshes" / "model.obj", texture_dir=project / "textures", texture_rel="../textures/")
    for f in (project / "previews").glob("model*.glb"):
        f.unlink()
    if preview is not None and model.num_faces > PREVIEW_MAX_FACES:
        export_glb(preview, project / "previews", "model")
        export_glb(model, project / "previews", "model_full")
        info = {"decimated": True, "faces": preview.num_faces, "full_faces": model.num_faces}
    else:
        export_glb(model, project / "previews", "model")
        info = {"decimated": False, "faces": model.num_faces, "full_faces": model.num_faces}
    info["pointcloud_points"] = 0
    if pts_prev is not None:
        _write_points(project / "previews" / "pointcloud.ply", pts_prev[0], pts_prev[1], compact=True)
        info["pointcloud_points"] = int(len(pts_prev[0]))
    if pts_full is not None:
        _write_points(project / "reconstruction" / "dense_aligned.ply", pts_full[0], pts_full[1], compact=False)
    info["edits"] = len(ops)
    (project / "processed" / "edits_rigid.json").write_text(json.dumps({"matrix": rigid.tolist()}), encoding="utf-8")
    EditState(ops).save(project / "processed" / "edits.json")  # committed only once everything succeeded
    (project / "previews" / "preview.json").write_text(json.dumps(info, indent=2), encoding="utf-8")
    # exports no longer match the model: remove them (they are regenerated on demand)
    exp = project / "exports"
    if exp.exists():
        shutil.rmtree(exp)
    exp.mkdir()
    (project / "pipeline_result.json").exists() and _update_result(project, model)
    logger.finish(f"Modèle mis à jour : {fmt_int(model.num_faces)} faces", faces=model.num_faces, ops=len(ops))
    return {"faces": model.num_faces, "report": report}


def _update_result(project: Path, model: TexturedModel) -> None:
    f = project / "pipeline_result.json"
    d = json.loads(f.read_text(encoding="utf-8"))
    d["num_faces"], d["num_vertices"] = model.num_faces, model.num_vertices
    f.write_text(json.dumps(d, indent=2), encoding="utf-8")


def edits_rigid(project: Path) -> np.ndarray:
    f = Path(project) / "processed" / "edits_rigid.json"
    return np.asarray(json.loads(f.read_text(encoding="utf-8"))["matrix"]) if f.exists() else np.eye(4)
