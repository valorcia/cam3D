"""Quality profiles: FAST / HIGH / ULTRA.

Each profile maps to *real* processing parameters. The numbers below are
documented in PHOTOGRAMMETRY.md; change them there and here together.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict


@dataclass(frozen=True)
class QualityProfile:
    name: str
    label: str
    description: str
    # --- preparation
    max_image_size: int           # longest side used for SfM features (px); 0 = original
    # --- SfM (COLMAP)
    sift_max_features: int
    matching: str                 # "exhaustive" | "sequential" | "auto"
    # --- dense (OpenMVS DensifyPointCloud)
    densify_resolution_level: int  # 0 = full res, 1 = half, 2 = quarter
    densify_max_resolution: int    # cap on longest side used for depth maps
    densify_number_views_fuse: int
    densify_estimate_normals: int  # 0/1/2
    densify_filter_iters: int      # --filter-point-cloud
    # --- mesh (ReconstructMesh)
    mesh_min_point_distance: float  # --min-point-distance (px)
    mesh_smooth: int               # --smooth iterations
    mesh_target_faces: int         # decimation target before texturing (0 = none)
    # --- refine (RefineMesh, optional, slow on CPU)
    refine_enabled: bool
    refine_resolution_level: int
    refine_max_iters: int
    # --- texture (TextureMesh)
    texture_resolution_level: int  # 0 = full-res images
    texture_max_size: int          # max texture atlas size
    texture_patch_packing_heuristic: int
    # --- SfM mapper: "incremental" (most robust), "global" (GLOMAP, much faster on large captures) or "auto"
    mapper: str = "auto"

    def to_dict(self) -> dict:
        return asdict(self)


FAST = QualityProfile(
    name="fast", label="Rapide",
    description="Aperçu exploitable rapidement : images réduites, nuage dense au quart de résolution, maillage léger.",
    max_image_size=1600, sift_max_features=4096, matching="auto",
    densify_resolution_level=2, densify_max_resolution=1200, densify_number_views_fuse=2,
    densify_estimate_normals=0, densify_filter_iters=0,
    mesh_min_point_distance=2.5, mesh_smooth=2, mesh_target_faces=150_000,
    refine_enabled=False, refine_resolution_level=2, refine_max_iters=0,
    texture_resolution_level=1, texture_max_size=4096, texture_patch_packing_heuristic=3,
)

HIGH = QualityProfile(
    name="high", label="Haute qualité",
    description="Modèle détaillé et texturé : nuage dense à demi-résolution, maillage dense, textures 8K.",
    max_image_size=3200, sift_max_features=8192, matching="auto",
    densify_resolution_level=1, densify_max_resolution=2400, densify_number_views_fuse=3,
    densify_estimate_normals=2, densify_filter_iters=1,
    mesh_min_point_distance=2.0, mesh_smooth=2, mesh_target_faces=600_000,
    refine_enabled=False, refine_resolution_level=1, refine_max_iters=0,
    texture_resolution_level=0, texture_max_size=8192, texture_patch_packing_heuristic=3,
)

ULTRA = QualityProfile(
    name="ultra", label="Ultra",
    description="Maximum de détails : pleine résolution, raffinement photométrique du maillage, textures 8K.",
    max_image_size=0, sift_max_features=16384, matching="auto",
    densify_resolution_level=0, densify_max_resolution=4000, densify_number_views_fuse=3,
    densify_estimate_normals=2, densify_filter_iters=1,
    mesh_min_point_distance=1.5, mesh_smooth=1, mesh_target_faces=0,
    refine_enabled=True, refine_resolution_level=1, refine_max_iters=2,
    texture_resolution_level=0, texture_max_size=8192, texture_patch_packing_heuristic=0,
)

PROFILES: dict[str, QualityProfile] = {p.name: p for p in (FAST, HIGH, ULTRA)}


def get_profile(name: str) -> QualityProfile:
    try:
        return PROFILES[name.lower()]
    except KeyError:
        raise ValueError(f"Profil inconnu: {name!r}. Profils disponibles: {', '.join(PROFILES)}")
