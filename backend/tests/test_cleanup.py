import numpy as np

from cam3d.engine.events import Stage, StageLogger
from cam3d.engine.mesh_io import TexturedModel
from cam3d.engine.stages.cleanup import canonical_transform, remove_small_components, rotation_to_y_up, run_cleanup
from conftest import make_cube_part


def test_rotation_to_y_up():
    for up in ([0, -1, 0], [1, 0, 0], [0, 0, 1], [0.3, -0.9, 0.1]):
        R = rotation_to_y_up(np.array(up, dtype=float))[:3, :3]
        u = np.array(up, dtype=float)
        u /= np.linalg.norm(u)
        np.testing.assert_allclose(R @ u, [0, 1, 0], atol=1e-9)
        np.testing.assert_allclose(np.linalg.det(R), 1.0, atol=1e-9)


def test_remove_small_components_keeps_uv(texture_file):
    big = make_cube_part("big", size=10.0, texture=texture_file)
    # a tiny floating cube merged into the same part -> must be removed
    tiny = make_cube_part("tiny", offset=(50, 50, 50), size=0.1, texture=texture_file)
    merged_vertices = np.vstack([big.vertices, tiny.vertices])
    merged_faces = np.vstack([big.faces, tiny.faces + len(big.vertices)])
    merged_uv = np.vstack([big.uv, tiny.uv])
    big.vertices, big.faces, big.uv = merged_vertices, merged_faces, merged_uv
    model = TexturedModel(parts=[big])
    # both components have 12 faces: use min_faces=0 so the fraction rule decides (equal -> both kept)
    removed = remove_small_components(model, min_fraction=0.02, min_faces=0)
    assert removed == 0 and model.num_faces == 24
    # absolute threshold above both: the largest component must survive anyway
    removed = remove_small_components(model, min_fraction=0.02, min_faces=13)
    assert removed == 1 and model.num_faces == 12
    assert model.parts[0].uv is not None and len(model.parts[0].uv) == len(model.parts[0].vertices)


def test_canonical_transform_grounds_model(cube_model, tmp_path):
    lg = StageLogger(Stage.CLEANUP, tmp_path / "logs")
    run_cleanup(cube_model, lg, up_vector=[0, 0, 1])
    lg.close()
    lo, hi = cube_model.bounds()
    np.testing.assert_allclose(lo, [-0.5, 0.0, -0.5], atol=1e-9)
    np.testing.assert_allclose(hi, [0.5, 1.0, 0.5], atol=1e-9)
    assert cube_model.parts[0].uv is not None
