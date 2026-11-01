"""Stage 6 - cleanup and canonical orientation (UV preserving).

Operations applied automatically after texturing:

1. remove small disconnected components (noise, floating blobs),
2. drop degenerate / duplicate faces,
3. rotate the model so that the estimated gravity vector points to +Y,
4. translate so that the model's lowest point is at y=0 and it is centred in XZ.

All operations work on face subsets of the textured mesh, so UVs and textures
are untouched. Interactive tools (crop, delete selection, undo) build on the
same primitives; see ``cam3d.engine.edit``.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from pathlib import Path

import numpy as np
import trimesh

from ..events import CancelToken, StageLogger
from ..mesh_io import MeshPart, TexturedModel


@dataclass
class CleanupReport:
    faces_before: int
    faces_after: int
    components_removed: int
    degenerate_removed: int
    up_vector_used: list[float]
    transform: list[list[float]]   # 4x4 applied to the model (row-major)


def _subset(part: MeshPart, face_mask: np.ndarray) -> MeshPart:
    faces = part.faces[face_mask]
    used = np.unique(faces)
    remap = -np.ones(len(part.vertices), dtype=np.int64)
    remap[used] = np.arange(len(used))
    return MeshPart(part.name, part.vertices[used], remap[faces], part.uv[used] if part.uv is not None else None,
                    part.texture, None, part.diffuse_color)


def remove_small_components(model: TexturedModel, min_fraction: float = 0.02, min_faces: int = 200) -> int:
    """Keep components with >= max(min_faces, min_fraction * largest) faces. Returns #removed."""
    removed = 0
    for i, p in enumerate(model.parts):
        # Textured meshes duplicate vertices along UV seams, so connectivity must
        # be computed on merged positions, not on the (split) vertex indices.
        _, inverse = trimesh.grouping.unique_rows(p.vertices, digits=8)
        tm = trimesh.Trimesh(p.vertices, inverse[p.faces], process=False)
        labels = trimesh.graph.connected_component_labels(tm.face_adjacency, node_count=len(p.faces))
        counts = np.bincount(labels)
        if len(counts) <= 1:
            continue
        threshold = max(min_faces, int(min_fraction * counts.max()))
        keep_labels = np.flatnonzero(counts >= threshold)
        if len(keep_labels) == 0:  # never drop the main component, however small the mesh is
            keep_labels = np.array([int(np.argmax(counts))])
        removed += len(counts) - len(keep_labels)
        mask = np.isin(labels, keep_labels)
        model.parts[i] = _subset(p, mask)
    model.parts = [p for p in model.parts if len(p.faces) > 0]
    return removed


def remove_degenerate_faces(model: TexturedModel, min_area: float = 0.0) -> int:
    removed = 0
    for i, p in enumerate(model.parts):
        tm = trimesh.Trimesh(p.vertices, p.faces, process=False)
        areas = tm.area_faces
        ok = areas > min_area
        # duplicate faces (same vertex set)
        sorted_faces = np.sort(p.faces, axis=1)
        _, first_idx = np.unique(sorted_faces, axis=0, return_index=True)
        dup_mask = np.zeros(len(p.faces), dtype=bool)
        dup_mask[first_idx] = True
        mask = ok & dup_mask
        removed += int((~mask).sum())
        if removed:
            model.parts[i] = _subset(p, mask)
    return removed


def rotation_to_y_up(up: np.ndarray) -> np.ndarray:
    """4x4 rotation taking unit vector ``up`` to +Y."""
    up = np.asarray(up, dtype=np.float64)
    up = up / (np.linalg.norm(up) or 1.0)
    target = np.array([0.0, 1.0, 0.0])
    v = np.cross(up, target)
    c = float(np.dot(up, target))
    M = np.eye(4)
    if np.linalg.norm(v) < 1e-8:
        if c < 0:  # anti-parallel: rotate 180° around X
            M[1, 1] = M[2, 2] = -1.0
        return M
    vx = np.array([[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]])
    R = np.eye(3) + vx + vx @ vx * (1.0 / (1.0 + c))
    M[:3, :3] = R
    return M


def canonical_transform(model: TexturedModel, up_vector: np.ndarray | None) -> np.ndarray:
    """Rotate up->+Y, then put the bbox bottom on y=0 and centre in XZ."""
    M = rotation_to_y_up(up_vector) if up_vector is not None else np.eye(4)
    allv = np.vstack([p.vertices for p in model.parts]) @ M[:3, :3].T
    lo, hi = allv.min(axis=0), allv.max(axis=0)
    centre = (lo + hi) / 2.0
    T = np.eye(4)
    T[:3, 3] = [-centre[0], -lo[1], -centre[2]]
    return T @ M


def run_cleanup(model: TexturedModel, logger: StageLogger, up_vector: list[float] | None,
                cancel: CancelToken | None = None, min_component_fraction: float = 0.02,
                report_path: Path | None = None) -> CleanupReport:
    logger.start("Nettoyage automatique du maillage texturé")
    before = model.num_faces
    comps = remove_small_components(model, min_fraction=min_component_fraction)
    logger.log(f"Composants isolés supprimés : {comps}")
    if cancel:
        cancel.check()
    degen = remove_degenerate_faces(model)
    logger.log(f"Faces dégénérées/dupliquées supprimées : {degen}")
    up = np.asarray(up_vector, dtype=np.float64) if up_vector is not None else np.array([0.0, 1.0, 0.0])
    M = canonical_transform(model, up)
    model.apply_transform(M)
    logger.log("Orientation : vecteur 'haut' estimé aligné sur +Y, base posée sur y=0")
    rep = CleanupReport(before, model.num_faces, comps, degen, up.tolist(), M.tolist())
    if report_path:
        Path(report_path).write_text(json.dumps(asdict(rep), indent=2), encoding="utf-8")
    logger.finish(f"{rep.faces_after:,} faces conservées sur {before:,}".replace(",", " "), **{k: v for k, v in asdict(rep).items() if k != "transform"})
    return rep
