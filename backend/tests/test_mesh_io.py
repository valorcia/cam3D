import numpy as np

from cam3d.engine.mesh_io import load_obj, write_obj, merged_geometry


def test_obj_roundtrip_keeps_uv_and_texture(cube_model, tmp_path):
    obj = tmp_path / "out" / "cube.obj"
    textures = write_obj(cube_model, obj, texture_dir=tmp_path / "out" / "tex", texture_rel="tex/")
    assert len(textures) == 1 and textures[0].exists()
    mtl = (tmp_path / "out" / "cube.mtl").read_text()
    assert "map_Kd tex/cube_0.jpg" in mtl
    back = load_obj(obj)
    assert len(back.parts) == 1
    p = back.parts[0]
    assert p.num_faces == 12 and len(p.vertices) == 24
    assert p.uv is not None and p.uv.shape == (24, 2)
    assert p.texture is not None and p.texture.exists()
    np.testing.assert_allclose(np.sort(p.vertices, axis=0), np.sort(cube_model.parts[0].vertices, axis=0), atol=1e-5)


def test_apply_transform_flips_winding_on_reflection(cube_model):
    m = merged_geometry(cube_model)
    vol_before = m.volume
    M = np.diag([-1.0, 1.0, 1.0, 1.0])
    cube_model.apply_transform(M)
    assert merged_geometry(cube_model).volume > 0 and abs(merged_geometry(cube_model).volume - vol_before) < 1e-6


def test_glb_roundtrip_keeps_uv_and_texture(cube_model, tmp_path):
    from cam3d.engine.mesh_io import load_glb, load_model, to_trimesh_scene

    glb = tmp_path / "cube.glb"
    to_trimesh_scene(cube_model).export(glb, file_type="glb")
    back = load_model(glb)
    assert len(back.parts) == 1
    p = back.parts[0]
    assert p.num_faces == 12 and p.uv is not None and len(p.uv) == len(p.vertices)
    assert p.texture is not None and p.texture.suffix == ".jpg" and p.texture.exists()
    assert load_glb(glb).num_faces == 12
