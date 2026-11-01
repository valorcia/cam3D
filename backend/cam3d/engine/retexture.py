"""Simplify a (possibly edited) model and re-texture it from the photos.

Decimating a textured mesh directly damages its UV atlas (seams collapse,
patches stretch). Instead the canonical geometry is mapped back to the
reconstruction frame, decimated by OpenMVS (quadric edge collapse), and
TextureMesh projects the original photos onto it again: the result has a
fresh, clean atlas. Requires the project's ``processed/mvs/scene_dense.mvs``
(kept after reconstruction) and the canonical transform (``cleanup.json``).
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import trimesh

from .events import CancelToken, StageLogger
from .mesh_io import TexturedModel, load_model, merged_geometry
from .profiles import QualityProfile
from .stages.mvs import MeshResult, decimate_mesh, run_texture
from .tools import ToolRegistry
from .events import fmt_int


def canonical_transform_of(project: Path) -> np.ndarray:
    f = Path(project) / "processed" / "cleanup.json"
    if not f.exists():
        raise RuntimeError("Transformation du modèle introuvable (cleanup.json) : reconstruisez le projet.")
    return np.asarray(json.loads(f.read_text(encoding="utf-8"))["transform"], float)


def simplify_and_retexture(model: TexturedModel, project: Path, target_faces: int, profile: QualityProfile,
                           tools: ToolRegistry, logger: StageLogger, cancel: CancelToken | None = None,
                           name: str = "simplified", extra_transform: np.ndarray | None = None) -> TexturedModel:
    """``extra_transform``: rigid edits (rotate/recenter) applied after the canonical frame,
    so that geometry can be mapped back to the reconstruction frame exactly."""
    project = Path(project)
    mvs = project / "processed" / "mvs"
    scene = mvs / "scene_dense.mvs"
    if not scene.exists():
        raise RuntimeError("Scène OpenMVS introuvable : la re-texturation nécessite les données de reconstruction.")
    M = canonical_transform_of(project)
    if extra_transform is not None:
        M = extra_transform @ M
    Minv = np.linalg.inv(M)
    geo = merged_geometry(model)
    # merge UV-seam duplicates so the decimation sees a connected surface
    geo.merge_vertices(merge_tex=True, merge_norm=True)
    V = np.asarray(geo.vertices) @ Minv[:3, :3].T + Minv[:3, 3]
    raw = mvs / f"{name}_input.ply"
    trimesh.Trimesh(V, np.asarray(geo.faces), process=False).export(raw, file_type="ply", encoding="binary")
    mesh = MeshResult(str(scene), str(raw), len(V), len(geo.faces))
    if len(geo.faces) > target_faces:
        logger.log(f"Décimation de {fmt_int(len(geo.faces))} à {fmt_int(target_faces)} faces")
        ply = decimate_mesh(mesh, target_faces, tools, logger, cancel, out_name=f"{name}_decimated")
    else:
        ply = raw
    logger.log("Re-texturage à partir des photos")
    tex = run_texture(project / "processed", profile, tools, logger, mesh, cancel, mesh_override=ply,
                      output_name=f"{name}_tex", allow_raw_fallback=False)
    out = load_model(Path(tex.obj_path))
    out.apply_transform(M)
    return out
