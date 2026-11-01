"""Geometry filtering between meshing and texturing (no UVs yet -> cheap).

OpenMVS' Delaunay/graph-cut meshing closes unbounded scenes with large
"hallucinated" surfaces (sky, background, floor extrapolations). We remove:

1. faces whose longest edge exceeds ``edge_ratio`` x the median edge length,
2. faces whose centroid is farther than ``dist_ratio`` x median edge from any
   dense point (surfaces not supported by photogrammetric evidence),
3. small disconnected components left over (< ``component_fraction`` of the
   largest, or < ``min_component_faces``).

The result is written as a new PLY that TextureMesh consumes through
``--mesh-file``. Thresholds are deliberately conservative so that real,
densely observed geometry is never touched; the interactive cleanup tools
remain available for the rest.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from pathlib import Path

import numpy as np
import trimesh
from scipy.spatial import cKDTree

from ..events import CancelToken, StageLogger
from ..events import fmt_int


@dataclass
class MeshFilterReport:
    faces_in: int
    faces_out: int
    removed_long_edges: int
    removed_unsupported: int
    removed_components: int
    median_edge: float


def _read_points(ply: Path, max_points: int = 3_000_000) -> np.ndarray:
    # OpenMVS dense PLYs carry list properties (view_indices) that trimesh rejects: use Open3D.
    import open3d as o3d

    pts = np.asarray(o3d.io.read_point_cloud(str(ply)).points, dtype=np.float64)
    if len(pts) > max_points:
        idx = np.random.default_rng(0).choice(len(pts), max_points, replace=False)
        pts = pts[idx]
    return pts


def filter_mesh(mesh_ply: Path, dense_ply: Path | None, out_ply: Path, logger: StageLogger,
                edge_ratio: float = 10.0, dist_ratio: float = 6.0, component_fraction: float = 0.02,
                min_component_faces: int = 300, cancel: CancelToken | None = None,
                report_path: Path | None = None) -> MeshFilterReport:
    import open3d as o3d

    o3m = o3d.io.read_triangle_mesh(str(mesh_ply))
    V, F = np.asarray(o3m.vertices, dtype=np.float64), np.asarray(o3m.triangles, dtype=np.int64)
    n_in = len(F)
    edges = V[F[:, [1, 2, 0]]] - V[F]
    edge_len = np.linalg.norm(edges, axis=2)         # (F,3)
    med = float(np.median(edge_len))
    keep = np.ones(n_in, dtype=bool)

    long_mask = edge_len.max(axis=1) > edge_ratio * med
    keep &= ~long_mask
    if cancel:
        cancel.check()

    unsupported = 0
    if dense_ply is not None and Path(dense_ply).exists():
        pts = _read_points(Path(dense_ply))
        tree = cKDTree(pts)
        centroids = V[F].mean(axis=1)
        d, _ = tree.query(centroids, workers=-1)
        far = d > dist_ratio * med
        unsupported = int((far & keep).sum())
        keep &= ~far
    if cancel:
        cancel.check()

    F2 = F[keep]
    # connected components on the surviving faces (vertex-index connectivity is fine: no UV seams yet)
    tm2 = trimesh.Trimesh(V, F2, process=False)
    labels = trimesh.graph.connected_component_labels(tm2.face_adjacency, node_count=len(F2))
    counts = np.bincount(labels) if len(F2) else np.array([0])
    thr = max(min_component_faces, int(component_fraction * counts.max()))
    keep_labels = np.flatnonzero(counts >= thr)
    if len(keep_labels) == 0:
        keep_labels = np.array([int(np.argmax(counts))])
    comp_mask = np.isin(labels, keep_labels)
    removed_comps = int(len(counts) - len(keep_labels))
    F3 = F2[comp_mask]

    # Removing faces can leave non-manifold edges/vertices, which OpenMVS'
    # seam leveling cannot handle (unordered_map::at crash): clean them with Open3D.
    o3 = o3d.geometry.TriangleMesh(o3d.utility.Vector3dVector(V), o3d.utility.Vector3iVector(F3))
    o3.remove_duplicated_triangles()
    o3.remove_degenerate_triangles()
    o3.remove_non_manifold_edges()
    for _ in range(5):
        nmv = np.asarray(o3.get_non_manifold_vertices())
        if len(nmv) == 0:
            break
        tri = np.asarray(o3.triangles)
        bad = np.isin(tri, nmv).any(axis=1)
        o3.remove_triangles_by_mask(bad)
        o3.remove_non_manifold_edges()
    o3.remove_unreferenced_vertices()
    out = trimesh.Trimesh(np.asarray(o3.vertices), np.asarray(o3.triangles), process=False)
    out.export(out_ply, file_type="ply", encoding="binary")
    rep = MeshFilterReport(n_in, len(out.faces), int(long_mask.sum()), unsupported, removed_comps, med)
    logger.log(f"Filtrage géométrique : {rep.removed_long_edges} faces trop grandes, {rep.removed_unsupported} faces sans "
               f"support photogrammétrique, {rep.removed_components} composants isolés -> {fmt_int(rep.faces_out)} faces")
    if report_path:
        Path(report_path).write_text(json.dumps(asdict(rep), indent=2), encoding="utf-8")
    return rep
