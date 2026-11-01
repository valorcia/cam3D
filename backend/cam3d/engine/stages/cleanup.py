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
    orientation: dict | None = None


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


def _rot_y(theta: float) -> np.ndarray:
    c, s = np.cos(theta), np.sin(theta)
    M = np.eye(4)
    M[0, 0], M[0, 2], M[2, 0], M[2, 2] = c, s, -s, c
    return M


def manhattan_yaw(model: TexturedModel, R_up: np.ndarray) -> tuple[float, float]:
    """Yaw (rad, about +Y) aligning the dominant vertical surfaces with the X/Z axes.

    Area-weighted histogram of wall orientations modulo 90° (walls of a building,
    sides of a box). Returns (yaw, confidence in [0,1]). Rotating by -yaw puts
    the dominant walls parallel to the axes, which is what SketchUp users expect
    (red/green axes along the walls).
    """
    angles, weights = [], []
    for p in model.parts:
        V = p.vertices @ R_up[:3, :3].T
        tri = V[p.faces]
        n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
        area = np.linalg.norm(n, axis=1)
        ok = area > 0
        n, area = n[ok] / area[ok, None], area[ok]
        vertical = np.abs(n[:, 1]) < 0.3            # wall-like faces
        a = np.arctan2(n[vertical, 2], n[vertical, 0]) % (np.pi / 2)
        angles.append(a)
        weights.append(area[vertical])
    if not angles:
        return 0.0, 0.0
    a, w = np.concatenate(angles), np.concatenate(weights)
    if len(a) == 0 or w.sum() <= 0:
        return 0.0, 0.0
    bins = 90
    hist, edges = np.histogram(a, bins=bins, range=(0, np.pi / 2), weights=w)
    hist = np.convolve(np.r_[hist[-2:], hist, hist[:2]], np.ones(5) / 5, mode="valid")  # circular smoothing
    k = int(np.argmax(hist))
    peak = (edges[k] + edges[k + 1]) / 2
    # sub-degree refinement: area-weighted mean of the orientations within ±3° of the peak
    q = np.pi / 2
    diff = (a - peak + q / 2) % q - q / 2
    near = np.abs(diff) < np.radians(3)
    yaw = (peak + float(np.average(diff[near], weights=w[near]))) % q if near.any() and w[near].sum() > 0 else peak
    # share of the wall area within ±7.5° of the dominant direction, vs 1/6 for random
    # orientations (real scans spread walls over several degrees)
    d_all = np.abs((a - yaw + q / 2) % q - q / 2)
    share = float(w[d_all <= np.radians(7.5)].sum() / w.sum())
    confidence = max(0.0, (share - 1 / 6) / (1 - 1 / 6))
    return float(yaw), float(min(1.0, confidence))


def canonical_transform(model: TexturedModel, up_vector: np.ndarray | None,
                        camera_center: np.ndarray | None = None, info: dict | None = None) -> np.ndarray:
    """Rotate up->+Y, align dominant walls with X/Z, turn the photographed side
    towards +Z ("front"), then put the bbox bottom on y=0 and centre in XZ."""
    M = rotation_to_y_up(up_vector) if up_vector is not None else np.eye(4)
    yaw, conf = manhattan_yaw(model, M)
    if info is not None:
        info.update(wall_yaw_deg=round(float(np.degrees(yaw)), 2), wall_confidence=round(conf, 3),
                    walls_aligned=conf >= 0.2, front_from_cameras=camera_center is not None)
    if conf >= 0.2:
        M = _rot_y(yaw) @ M  # rotate walls onto the axes (sign: R_y(+yaw) maps angle yaw to 0 for our convention)
    if camera_center is not None:
        allv = np.vstack([p.vertices for p in model.parts]) @ M[:3, :3].T
        c = (allv.min(axis=0) + allv.max(axis=0)) / 2
        cam = np.asarray(camera_center, dtype=np.float64) @ M[:3, :3].T + M[:3, 3]
        d = cam - c
        # quarter turn that brings the cameras' side to +Z
        quarter = {0: 0.0, 1: np.pi / 2, 2: np.pi, 3: -np.pi / 2}
        side = int(np.argmax([d[2], -d[0], -d[2], d[0]]))  # +Z, -X, -Z, +X
        M = _rot_y(quarter[side]) @ M
    allv = np.vstack([p.vertices for p in model.parts]) @ M[:3, :3].T
    lo, hi = allv.min(axis=0), allv.max(axis=0)
    centre = (lo + hi) / 2.0
    T = np.eye(4)
    T[:3, 3] = [-centre[0], -lo[1], -centre[2]]
    return T @ M


def run_cleanup(model: TexturedModel, logger: StageLogger, up_vector: list[float] | None,
                cancel: CancelToken | None = None, min_component_fraction: float = 0.02,
                report_path: Path | None = None, camera_center: list[float] | None = None) -> CleanupReport:
    logger.start("Nettoyage automatique du maillage texturé")
    before = model.num_faces
    comps = remove_small_components(model, min_fraction=min_component_fraction)
    logger.log(f"Composants isolés supprimés : {comps}")
    if cancel:
        cancel.check()
    degen = remove_degenerate_faces(model)
    logger.log(f"Faces dégénérées/dupliquées supprimées : {degen}")
    up = np.asarray(up_vector, dtype=np.float64) if up_vector is not None else np.array([0.0, 1.0, 0.0])
    info: dict = {}
    M = canonical_transform(model, up, np.asarray(camera_center) if camera_center is not None else None, info)
    model.apply_transform(M)
    parts = ["haut estimé sur +Y"]
    parts.append(f"murs dominants alignés sur les axes (confiance {info['wall_confidence']:.2f})" if info["walls_aligned"]
                 else f"pas d'orientation de murs dominante (confiance {info['wall_confidence']:.2f}) : rotation horizontale conservée")
    if info["front_from_cameras"]:
        parts.append("face photographiée vers +Z")
    parts.append("base posée sur y=0")
    logger.log("Orientation : " + ", ".join(parts))
    rep = CleanupReport(before, model.num_faces, comps, degen, up.tolist(), M.tolist(), info)
    if report_path:
        Path(report_path).write_text(json.dumps(asdict(rep), indent=2), encoding="utf-8")
    logger.finish(f"{rep.faces_after:,} faces conservées sur {before:,}".replace(",", " "), **{k: v for k, v in asdict(rep).items() if k != "transform"})
    return rep
