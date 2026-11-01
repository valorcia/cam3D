import os
import shutil
import subprocess
import zipfile

import collada
import trimesh

from cam3d.engine.events import Stage, StageLogger
from cam3d.engine.stages.dae import write_dae
from cam3d.engine.stages.export import run_exports


def test_dae_writer_sketchup_conventions(cube_model, tmp_path):
    dae = tmp_path / "exp" / "cube.dae"
    files = write_dae(cube_model, dae)
    assert dae.exists() and len(files) == 1 and files[0].parent.name == "textures"
    doc = collada.Collada(str(dae))
    assert doc.assetInfo.upaxis == collada.asset.UP_AXIS.Z_UP
    assert doc.assetInfo.unitmeter == 1.0
    prim = doc.geometries[0].primitives[0]
    assert len(prim) == 12 and len(prim.texcoordset) == 1 and prim.normal is not None
    assert doc.images[0].path == "textures/cube_0.jpg"
    assert (dae.parent / doc.images[0].path).exists()
    xml = dae.read_text()
    assert 'semantic="UVSET0"' in xml and 'input_semantic="TEXCOORD"' in xml
    # geometry really is Z-up: the cube's vertical extent (engine Y) is now on Z
    v = prim.vertex
    assert v[:, 2].max() - v[:, 2].min() == 1.0
    if shutil.which("assimp"):
        out = subprocess.run(["assimp", "info", str(dae)], capture_output=True, text=True)
        assert out.returncode == 0 and "Faces:" in out.stdout


def test_run_exports_all_formats(cube_model, tmp_path):
    lg = StageLogger(Stage.EXPORT, tmp_path / "logs")
    res = run_exports(cube_model, tmp_path / "exports", "cube", ("obj", "glb", "stl", "ply", "dae"), lg)
    lg.close()
    by = {r.format: r for r in res}
    assert set(by) == {"obj", "glb", "stl", "ply", "dae"}
    for fmt in ("obj", "dae"):
        with zipfile.ZipFile(by[fmt].path) as z:
            names = z.namelist()
            assert any(n.endswith(f".{fmt}") for n in names) and any(n.endswith(".jpg") for n in names)
    assert by["stl"].textured is False and "textures" in by["stl"].note
    glb = trimesh.load(by["glb"].path)
    g = list(glb.geometry.values())[0]
    assert isinstance(g.visual, trimesh.visual.TextureVisuals) and g.visual.material.baseColorTexture is not None
    assert os.path.getsize(by["ply"].path) > 0
