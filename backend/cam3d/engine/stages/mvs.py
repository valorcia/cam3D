"""Stages 3-5 - dense reconstruction, meshing, refinement, texturing (OpenMVS).

Layout inside ``work_dir``::

    dense/            COLMAP undistorted workspace (images/, sparse/)
    mvs/scene.mvs     OpenMVS scene imported from COLMAP
    mvs/scene_dense.mvs / .ply
    mvs/scene_dense_mesh.mvs / .ply
    mvs/scene_dense_mesh_refine.mvs / .ply       (ULTRA only)
    mvs/textured.obj / textured.mtl / textured_*.jpg

Each OpenMVS tool is run as a subprocess with its log streamed to
``logs/<stage>.log``. OpenMVS is AGPL-3.0: it is invoked as a separate
process, never linked (see ARCHITECTURE.md, "Licences").
"""
from __future__ import annotations

import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pycolmap

from ..events import CancelToken, StageLogger
from ..profiles import QualityProfile
from ..subprocess_utils import ToolError, run_tool
from ..tools import ToolRegistry

_PROGRESS_RE = re.compile(r"(\d+)\s*/\s*(\d+)")  # e.g. "Depth-map 3/11"


@dataclass
class DenseResult:
    scene_mvs: str
    dense_mvs: str
    dense_ply: str
    num_points: int


@dataclass
class MeshResult:
    scene_mvs: str   # dense scene (.mvs) the mesh belongs to; OpenMVS tools take it + --mesh-file
    mesh_ply: str
    num_vertices: int
    num_faces: int


@dataclass
class TextureResult:
    obj_path: str      # textured model file (GLB by default, OBJ if requested)
    mtl_path: str
    textures: list[str]
    num_vertices: int
    num_faces: int


def _count_ply(path: Path) -> tuple[int, int]:
    """Return (vertices, faces) from a PLY header without loading the data."""
    v = f = 0
    with open(path, "rb") as fh:
        for raw in fh:
            line = raw.decode("ascii", "ignore").strip()
            if line.startswith("element vertex"):
                v = int(line.split()[-1])
            elif line.startswith("element face"):
                f = int(line.split()[-1])
            elif line == "end_header":
                break
    return v, f


def _stream(logger: StageLogger, total_hint: str | None = None):
    def on_line(line: str) -> None:
        logger.raw(line)
        if total_hint and total_hint in line:
            m = _PROGRESS_RE.search(line)
            if m:
                done, total = int(m.group(1)), int(m.group(2))
                if total > 0:
                    logger.progress(done / total, line.strip()[:120])
    return on_line


def _common_args(threads: int) -> list[str]:
    return ["--max-threads", str(threads), "--process-priority", "0", "-v", "2"]


def prepare_openmvs_scene(work_dir: Path, tools: ToolRegistry, logger: StageLogger, threads: int,
                          cancel: CancelToken | None = None) -> Path:
    """COLMAP undistortion -> InterfaceCOLMAP -> mvs/scene.mvs"""
    work_dir = Path(work_dir)
    sparse0 = work_dir / "sparse" / "0"
    dense_dir = work_dir / "dense"
    mvs_dir = work_dir / "mvs"
    for d in (dense_dir, mvs_dir):
        if d.exists():
            shutil.rmtree(d)
    mvs_dir.mkdir(parents=True)
    logger.log("Correction de la distorsion des images (COLMAP undistort -> PINHOLE)")
    pycolmap.undistort_images(output_path=dense_dir, input_path=sparse0, image_path=work_dir / "images",
                              output_type="COLMAP", num_threads=threads)
    if cancel:
        cancel.check()
    rec = pycolmap.Reconstruction(dense_dir / "sparse")
    rec.write_text(dense_dir / "sparse")  # InterfaceCOLMAP 2.3 reads the text files
    scene = mvs_dir / "scene.mvs"
    logger.log("Import de la scène COLMAP dans OpenMVS (InterfaceCOLMAP)")
    run_tool(
        [tools.openmvs_bin("InterfaceCOLMAP"), "-w", str(mvs_dir), "-i", str(dense_dir), "-o", str(scene),
         "--image-folder", str(dense_dir / "images") + os.sep, *_common_args(threads)],
        cwd=mvs_dir, on_line=_stream(logger), cancel=cancel,
    )
    if not scene.exists():
        raise RuntimeError("InterfaceCOLMAP n'a pas produit scene.mvs (voir logs/dense.log).")
    return scene


def run_densify(work_dir: Path, profile: QualityProfile, tools: ToolRegistry, logger: StageLogger,
                cancel: CancelToken | None = None, threads: int = 0) -> DenseResult:
    threads = threads or (os.cpu_count() or 2)
    logger.start(f"Reconstruction dense OpenMVS (niveau {profile.densify_resolution_level}, max {profile.densify_max_resolution}px)")
    scene = prepare_openmvs_scene(work_dir, tools, logger, threads, cancel)
    mvs_dir = scene.parent
    out = mvs_dir / "scene_dense.mvs"
    cmd = [
        tools.openmvs_bin("DensifyPointCloud"), str(scene), "-w", str(mvs_dir), "-o", str(out),
        "--resolution-level", str(profile.densify_resolution_level),
        "--max-resolution", str(profile.densify_max_resolution),
        "--number-views-fuse", str(profile.densify_number_views_fuse),
        "--estimate-normals", str(profile.densify_estimate_normals),
        "--filter-point-cloud", str(profile.densify_filter_iters),
        "--remove-dmaps", "1",
        *_common_args(threads),
    ]
    if profile.name == "fast":
        cmd += ["--geometric-iters", "0"]
    logger.log("DensifyPointCloud : " + " ".join(Path(c).name if i == 0 else c for i, c in enumerate(cmd)))
    run_tool(cmd, cwd=mvs_dir, on_line=_stream(logger, "Estimated depth-map"), cancel=cancel)
    ply = mvs_dir / "scene_dense.ply"
    if not out.exists() or not ply.exists():
        raise RuntimeError("DensifyPointCloud n'a pas produit de nuage dense (voir logs/dense.log).")
    n, _ = _count_ply(ply)
    if n < 1000:
        raise RuntimeError(f"Nuage dense trop pauvre ({n} points) : les images manquent probablement de recouvrement ou de texture.")
    logger.finish(f"Nuage dense : {n:,} points".replace(",", " "), num_points=n)
    return DenseResult(str(scene), str(out), str(ply), n)


def run_mesh(work_dir: Path, profile: QualityProfile, tools: ToolRegistry, logger: StageLogger,
             dense: DenseResult, cancel: CancelToken | None = None, threads: int = 0) -> MeshResult:
    threads = threads or (os.cpu_count() or 2)
    mvs_dir = Path(dense.dense_mvs).parent
    out = mvs_dir / "scene_dense_mesh.mvs"   # ReconstructMesh writes <out>.ply (the .mvs only for non-default archive types)
    logger.start("Maillage (ReconstructMesh, Delaunay + graph-cut)")
    cmd = [
        tools.openmvs_bin("ReconstructMesh"), dense.dense_mvs, "-w", str(mvs_dir), "-o", str(out),
        "--min-point-distance", str(profile.mesh_min_point_distance),
        "--remove-spurious", "30", "--remove-spikes", "1", "--close-holes", "30",
        "--smooth", str(profile.mesh_smooth),
        *_common_args(threads),
    ]
    if profile.mesh_target_faces:
        cmd += ["--target-face-num", str(profile.mesh_target_faces)]
    run_tool(cmd, cwd=mvs_dir, on_line=_stream(logger), cancel=cancel)
    ply = mvs_dir / "scene_dense_mesh.ply"
    if not ply.exists():
        raise RuntimeError("ReconstructMesh n'a pas produit de maillage (voir logs/mesh.log).")
    v, f = _count_ply(ply)
    if f < 100:
        raise RuntimeError(f"Maillage dégénéré ({f} faces).")
    # geometric filtering of hallucinated surfaces (sky/background closures)
    from .meshfilter import filter_mesh
    filtered = mvs_dir / "scene_dense_mesh_filtered.ply"
    rep = filter_mesh(ply, Path(dense.dense_ply), filtered, logger, cancel=cancel,
                      report_path=Path(work_dir) / "meshfilter.json")
    if rep.faces_out >= 100:
        ply, v, f = filtered, None, rep.faces_out
        v, f = _count_ply(filtered)
    else:
        logger.log("Filtrage ignoré (trop peu de faces restantes) : maillage brut conservé")
    logger.finish(f"Maillage : {v:,} sommets, {f:,} faces".replace(",", " "), num_vertices=v, num_faces=f)
    return MeshResult(dense.dense_mvs, str(ply), v, f)


def run_refine(work_dir: Path, profile: QualityProfile, tools: ToolRegistry, logger: StageLogger,
               mesh: MeshResult, cancel: CancelToken | None = None, threads: int = 0) -> MeshResult:
    threads = threads or (os.cpu_count() or 2)
    mvs_dir = Path(mesh.scene_mvs).parent
    refine_bin = tools.openmvs.get("RefineMesh")
    if not profile.refine_enabled:
        logger.skip("Raffinement désactivé pour ce profil")
        return mesh
    if not refine_bin or not refine_bin.available:
        logger.skip("RefineMesh indisponible : étape ignorée")
        return mesh
    out = mvs_dir / "scene_dense_mesh_refine.mvs"
    logger.start(f"Raffinement photométrique du maillage (RefineMesh, niveau {profile.refine_resolution_level})")
    cmd = [
        refine_bin.path, mesh.scene_mvs, "-w", str(mvs_dir), "-o", str(out), "--mesh-file", mesh.mesh_ply,
        "--resolution-level", str(profile.refine_resolution_level),
        "--max-views", "8", "--scales", str(max(1, profile.refine_max_iters)),
        *_common_args(threads),
    ]
    run_tool(cmd, cwd=mvs_dir, on_line=_stream(logger), cancel=cancel)
    ply = mvs_dir / "scene_dense_mesh_refine.ply"
    if not ply.exists():
        logger.log("RefineMesh n'a rien produit, maillage non raffiné conservé")
        return mesh
    v, f = _count_ply(ply)
    logger.finish(f"Maillage raffiné : {v:,} sommets, {f:,} faces".replace(",", " "), num_vertices=v, num_faces=f)
    return MeshResult(mesh.scene_mvs, str(ply), v, f)


def _texture_outputs(mvs_dir: Path, name: str) -> list[Path]:
    """Files written by TextureMesh for output ``name`` — and nothing else
    (``name*`` would also match e.g. the input mesh ``name_mesh.ply``)."""
    out = [mvs_dir / f"{name}{ext}" for ext in (".glb", ".gltf", ".obj", ".mtl", ".ply")]
    out += [p for p in mvs_dir.glob(f"{name}_*") if p.suffix.lower() in {".jpg", ".jpeg", ".png"}
            and (p.stem.startswith(f"{name}_material") or p.stem[len(name) + 1:].isdigit() or "map_Kd" in p.stem)]
    return [p for p in out if p.exists()]


def decimate_mesh(mesh: MeshResult, target_faces: int, tools: ToolRegistry, logger: StageLogger,
                  cancel: CancelToken | None = None, threads: int = 0, out_name: str = "decimated_preview") -> Path:
    """Quadric decimation of an existing mesh with OpenMVS (before texturing,
    so the decimated mesh gets its own clean UV atlas)."""
    threads = threads or (os.cpu_count() or 2)
    mvs_dir = Path(mesh.scene_mvs).parent
    out = mvs_dir / f"{out_name}.mvs"
    cmd = [
        tools.openmvs_bin("ReconstructMesh"), mesh.scene_mvs, "-w", str(mvs_dir), "--mesh-file", mesh.mesh_ply,
        "-o", str(out), "--target-face-num", str(target_faces),
        "--remove-spurious", "0", "--remove-spikes", "0", "--close-holes", "0", "--smooth", "0",
        *_common_args(threads),
    ]
    run_tool(cmd, cwd=mvs_dir, on_line=_stream(logger), cancel=cancel)
    ply = mvs_dir / f"{out_name}.ply"
    if not ply.exists():
        raise RuntimeError("La décimation n'a produit aucun maillage")
    return ply


def run_texture(work_dir: Path, profile: QualityProfile, tools: ToolRegistry, logger: StageLogger,
                mesh: MeshResult, cancel: CancelToken | None = None, threads: int = 0,
                mesh_override: Path | None = None, output_name: str = "textured",
                export_type: str = "glb", allow_raw_fallback: bool = True) -> TextureResult:
    """Texture ``mesh`` (or ``mesh_override`` PLY, e.g. a cleaned/decimated one).

    The default output is GLB: OpenMVS 2.3.0's OBJ writer crashes on
    single-texture meshes unless patched (see INSTALLATION.md), while its glTF
    writer is robust on the official binaries. ``mesh_io.load_model`` reads both.

    Robustness ladder (each attempt is logged):
      1. requested mesh, global seam leveling on;
      2. same mesh, ``--global-seam-leveling 0`` (seam leveling crashes on some
         non-manifold meshes);
      3. the raw ReconstructMesh output (``scene_dense_mesh.ply``) if a filtered
         mesh was used.
    """
    threads = threads or (os.cpu_count() or 2)
    mvs_dir = Path(mesh.scene_mvs).parent
    ext = ".glb" if export_type == "glb" else ".obj"
    out = mvs_dir / f"{output_name}{ext}"
    for old in _texture_outputs(mvs_dir, output_name):
        old.unlink()
    logger.start(f"Texturage (TextureMesh, niveau {profile.texture_resolution_level}, atlas max {profile.texture_max_size}px)")

    mesh_file = Path(mesh_override) if mesh_override is not None else Path(mesh.mesh_ply)
    if not mesh_file.exists():
        raise RuntimeError(f"Maillage à texturer introuvable : {mesh_file.name}")
    raw_mesh = mvs_dir / "scene_dense_mesh.ply"
    attempts: list[tuple[Path, int]] = [(mesh_file, 1), (mesh_file, 0)]
    if allow_raw_fallback and raw_mesh.exists() and raw_mesh.resolve() != mesh_file.resolve():
        attempts.append((raw_mesh, 0))
    last_err: Exception | None = None
    for i, (mfile, seam) in enumerate(attempts, 1):
        cmd = [
            tools.openmvs_bin("TextureMesh"), mesh.scene_mvs, "-w", str(mvs_dir), "-o", str(out),
            "--mesh-file", str(mfile), "--export-type", export_type,
            "--resolution-level", str(profile.texture_resolution_level),
            "--max-texture-size", str(profile.texture_max_size),
            "--patch-packing-heuristic", str(profile.texture_patch_packing_heuristic),
            "--global-seam-leveling", str(seam), "--empty-color", "0", "--close-holes", "30",
            *_common_args(threads),
        ]
        if i > 1:
            logger.log(f"Nouvelle tentative de texturage ({i}/{len(attempts)}) : maillage {mfile.name}, seam-leveling={seam}")
        try:
            run_tool(cmd, cwd=mvs_dir, on_line=_stream(logger), cancel=cancel)
        except ToolError as e:
            last_err = e
            logger.log(f"TextureMesh a échoué (code {e.returncode}) : {e.tail.splitlines()[-1] if e.tail else ''}")
            continue
        if out.exists():
            break
        last_err = RuntimeError("TextureMesh n'a produit aucun fichier.")
    else:
        raise RuntimeError(f"Texturage impossible après {len(attempts)} tentatives : {last_err}")

    textures = sorted(str(p) for p in _texture_outputs(mvs_dir, output_name) if p.suffix.lower() in {".jpg", ".png", ".jpeg"})
    if export_type == "obj":
        mtl = out.with_suffix(".mtl")
        if not mtl.exists() or not textures:
            raise RuntimeError("TextureMesh n'a pas produit d'OBJ texturé complet (voir logs/texture.log).")
    v = f = 0
    if export_type == "obj":
        with open(out, "r", encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                if line.startswith("v "):
                    v += 1
                elif line.startswith("f "):
                    f += 1
    else:
        import trimesh

        sc = trimesh.load(out, process=False)
        geoms = list(sc.geometry.values()) if isinstance(sc, trimesh.Scene) else [sc]
        v = sum(len(g.vertices) for g in geoms)
        f = sum(len(g.faces) for g in geoms)
    logger.finish(f"Modèle texturé : {f:,} faces, {max(len(textures), 1)} texture(s)".replace(",", " "),
                  num_faces=f, textures=[Path(t).name for t in textures])
    return TextureResult(str(out), str(out.with_suffix(".mtl")) if export_type == "obj" else "", textures, v, f)
