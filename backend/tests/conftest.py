import os
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from cam3d.engine.mesh_io import MeshPart, TexturedModel


def make_cube_part(name: str, offset=(0.0, 0.0, 0.0), size=1.0, texture: Path | None = None) -> MeshPart:
    """A textured cube: 8 vertices duplicated per face (24) so UVs are per-face."""
    o = np.asarray(offset, dtype=np.float64)
    faces_def = [  # (normal axis, sign)
        (0, 1), (0, -1), (1, 1), (1, -1), (2, 1), (2, -1),
    ]
    verts, uvs, faces = [], [], []
    for axis, sign in faces_def:
        u_axis, v_axis = [(1, 2), (0, 2), (0, 1)][axis]
        base = len(verts)
        for (a, b) in [(0, 0), (1, 0), (1, 1), (0, 1)]:
            p = np.zeros(3)
            p[axis] = sign * size / 2
            p[u_axis] = (a - 0.5) * size
            p[v_axis] = (b - 0.5) * size
            verts.append(p + o)
            uvs.append([a, b])
        if sign > 0:
            faces += [[base, base + 1, base + 2], [base, base + 2, base + 3]]
        else:
            faces += [[base, base + 2, base + 1], [base, base + 3, base + 2]]
    return MeshPart(name, np.array(verts), np.array(faces, dtype=np.int64), np.array(uvs, dtype=np.float32), texture)


@pytest.fixture
def texture_file(tmp_path) -> Path:
    img = Image.fromarray((np.random.default_rng(0).random((64, 64, 3)) * 255).astype(np.uint8))
    p = tmp_path / "tex.jpg"
    img.save(p, quality=90)
    return p


@pytest.fixture
def cube_model(texture_file) -> TexturedModel:
    return TexturedModel(parts=[make_cube_part("cube", texture=texture_file)])


@pytest.fixture
def dataset_dir() -> Path:
    d = os.environ.get("CAM3D_TEST_DATASET")
    if not d or not Path(d).is_dir():
        pytest.skip("CAM3D_TEST_DATASET non défini (dossier de photos réelles requis)")
    return Path(d)
