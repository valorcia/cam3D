"""Stage 7 - exports: OBJ, GLB, STL, PLY, DAE (+ zip bundles)."""
from __future__ import annotations

import copy
import json
import shutil
import zipfile
from dataclasses import dataclass, asdict
from pathlib import Path

import numpy as np
import trimesh

from ..events import CancelToken, StageLogger
from ..mesh_io import TexturedModel, write_obj, to_trimesh_scene, merged_geometry
from .dae import write_dae

FORMATS = ("obj", "glb", "stl", "ply", "dae")


@dataclass
class ExportResult:
    format: str
    path: str                 # main file (or zip)
    files: list[str]          # every file produced
    size_bytes: int
    num_faces: int
    textured: bool
    note: str = ""


def _zip(paths: list[Path], zip_path: Path, base: Path) -> Path:
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for p in paths:
            z.write(p, arcname=str(p.relative_to(base)))
    return zip_path


def export_obj(model: TexturedModel, out_dir: Path, name: str, zip_bundle: bool = True) -> ExportResult:
    d = Path(out_dir) / f"{name}_obj"
    if d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True)
    obj = d / f"{name}.obj"
    textures = write_obj(model, obj)
    files = [obj, obj.with_suffix(".mtl"), *textures]
    main = _zip(files, Path(out_dir) / f"{name}_obj.zip", d) if zip_bundle else obj
    return ExportResult("obj", str(main), [str(f) for f in files], main.stat().st_size, model.num_faces, bool(textures))


def export_glb(model: TexturedModel, out_dir: Path, name: str) -> ExportResult:
    out = Path(out_dir) / f"{name}.glb"
    scene = to_trimesh_scene(model)
    scene.export(out, file_type="glb")
    return ExportResult("glb", str(out), [str(out)], out.stat().st_size, model.num_faces, bool(model.textures))


def export_stl(model: TexturedModel, out_dir: Path, name: str) -> ExportResult:
    out = Path(out_dir) / f"{name}.stl"
    merged_geometry(model).export(out, file_type="stl")
    return ExportResult("stl", str(out), [str(out)], out.stat().st_size, model.num_faces, False,
                        note="Le STL ne contient que la géométrie : les textures photographiques ne sont pas conservées.")


def export_ply(model: TexturedModel, out_dir: Path, name: str, point_cloud: Path | None = None) -> ExportResult:
    out = Path(out_dir) / f"{name}.ply"
    merged_geometry(model).export(out, file_type="ply", encoding="binary")
    files = [out]
    note = "Maillage sans texture."
    if point_cloud and Path(point_cloud).exists():
        pc = Path(out_dir) / f"{name}_pointcloud.ply"
        shutil.copyfile(point_cloud, pc)
        files.append(pc)
        note += " Le nuage de points dense est fourni séparément (" + pc.name + ")."
    return ExportResult("ply", str(out), [str(f) for f in files], out.stat().st_size, model.num_faces, False, note)


def export_dae(model: TexturedModel, out_dir: Path, name: str, zip_bundle: bool = True,
               unit_scale: float | None = None, calibrated: bool | None = None) -> ExportResult:
    d = Path(out_dir) / f"{name}_dae"
    if d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True)
    dae = d / f"{name}.dae"
    textures = write_dae(model, dae, unit_scale=unit_scale)
    files = [dae, *textures]
    main = _zip(files, Path(out_dir) / f"{name}_dae.zip", d) if zip_bundle else dae
    note = "Importer dans SketchUp via Fichier > Importer (COLLADA). Le dossier 'textures' doit rester à côté du .dae."
    if not (calibrated if calibrated is not None else unit_scale):
        note += " Échelle non étalonnée : utilisez l'outil d'étalonnage avant un usage métrique."
    else:
        note += " Échelle étalonnée : dimensions en mètres."
    return ExportResult("dae", str(main), [str(f) for f in files], main.stat().st_size, model.num_faces, bool(textures), note)


def merge_exports_json(out_dir: Path, results: list[ExportResult], extra: dict | None = None) -> None:
    """exports.json keeps one entry per produced file (successive exports accumulate)."""
    f = Path(out_dir) / "exports.json"
    entries: dict[str, dict] = {}
    if f.exists():
        try:
            for e in json.loads(f.read_text(encoding="utf-8")):
                entries[Path(e["path"]).name] = e
        except (ValueError, KeyError):
            pass
    for r in results:
        entries[Path(r.path).name] = asdict(r)
    for name, more in (extra or {}).items():
        entries.setdefault(name, {}).update(more)
    f.write_text(json.dumps(list(entries.values()), indent=2), encoding="utf-8")


def run_exports(model: TexturedModel, out_dir: Path, name: str, formats: tuple[str, ...], logger: StageLogger,
                cancel: CancelToken | None = None, point_cloud: Path | None = None,
                unit_scale: float | None = None) -> list[ExportResult]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    logger.start(f"Export : {', '.join(f.upper() for f in formats)}")
    if unit_scale:
        # calibrated: every format is written in metres
        model = copy.deepcopy(model)
        model.apply_transform(np.diag([unit_scale, unit_scale, unit_scale, 1.0]))
        logger.log(f"Échelle étalonnée appliquée : 1 unité = {unit_scale:.6g} m, exports en mètres")
    results: list[ExportResult] = []
    for i, fmt in enumerate(formats):
        if cancel:
            cancel.check()
        if fmt not in FORMATS:
            logger.log(f"Format inconnu ignoré : {fmt}")
            continue
        if fmt == "obj":
            r = export_obj(model, out_dir, name)
        elif fmt == "glb":
            r = export_glb(model, out_dir, name)
        elif fmt == "stl":
            r = export_stl(model, out_dir, name)
        elif fmt == "ply":
            r = export_ply(model, out_dir, name, point_cloud)
        else:
            r = export_dae(model, out_dir, name, unit_scale=None, calibrated=bool(unit_scale))
        results.append(r)
        logger.progress((i + 1) / len(formats), f"{fmt.upper()} : {Path(r.path).name} ({r.size_bytes / 1e6:.1f} Mo)")
    merge_exports_json(out_dir, results)
    logger.finish(f"{len(results)} export(s) produit(s)", formats=[r.format for r in results])
    return results
