"""« Export SketchUp » profile.

1. starts from the current (edited) textured model;
2. applies the calibrated scale (metres) when available;
3. orientation: already canonical (vertical, walls on the axes, front towards
   the viewer); written Z-up as SketchUp expects;
4. reduces the polygon count to the chosen level, **re-texturing from the
   photos** instead of degrading the UV atlas;
5. preserves textures (JPEG, relative paths);
6. writes the COLLADA file;
7. bundles .dae + textures/ in a ZIP;
8. re-reads the written DAE and checks it (axis, unit, UV, materials, textures
   present on disk, face count); the result is stored with the export.
"""
from __future__ import annotations

import json
import shutil
import zipfile
from dataclasses import asdict
from pathlib import Path

import collada

from .events import CancelToken, StageLogger
from .mesh_io import load_obj
from .profiles import get_profile
from .retexture import simplify_and_retexture
from .edit_runner import edits_rigid
from .stages.dae import write_dae
from .stages.export import ExportResult, merge_exports_json
from .tools import ToolRegistry
from .events import fmt_int

LEVELS = {
    "light": (50_000, "Léger"),
    "standard": (150_000, "Standard"),
    "detailed": (400_000, "Détaillé"),
}


def verify_dae(dae: Path, expected_faces: int) -> dict:
    doc = collada.Collada(str(dae))
    faces = sum(len(p) for g in doc.geometries for p in g.primitives)
    images = [im.path for im in doc.images]
    missing = [p for p in images if not (dae.parent / p).exists()]
    has_uv = all(len(p.texcoordset) > 0 for g in doc.geometries for p in g.primitives)
    checks = {
        "up_axis_z": doc.assetInfo.upaxis == collada.asset.UP_AXIS.Z_UP,
        "unit_meter": doc.assetInfo.unitmeter == 1.0,
        "uv_present": has_uv,
        "textures_present": bool(images) and not missing,
        "relative_texture_paths": all(not Path(p).is_absolute() and ".." not in Path(p).parts for p in images),
        "face_count_matches": faces == expected_faces,
        "materials_bound": len(doc.materials) == len(doc.geometries) and len(doc.materials) > 0,
    }
    return {"ok": all(checks.values()), "checks": checks, "faces": faces, "textures": images, "missing": missing}


def export_sketchup(project: Path, level: str, tools: ToolRegistry, logger: StageLogger,
                    cancel: CancelToken | None = None) -> ExportResult:
    if level not in LEVELS:
        raise ValueError(f"Niveau inconnu : {level}")
    target, label = LEVELS[level]
    project = Path(project)
    logger.start(f"Export SketchUp « {label} » (≤ {fmt_int(target)} faces)")
    model = load_obj(project / "meshes" / "model.obj")
    profile = "fast"
    meta = project / "processed" / "stages" / "texture.json"
    if meta.exists():
        profile = json.loads(meta.read_text(encoding="utf-8")).get("profile", "fast")
    if model.num_faces > target:
        model = simplify_and_retexture(model, project, target, get_profile(profile), tools, logger, cancel,
                                       name=f"sketchup_{level}", extra_transform=edits_rigid(project))
    else:
        logger.log(f"Le modèle a déjà {fmt_int(model.num_faces)} faces : pas de simplification")
    calib = project / "processed" / "calibration.json"
    scale = json.loads(calib.read_text(encoding="utf-8")).get("metres_per_unit") if calib.exists() else None
    name = f"model_sketchup_{level}"
    out_dir = project / "exports"
    d = out_dir / name
    if d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True)
    dae = d / f"{name}.dae"
    textures = write_dae(model, dae, unit_scale=scale)
    report = verify_dae(dae, model.num_faces)
    logger.log("Vérification du DAE : " + ", ".join(f"{k}={'OK' if v else 'ÉCHEC'}" for k, v in report["checks"].items()))
    if not report["ok"]:
        raise RuntimeError(f"Le DAE produit ne passe pas la vérification : {report['checks']}")
    zip_path = out_dir / f"{name}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for f in [dae, *textures]:
            z.write(f, arcname=str(f.relative_to(d)))
    note = (f"SketchUp « {label} » : {fmt_int(model.num_faces)} faces, textures re-projetées depuis les photos, Z vers le haut, "
            f"{'mètres (étalonné)' if scale else 'échelle NON étalonnée'}. Vérification automatique : OK.")
    res = ExportResult("dae", str(zip_path), [str(dae), *map(str, textures)], zip_path.stat().st_size, model.num_faces,
                       True, note)
    merge_exports_json(out_dir, [res], extra={zip_path.name: {"sketchup_level": level, "verification": report}})
    logger.finish(f"Export SketchUp prêt : {zip_path.name}", faces=model.num_faces)
    return res
