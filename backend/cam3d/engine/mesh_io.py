"""Textured mesh container + readers/writers that keep UVs and textures intact.

A :class:`TexturedModel` is a list of :class:`MeshPart`; each part has one
material (one texture image). OpenMVS usually produces a single atlas, but the
format supports several so that merged/imported models work too.

Coordinate convention inside the engine: **Y up**, right-handed, unit unknown
until the model is calibrated (see ``scale`` metadata).
"""
from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import trimesh
from PIL import Image


@dataclass
class MeshPart:
    name: str
    vertices: np.ndarray          # (V,3) float64
    faces: np.ndarray             # (F,3) int64, indices into vertices
    uv: np.ndarray | None         # (V,2) float32 per-vertex UV (0..1, V flipped = OBJ convention) or None
    texture: Path | None          # image file on disk, or None
    normals: np.ndarray | None = None  # (V,3) per-vertex normals (recomputed on demand)
    diffuse_color: tuple[float, float, float] = (0.8, 0.8, 0.8)

    @property
    def num_faces(self) -> int:
        return int(len(self.faces))

    def as_trimesh(self) -> trimesh.Trimesh:
        visual = None
        if self.uv is not None:
            img = Image.open(self.texture) if self.texture else None
            mat = trimesh.visual.material.SimpleMaterial(image=img, diffuse=[int(c * 255) for c in self.diffuse_color] + [255])
            visual = trimesh.visual.TextureVisuals(uv=self.uv, material=mat)
        return trimesh.Trimesh(self.vertices, self.faces, visual=visual, process=False)

    def compute_normals(self) -> np.ndarray:
        tm = trimesh.Trimesh(self.vertices, self.faces, process=False)
        self.normals = np.asarray(tm.vertex_normals, dtype=np.float64)
        return self.normals


@dataclass
class TexturedModel:
    parts: list[MeshPart] = field(default_factory=list)
    up_axis: str = "Y"  # engine convention; exporters convert as needed
    unit_scale: float | None = None  # metres per model unit when calibrated, else None

    @property
    def num_faces(self) -> int:
        return sum(p.num_faces for p in self.parts)

    @property
    def num_vertices(self) -> int:
        return sum(len(p.vertices) for p in self.parts)

    @property
    def textures(self) -> list[Path]:
        return [p.texture for p in self.parts if p.texture]

    def bounds(self) -> tuple[np.ndarray, np.ndarray]:
        allv = np.vstack([p.vertices for p in self.parts])
        return allv.min(axis=0), allv.max(axis=0)

    def apply_transform(self, m: np.ndarray) -> None:
        """Apply a 4x4 homogeneous transform to every part (normals recomputed)."""
        R = m[:3, :3]
        t = m[:3, 3]
        flip = np.linalg.det(R) < 0
        for p in self.parts:
            p.vertices = p.vertices @ R.T + t
            if flip:  # keep outward orientation under reflections
                p.faces = p.faces[:, [0, 2, 1]]
            p.normals = None


# ----------------------------------------------------------------------------
# OBJ reading (via trimesh, which handles multi-material + vt/vn indices)
# ----------------------------------------------------------------------------

def load_obj(path: Path) -> TexturedModel:
    path = Path(path)
    loaded = trimesh.load(path, process=False, force=None, maintain_order=True)
    geoms: list[tuple[str, trimesh.Trimesh]]
    if isinstance(loaded, trimesh.Scene):
        geoms = [(name, g) for name, g in loaded.geometry.items() if isinstance(g, trimesh.Trimesh)]
    else:
        geoms = [(path.stem, loaded)]
    model = TexturedModel()
    for name, g in geoms:
        uv = None
        tex = None
        color = (0.8, 0.8, 0.8)
        vis = g.visual
        if isinstance(vis, trimesh.visual.TextureVisuals) and vis.uv is not None and len(vis.uv) == len(g.vertices):
            uv = np.asarray(vis.uv, dtype=np.float32)
            mat = vis.material
            # Resolve map_Kd ourselves from the MTL: trimesh refuses relative paths that leave the
            # OBJ's folder (e.g. "../textures/x.jpg") and then silently returns no image.
            src = _find_texture_file(path, mat)
            if src is not None:
                tex = src
            else:
                img = getattr(mat, "image", None)
                if img is None and hasattr(mat, "baseColorTexture"):
                    img = mat.baseColorTexture
                if img is not None:  # texture only available in memory: dump it next to the OBJ
                    tex = path.parent / f"{path.stem}_{len(model.parts)}.png"
                    img.save(tex)
            d = getattr(mat, "diffuse", None)
            if d is not None and len(d) >= 3:
                color = tuple(float(x) / 255.0 for x in d[:3])
        model.parts.append(MeshPart(name, np.asarray(g.vertices, dtype=np.float64), np.asarray(g.faces, dtype=np.int64), uv, tex, diffuse_color=color))
    if not model.parts:
        raise RuntimeError(f"Aucune géométrie lisible dans {path}")
    return model


def load_glb(path: Path, texture_dir: Path | None = None, jpeg_quality: int = 95) -> TexturedModel:
    """Load a GLB/glTF (e.g. OpenMVS ``--export-type glb``); embedded textures are
    written next to the file as JPEG (photographic data, much smaller than PNG)."""
    path = Path(path)
    texture_dir = Path(texture_dir) if texture_dir else path.parent
    texture_dir.mkdir(parents=True, exist_ok=True)
    loaded = trimesh.load(path, process=False, force=None)
    geoms = list(loaded.geometry.items()) if isinstance(loaded, trimesh.Scene) else [(path.stem, loaded)]
    model = TexturedModel()
    for i, (name, g) in enumerate(geoms):
        if not isinstance(g, trimesh.Trimesh) or len(g.faces) == 0:
            continue
        uv = tex = None
        vis = g.visual
        if isinstance(vis, trimesh.visual.TextureVisuals) and vis.uv is not None and len(vis.uv) == len(g.vertices):
            uv = np.asarray(vis.uv, dtype=np.float32)
            img = getattr(vis.material, "baseColorTexture", None) or getattr(vis.material, "image", None)
            if img is not None:
                tex = texture_dir / f"{path.stem}_{i}.jpg"
                img.convert("RGB").save(tex, "JPEG", quality=jpeg_quality, subsampling=0)
        model.parts.append(MeshPart(name, np.asarray(g.vertices, dtype=np.float64), np.asarray(g.faces, dtype=np.int64), uv, tex))
    if not model.parts:
        raise RuntimeError(f"Aucune géométrie lisible dans {path}")
    return model


def load_model(path: Path) -> TexturedModel:
    path = Path(path)
    if path.suffix.lower() in {".glb", ".gltf"}:
        return load_glb(path)
    return load_obj(path)


def _find_texture_file(obj_path: Path, material) -> Path | None:
    """Resolve the map_Kd file referenced by the MTL for this material."""
    mtl_path = None
    with open(obj_path, "r", encoding="utf-8", errors="ignore") as fh:
        for line in fh:
            if line.startswith("mtllib"):
                mtl_path = obj_path.parent / line.split(None, 1)[1].strip()
                break
    if mtl_path is None or not mtl_path.exists():
        return None
    current = None
    mats: dict[str, Path] = {}
    for line in mtl_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if line.startswith("newmtl"):
            current = line.split(None, 1)[1].strip()
        elif line.startswith("map_Kd") and current:
            mats[current] = (mtl_path.parent / line.split(None, 1)[1].strip()).resolve()
    name = getattr(material, "name", None)
    if name in mats and mats[name].exists():
        return mats[name]
    if len(mats) == 1:
        p = next(iter(mats.values()))
        return p if p.exists() else None
    return None


# ----------------------------------------------------------------------------
# OBJ writing (own writer: predictable relative paths, no re-encoding of textures)
# ----------------------------------------------------------------------------

def write_obj(model: TexturedModel, obj_path: Path, texture_dir: Path | None = None, texture_rel: str = "",
              write_normals: bool = True) -> list[Path]:
    """Write ``obj_path`` (+ ``.mtl``) and copy textures.

    ``texture_dir``: where to copy texture files (default: next to the OBJ).
    ``texture_rel``: path prefix written in the MTL (e.g. ``"../textures/"``).
    Returns the list of texture files written.
    """
    obj_path = Path(obj_path)
    obj_path.parent.mkdir(parents=True, exist_ok=True)
    mtl_path = obj_path.with_suffix(".mtl")
    texture_dir = Path(texture_dir) if texture_dir else obj_path.parent
    texture_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    with open(obj_path, "w", encoding="utf-8") as fo, open(mtl_path, "w", encoding="utf-8") as fm:
        fo.write("# cam3D textured mesh (Y up)\n")
        fo.write(f"mtllib {mtl_path.name}\n")
        v_off = 0
        for i, p in enumerate(model.parts):
            mat = f"material_{i}"
            fm.write(f"newmtl {mat}\nKa 1.000 1.000 1.000\nKd {p.diffuse_color[0]:.3f} {p.diffuse_color[1]:.3f} {p.diffuse_color[2]:.3f}\nKs 0.000 0.000 0.000\nd 1.0\nillum 1\n")
            if p.texture is not None:
                tex_name = f"{obj_path.stem}_{i}{Path(p.texture).suffix.lower()}"
                dst = texture_dir / tex_name
                if Path(p.texture).resolve() != dst.resolve():
                    shutil.copyfile(p.texture, dst)
                written.append(dst)
                fm.write(f"map_Kd {texture_rel}{tex_name}\n")
            fm.write("\n")
            fo.write(f"o {p.name}\nusemtl {mat}\n")
            np.savetxt(fo, p.vertices, fmt="v %.6f %.6f %.6f")
            has_uv = p.uv is not None
            if has_uv:
                np.savetxt(fo, p.uv, fmt="vt %.6f %.6f")
            if write_normals:
                n = p.normals if p.normals is not None else p.compute_normals()
                np.savetxt(fo, n, fmt="vn %.4f %.4f %.4f")
            f1 = p.faces + 1 + v_off
            if has_uv and write_normals:
                lines = np.char.add(np.char.add(np.char.add(f1.astype(str), "/"), f1.astype(str)), "/")
                lines = np.char.add(lines, f1.astype(str))
                np.savetxt(fo, lines, fmt="f %s %s %s")
            elif has_uv:
                lines = np.char.add(np.char.add(f1.astype(str), "/"), f1.astype(str))
                np.savetxt(fo, lines, fmt="f %s %s %s")
            elif write_normals:
                lines = np.char.add(np.char.add(f1.astype(str), "//"), f1.astype(str))
                np.savetxt(fo, lines, fmt="f %s %s %s")
            else:
                np.savetxt(fo, f1, fmt="f %d %d %d")
            v_off += len(p.vertices)
    return written


def to_trimesh_scene(model: TexturedModel) -> trimesh.Scene:
    scene = trimesh.Scene()
    for p in model.parts:
        scene.add_geometry(p.as_trimesh(), geom_name=p.name)
    return scene


def merged_geometry(model: TexturedModel) -> trimesh.Trimesh:
    """Geometry only (no UV) - for STL/PLY and metrics."""
    return trimesh.util.concatenate([trimesh.Trimesh(p.vertices, p.faces, process=False) for p in model.parts])
