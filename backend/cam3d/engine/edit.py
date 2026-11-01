"""Non-destructive model editing.

The reconstructed model is kept untouched in ``meshes/original/``. User edits
are a list of operations (``processed/edits.json``) replayed on the original:
undo = drop the last operation and replay; reset = empty list. Every
operation is expressed **geometrically in the model's canonical frame** (not
with face indices), so the same list applies to the full model, the browser
preview (possibly decimated) and the point cloud.

Operations:

``crop_box``        keep what lies inside an axis-aligned box  {min, max}
``delete_region``   delete what projects inside a screen polygon {matrix (4x4 view-projection, column-major as in three.js), polygon [[x,y] NDC]}
``remove_components`` delete floating parts smaller than a fraction of the largest {min_fraction}
``rotate``          rotate about the model centre {axis x|y|z, degrees}
``recenter``        centre in X/Z and put the lowest point on y=0
``simplify``        reduce to {target_faces}; the mesh is decimated by OpenMVS and
                    **re-textured from the photos** (handled by ``retexture.py``)

Faces are tested with their centroid; points with their position.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .mesh_io import MeshPart, TexturedModel
from .stages.cleanup import remove_small_components

OP_TYPES = ("crop_box", "delete_region", "remove_components", "rotate", "recenter", "simplify")


class EditError(ValueError):
    pass


def validate_op(op: dict) -> dict:
    t = op.get("type")
    if t not in OP_TYPES:
        raise EditError(f"Opération inconnue : {t}")
    if t == "crop_box":
        lo, hi = np.asarray(op.get("min"), float), np.asarray(op.get("max"), float)
        if lo.shape != (3,) or hi.shape != (3,) or np.any(hi <= lo):
            raise EditError("Boîte de découpe invalide")
        return {"type": t, "min": lo.tolist(), "max": hi.tolist()}
    if t == "delete_region":
        m = np.asarray(op.get("matrix"), float)
        poly = np.asarray(op.get("polygon"), float)
        if m.shape != (16,) or poly.ndim != 2 or poly.shape[1] != 2 or len(poly) < 3:
            raise EditError("Sélection invalide")
        return {"type": t, "matrix": m.tolist(), "polygon": poly.tolist()}
    if t == "remove_components":
        f = float(op.get("min_fraction", 0.05))
        if not 0 < f < 1:
            raise EditError("Seuil invalide")
        return {"type": t, "min_fraction": f}
    if t == "rotate":
        axis, deg = op.get("axis"), float(op.get("degrees", 0))
        if axis not in ("x", "y", "z") or not -360 <= deg <= 360:
            raise EditError("Rotation invalide")
        return {"type": t, "axis": axis, "degrees": deg}
    if t == "recenter":
        return {"type": t}
    n = int(op.get("target_faces", 0))
    if n < 1000:
        raise EditError("Nombre de faces cible trop faible (1 000 minimum)")
    return {"type": t, "target_faces": n}


# --------------------------------------------------------------------- masks
def inside_box(points: np.ndarray, lo, hi) -> np.ndarray:
    return np.all((points >= np.asarray(lo)) & (points <= np.asarray(hi)), axis=1)


def _points_in_polygon(xy: np.ndarray, poly: np.ndarray) -> np.ndarray:
    """Even-odd rule, vectorised over points."""
    x, y = xy[:, 0], xy[:, 1]
    inside = np.zeros(len(xy), dtype=bool)
    j = len(poly) - 1
    for i in range(len(poly)):
        xi, yi = poly[i]
        xj, yj = poly[j]
        cond = ((yi > y) != (yj > y)) & (x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-12) + xi)
        inside ^= cond
        j = i
    return inside


def in_screen_region(points: np.ndarray, matrix16, polygon) -> np.ndarray:
    """Points whose projection (three.js column-major view-projection) falls inside the NDC polygon."""
    M = np.asarray(matrix16, float).reshape(4, 4).T  # column-major -> row-major
    h = np.c_[points, np.ones(len(points))] @ M.T
    w = h[:, 3]
    ok = w > 1e-9                                     # in front of the camera
    ndc = np.zeros((len(points), 2))
    ndc[ok] = h[ok, :2] / w[ok, None]
    return ok & _points_in_polygon(ndc, np.asarray(polygon, float))


def _rotation(axis: str, degrees: float) -> np.ndarray:
    a = np.radians(degrees)
    c, s = np.cos(a), np.sin(a)
    R = {"x": [[1, 0, 0], [0, c, -s], [0, s, c]], "y": [[c, 0, s], [0, 1, 0], [-s, 0, c]],
         "z": [[c, -s, 0], [s, c, 0], [0, 0, 1]]}[axis]
    return np.asarray(R, float)


def _subset(part: MeshPart, face_mask: np.ndarray) -> MeshPart:
    faces = part.faces[face_mask]
    used = np.unique(faces)
    remap = -np.ones(len(part.vertices), dtype=np.int64)
    remap[used] = np.arange(len(used))
    return MeshPart(part.name, part.vertices[used], remap[faces], part.uv[used] if part.uv is not None else None,
                    part.texture, None, part.diffuse_color)


def _filter_faces(model: TexturedModel, keep_fn) -> int:
    removed = 0
    parts = []
    for p in model.parts:
        centroids = p.vertices[p.faces].mean(axis=1)
        keep = keep_fn(centroids)
        removed += int((~keep).sum())
        if keep.any():
            parts.append(_subset(p, keep) if not keep.all() else p)
    model.parts = parts
    return removed


def rigid_matrix(model_bounds: tuple[np.ndarray, np.ndarray], op: dict) -> np.ndarray:
    lo, hi = model_bounds
    M = np.eye(4)
    if op["type"] == "rotate":
        c = (lo + hi) / 2
        R = _rotation(op["axis"], op["degrees"])
        M[:3, :3] = R
        M[:3, 3] = c - R @ c
    elif op["type"] == "recenter":
        M[:3, 3] = [-(lo[0] + hi[0]) / 2, -lo[1], -(lo[2] + hi[2]) / 2]
    return M


def apply_geometric_op(model: TexturedModel, op: dict, matrix: np.ndarray | None = None) -> dict:
    """Apply one non-simplify op in place. ``matrix``: precomputed rigid matrix (so that
    the full model, the preview and the point cloud get exactly the same motion)."""
    t = op["type"]
    if not model.parts or model.num_faces == 0:
        raise EditError("Le modèle est vide : annulez la dernière opération.")
    if t == "crop_box":
        n = _filter_faces(model, lambda c: inside_box(c, op["min"], op["max"]))
    elif t == "delete_region":
        n = _filter_faces(model, lambda c: ~in_screen_region(c, op["matrix"], op["polygon"]))
    elif t == "remove_components":
        before = model.num_faces
        remove_small_components(model, min_fraction=op["min_fraction"], min_faces=0)
        n = before - model.num_faces
    elif t in ("rotate", "recenter"):
        model.apply_transform(matrix if matrix is not None else rigid_matrix(model.bounds(), op))
        n = 0
    else:
        raise EditError(f"{t} n'est pas une opération géométrique")
    if model.num_faces == 0:
        raise EditError("Cette opération supprimerait tout le modèle.")
    return {"faces_removed": n, "faces": model.num_faces}


def apply_to_points(points: np.ndarray, colors: np.ndarray | None, op: dict,
                    matrix: np.ndarray | None) -> tuple[np.ndarray, np.ndarray | None]:
    """Same edit on a point cloud (simplify/remove_components do not apply to points)."""
    t = op["type"]
    if t == "crop_box":
        keep = inside_box(points, op["min"], op["max"])
    elif t == "delete_region":
        keep = ~in_screen_region(points, op["matrix"], op["polygon"])
    elif t in ("rotate", "recenter"):
        M = matrix if matrix is not None else np.eye(4)
        return points @ M[:3, :3].T + M[:3, 3], colors
    else:
        return points, colors
    return points[keep], (colors[keep] if colors is not None else None)


@dataclass
class EditState:
    ops: list[dict]

    @staticmethod
    def load(path: Path) -> "EditState":
        if Path(path).exists():
            return EditState(json.loads(Path(path).read_text(encoding="utf-8")).get("ops", []))
        return EditState([])

    def save(self, path: Path) -> None:
        Path(path).write_text(json.dumps({"ops": self.ops}, indent=2), encoding="utf-8")
