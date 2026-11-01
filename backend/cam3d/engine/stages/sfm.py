"""Stage 2 - Structure-from-Motion with COLMAP (via pycolmap).

Outputs, inside ``work_dir``:

* ``database.db``        COLMAP feature/match database
* ``sparse/0/``          best reconstruction (cameras/images/points3D .bin + .txt)
* ``sparse/0/points.ply``  sparse point cloud (for preview)
* ``sfm.json``           summary (registered images, points, errors)

CPU only by default (``Device.cpu``); when pycolmap is built with CUDA and an
NVIDIA GPU exists we let it pick ``auto``.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, asdict
from pathlib import Path

import numpy as np
import pycolmap

from ..events import CancelToken, StageLogger
from ..profiles import QualityProfile


@dataclass
class SfmResult:
    sparse_dir: str
    num_images_total: int
    num_registered: int
    num_points: int
    mean_reproj_error: float
    mean_track_length: float
    num_models: int
    up_vector: list[float]       # estimated world "up" (unit) from camera orientations
    centroid: list[float]


def _device(use_gpu: bool) -> "pycolmap.Device":
    if use_gpu and getattr(pycolmap, "has_cuda", False):
        return pycolmap.Device.auto
    return pycolmap.Device.cpu


def _choose_matching(profile: QualityProfile, num_images: int) -> str:
    if profile.matching != "auto":
        return profile.matching
    # Exhaustive is the most robust; its cost is O(n²). Beyond ~150 images we
    # switch to sequential (+loop detection) which assumes a video-like order.
    return "exhaustive" if num_images <= 150 else "sequential"


def estimate_up_vector(rec: "pycolmap.Reconstruction") -> np.ndarray:
    """Mean of the cameras' up axes (-Y in camera frame) expressed in world.

    Handheld captures keep the phone roughly upright, so this gives a usable
    gravity direction without IMU data. Falls back to -Y world if degenerate.
    """
    ups = []
    for img in rec.images.values():
        if not img.has_pose:
            continue
        R = img.cam_from_world().rotation.matrix()  # world -> cam
        ups.append(-R.T[:, 1])                         # cam -Y axis in world
    if not ups:
        return np.array([0.0, -1.0, 0.0])
    u = np.mean(ups, axis=0)
    n = np.linalg.norm(u)
    return u / n if n > 1e-6 else np.array([0.0, -1.0, 0.0])


def run_sfm(
    work_dir: Path,
    profile: QualityProfile,
    logger: StageLogger,
    cancel: CancelToken | None = None,
    use_gpu: bool = True,
    num_threads: int = -1,
) -> SfmResult:
    work_dir = Path(work_dir)
    images_dir = work_dir / "images"
    db_path = work_dir / "database.db"
    sparse_dir = work_dir / "sparse"
    image_names = sorted(p.name for p in images_dir.iterdir() if p.suffix.lower() in {".jpg", ".jpeg", ".png"})
    n = len(image_names)
    if n < 3:
        raise RuntimeError("Au moins 3 images sont nécessaires pour l'estimation des caméras.")
    logger.start(f"COLMAP SfM sur {n} images (pycolmap {pycolmap.__version__}, {'CUDA' if pycolmap.has_cuda and use_gpu else 'CPU'})")

    if db_path.exists():
        db_path.unlink()
    if sparse_dir.exists():
        import shutil
        shutil.rmtree(sparse_dir)
    sparse_dir.mkdir(parents=True)

    threads = num_threads if num_threads > 0 else (os.cpu_count() or 2)
    device = _device(use_gpu)
    token = pycolmap.CancellationToken() if hasattr(pycolmap, "CancellationToken") else None

    # --- 1. features -------------------------------------------------------
    ext = pycolmap.FeatureExtractionOptions()
    ext.num_threads = threads
    ext.max_image_size = profile.max_image_size or 10000
    ext.sift.max_num_features = profile.sift_max_features
    # Each photo gets its own camera model unless EXIF says it's the same device:
    # phones use a single camera -> SINGLE helps BA; but mixed imports happen.
    # AUTO groups by image size + EXIF model, which is the right default.
    reader = pycolmap.ImageReaderOptions()
    reader.camera_model = "SIMPLE_RADIAL"
    logger.log(f"Extraction SIFT (max {profile.sift_max_features} points, image max {ext.max_image_size}px, {threads} threads)")
    pycolmap.extract_features(
        db_path, images_dir, image_names=image_names, camera_mode=pycolmap.CameraMode.AUTO,
        reader_options=reader, extraction_options=ext, device=device,
    )
    if cancel:
        cancel.check()

    # --- 2. matching -------------------------------------------------------
    mode = _choose_matching(profile, n)
    mopt = pycolmap.FeatureMatchingOptions()
    mopt.num_threads = threads
    mopt.guided_matching = profile.name != "fast"
    logger.log(f"Appariement {mode} (guided={mopt.guided_matching})")
    if mode == "sequential":
        popt = pycolmap.SequentialPairingOptions()
        popt.overlap = 10
        popt.quadratic_overlap = True
        popt.loop_detection = False  # needs a vocab tree file; see PHOTOGRAMMETRY.md
        pycolmap.match_sequential(db_path, matching_options=mopt, pairing_options=popt, device=device)
    else:
        pycolmap.match_exhaustive(db_path, matching_options=mopt, device=device)
    if cancel:
        cancel.check()

    # --- 3. incremental mapping -------------------------------------------
    mopts = pycolmap.IncrementalPipelineOptions()
    mopts.num_threads = threads
    mopts.min_num_matches = 15
    mopts.multiple_models = True
    mopts.max_num_models = 5
    mopts.extract_colors = True
    mopts.ba_refine_focal_length = True
    mopts.ba_refine_extra_params = True
    mopts.ba_refine_principal_point = False
    progress = {"done": 0}

    def _next_image() -> None:
        progress["done"] += 1
        logger.progress(min(progress["done"] / n, 0.99), f"Caméra enregistrée {progress['done']}/{n}")
        if cancel and cancel.cancelled and token is not None:
            token.cancel()

    logger.log("Reconstruction incrémentale (poses + triangulation + ajustement de faisceaux)")
    recs = pycolmap.incremental_mapping(
        db_path, images_dir, sparse_dir, options=mopts, next_image_callback=_next_image,
    )
    if cancel:
        cancel.check()
    if not recs:
        raise RuntimeError(
            "COLMAP n'a pu enregistrer aucune caméra. Causes fréquentes : trop peu de recouvrement entre les photos, "
            "surfaces uniformes/réfléchissantes, images floues. Reprenez des photos en tournant lentement autour de l'objet."
        )
    # keep the model with the most registered images in sparse/0
    best_id = max(recs, key=lambda k: recs[k].num_reg_images())
    best = recs[best_id]
    out0 = sparse_dir / "0"
    if best_id != 0:
        import shutil
        tmp = sparse_dir / "best_tmp"
        shutil.move(str(sparse_dir / str(best_id)), str(tmp))
        if out0.exists():
            shutil.rmtree(out0)
        shutil.move(str(tmp), str(out0))
    best.write(out0)
    best.write_text(out0)  # OpenMVS InterfaceCOLMAP reads the .txt variant
    best.export_PLY(out0 / "points.ply")

    up = estimate_up_vector(best)
    centroid = np.asarray(best.compute_centroid(0.0, 1.0)).tolist()
    res = SfmResult(
        sparse_dir=str(out0),
        num_images_total=n,
        num_registered=best.num_reg_images(),
        num_points=best.num_points3D(),
        mean_reproj_error=float(best.compute_mean_reprojection_error()),
        mean_track_length=float(best.compute_mean_track_length()),
        num_models=len(recs),
        up_vector=up.tolist(),
        centroid=centroid,
    )
    (work_dir / "sfm.json").write_text(json.dumps(asdict(res), indent=2), encoding="utf-8")
    msg = (f"{res.num_registered}/{n} caméras, {res.num_points} points 3D, "
           f"erreur de reprojection {res.mean_reproj_error:.2f}px, {res.num_models} modèle(s)")
    if res.num_registered < max(3, int(0.5 * n)):
        logger.log("Attention : moins de la moitié des images ont été enregistrées ; la reconstruction sera partielle.")
    logger.finish(msg, **asdict(res))
    return res
