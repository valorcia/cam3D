"""COLLADA (.dae) writer tuned for SketchUp.

Why a dedicated writer instead of Blender: a pure-Python writer (pycollada,
BSD) has no heavyweight dependency, is deterministic and lets us control
exactly what SketchUp's importer sees:

* ``<up_axis>Z_UP</up_axis>`` with coordinates converted to Z-up (SketchUp is
  Z-up; some importers ignore ``up_axis`` so the data itself is Z-up too),
* ``<unit meter="1" name="meter"/>``,
* one ``<triangles>`` per material, VERTEX / NORMAL / TEXCOORD(set 0),
* ``<bind_vertex_input semantic="UVSET0" input_semantic="TEXCOORD" input_set="0"/>``
  (the binding SketchUp and Blender expect),
* lambert effect with a ``<texture texcoord="UVSET0">`` diffuse,
* texture paths relative to the .dae (``textures/<name>``), ASCII-safe names.

The function returns the list of files that must accompany the .dae; the
export stage zips them together.
"""
from __future__ import annotations

import re
import shutil
from pathlib import Path

import collada
import numpy as np
from collada import asset, geometry, material, scene, source

from ..mesh_io import TexturedModel

_Y_TO_Z_UP = np.array([[1, 0, 0], [0, 0, -1], [0, 1, 0]], dtype=np.float64)  # (x,y,z)->(x,-z,y)


def _safe(name: str) -> str:
    s = re.sub(r"[^A-Za-z0-9_\-]", "_", name)
    return s or "item"


def write_dae(model: TexturedModel, dae_path: Path, texture_subdir: str = "textures",
              convert_to_z_up: bool = True, unit_scale: float | None = None,
              author: str = "cam3D") -> list[Path]:
    dae_path = Path(dae_path)
    dae_path.parent.mkdir(parents=True, exist_ok=True)
    tex_dir = dae_path.parent / texture_subdir
    written: list[Path] = []

    doc = collada.Collada()
    doc.assetInfo.upaxis = asset.UP_AXIS.Z_UP if convert_to_z_up else asset.UP_AXIS.Y_UP
    doc.assetInfo.unitmeter = 1.0
    doc.assetInfo.unitname = "meter"
    contributor = asset.Contributor(author=author, authoring_tool="cam3D")
    doc.assetInfo.contributors.append(contributor)

    nodes = []
    scale = float(unit_scale) if unit_scale else 1.0
    for i, part in enumerate(model.parts):
        pid = f"{_safe(part.name)}_{i}"
        # ---- material / effect / image
        diffuse = None
        params = []
        if part.texture is not None and part.uv is not None:
            tex_dir.mkdir(parents=True, exist_ok=True)
            tex_name = f"{_safe(dae_path.stem)}_{i}{Path(part.texture).suffix.lower()}"
            dst = tex_dir / tex_name
            if Path(part.texture).resolve() != dst.resolve():
                shutil.copyfile(part.texture, dst)
            written.append(dst)
            image = material.CImage(f"{pid}_img", f"{texture_subdir}/{tex_name}")
            surface = material.Surface(f"{pid}_surface", image)
            sampler = material.Sampler2D(f"{pid}_sampler", surface)
            diffuse = material.Map(sampler, "UVSET0")
            params = [surface, sampler]
            doc.images.append(image)
        else:
            diffuse = tuple(part.diffuse_color) + (1.0,)
        effect = material.Effect(f"{pid}_effect", params, "lambert", diffuse=diffuse,
                                 ambient=(1.0, 1.0, 1.0, 1.0), specular=(0.0, 0.0, 0.0, 1.0), double_sided=True)
        mat = material.Material(f"{pid}_material", f"{pid}_material", effect)
        doc.effects.append(effect)
        doc.materials.append(mat)

        # ---- geometry
        verts = part.vertices * scale
        normals = part.normals if part.normals is not None else part.compute_normals()
        if convert_to_z_up:
            verts = verts @ _Y_TO_Z_UP.T
            normals = normals @ _Y_TO_Z_UP.T
        vsrc = source.FloatSource(f"{pid}_positions", np.asarray(verts, dtype=np.float32).ravel(), ("X", "Y", "Z"))
        nsrc = source.FloatSource(f"{pid}_normals", np.asarray(normals, dtype=np.float32).ravel(), ("X", "Y", "Z"))
        sources = [vsrc, nsrc]
        inputs = source.InputList()
        inputs.addInput(0, "VERTEX", f"#{pid}_positions")
        inputs.addInput(1, "NORMAL", f"#{pid}_normals")
        if part.uv is not None:
            tsrc = source.FloatSource(f"{pid}_uv", np.asarray(part.uv, dtype=np.float32).ravel(), ("S", "T"))
            sources.append(tsrc)
            inputs.addInput(2, "TEXCOORD", f"#{pid}_uv", set="0")
            idx = np.repeat(part.faces, 3, axis=1).astype(np.int64)  # v,n,t share the index
        else:
            idx = np.repeat(part.faces, 2, axis=1).astype(np.int64)
        geom = geometry.Geometry(doc, f"{pid}_geometry", pid, sources)
        triset = geom.createTriangleSet(idx.ravel(), inputs, f"{pid}_matsym")
        geom.primitives.append(triset)
        doc.geometries.append(geom)
        matnode = scene.MaterialNode(f"{pid}_matsym", mat, inputs=[("UVSET0", "TEXCOORD", "0")])
        geomnode = scene.GeometryNode(geom, [matnode])
        nodes.append(scene.Node(f"{pid}_node", children=[geomnode]))

    root = scene.Node("cam3D_model", children=nodes)
    sc = scene.Scene("scene", [root])
    doc.scenes.append(sc)
    doc.scene = sc
    doc.write(str(dae_path))
    return written
