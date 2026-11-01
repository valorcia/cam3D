from pathlib import Path

from cam3d.engine.stages.mvs import _texture_outputs


def test_texture_outputs_never_match_input_mesh(tmp_path: Path):
    for n in ["preview.glb", "preview_0.png", "preview_material_0_map_Kd.jpg", "preview_mesh.ply",
              "decimated_preview.ply", "textured.glb", "textured_0.png", "scene_dense_mesh.ply"]:
        (tmp_path / n).write_bytes(b"x")
    got = sorted(p.name for p in _texture_outputs(tmp_path, "preview"))
    assert got == ["preview.glb", "preview_0.png", "preview_material_0_map_Kd.jpg"]
    assert sorted(p.name for p in _texture_outputs(tmp_path, "textured")) == ["textured.glb", "textured_0.png"]


def test_write_ply_points_roundtrip(tmp_path: Path):
    import numpy as np
    import open3d as o3d

    from cam3d.engine.pipeline import write_ply_points

    xyz = np.random.default_rng(0).random((1000, 3))
    rgb = np.random.default_rng(1).random((1000, 3))
    f = tmp_path / "pc.ply"
    write_ply_points(f, xyz, rgb)
    assert f.stat().st_size < 1000 * 15 + 300
    pc = o3d.io.read_point_cloud(str(f))
    assert len(pc.points) == 1000
    np.testing.assert_allclose(np.asarray(pc.points), xyz, atol=1e-6)
    np.testing.assert_allclose(np.asarray(pc.colors), np.round(rgb * 255) / 255, atol=1e-6)
