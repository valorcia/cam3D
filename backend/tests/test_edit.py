import numpy as np
import pytest

from cam3d.engine.edit import EditError, apply_geometric_op, apply_to_points, in_screen_region, rigid_matrix, validate_op
from cam3d.engine.mesh_io import TexturedModel
from conftest import make_cube_part


def two_cubes(texture):
    a = make_cube_part("a", offset=(0, 0.5, 0), texture=texture)
    b = make_cube_part("b", offset=(5, 0.5, 0), texture=texture)
    return TexturedModel(parts=[a, b])


def ortho_top_matrix(half=10.0):
    """three.js-style column-major view-projection: orthographic camera looking down -Y."""
    # view: world (x, y, z) -> camera (x, -z, ... ) ; we only need x->ndc_x, z->ndc_y
    P = np.array([[1 / half, 0, 0, 0], [0, 0, -1 / half, 0], [0, -1 / half, 0, 0], [0, 0, 0, 1]], float)
    return P.T.reshape(-1).tolist()  # column-major


def test_validate_op_rejects_bad_input():
    with pytest.raises(EditError):
        validate_op({"type": "explode"})
    with pytest.raises(EditError):
        validate_op({"type": "crop_box", "min": [0, 0, 0], "max": [0, 1, 1]})
    with pytest.raises(EditError):
        validate_op({"type": "simplify", "target_faces": 10})
    assert validate_op({"type": "rotate", "axis": "y", "degrees": 90}) == {"type": "rotate", "axis": "y", "degrees": 90.0}


def test_crop_box_keeps_inside_and_uvs(texture_file):
    m = two_cubes(texture_file)
    r = apply_geometric_op(m, {"type": "crop_box", "min": [-1, -1, -1], "max": [1, 2, 1]})
    assert r["faces_removed"] == 12 and m.num_faces == 12
    assert all(p.uv is not None and len(p.uv) == len(p.vertices) for p in m.parts)
    with pytest.raises(EditError):
        apply_geometric_op(m, {"type": "crop_box", "min": [100, 100, 100], "max": [101, 101, 101]})


def test_delete_region_by_screen_rectangle(texture_file):
    m = two_cubes(texture_file)
    mat = ortho_top_matrix()
    # rectangle around x in [4,6] seen from the top -> NDC x in [0.4,0.6]
    poly = [[0.35, -0.2], [0.65, -0.2], [0.65, 0.2], [0.35, 0.2]]
    assert in_screen_region(np.array([[5.0, 0.5, 0.0]]), mat, poly)[0]
    assert not in_screen_region(np.array([[0.0, 0.5, 0.0]]), mat, poly)[0]
    r = apply_geometric_op(m, {"type": "delete_region", "matrix": mat, "polygon": poly})
    assert r["faces_removed"] == 12
    lo, hi = m.bounds()
    assert hi[0] <= 0.5 + 1e-9


def test_rigid_ops_preserve_distances_and_points_follow(texture_file):
    m = two_cubes(texture_file)
    before = np.linalg.norm(m.parts[1].vertices[0] - m.parts[0].vertices[0])
    pts = np.vstack([p.vertices for p in m.parts])
    op = {"type": "rotate", "axis": "y", "degrees": 90}
    M = rigid_matrix(m.bounds(), op)
    apply_geometric_op(m, op, M)
    pts2, _ = apply_to_points(pts, None, op, M)
    np.testing.assert_allclose(pts2, np.vstack([p.vertices for p in m.parts]), atol=1e-9)
    assert abs(np.linalg.norm(m.parts[1].vertices[0] - m.parts[0].vertices[0]) - before) < 1e-9
    op = {"type": "recenter"}
    apply_geometric_op(m, op, rigid_matrix(m.bounds(), op))
    lo, hi = m.bounds()
    np.testing.assert_allclose([lo[1], (lo[0] + hi[0]) / 2, (lo[2] + hi[2]) / 2], [0, 0, 0], atol=1e-9)


def test_remove_components(texture_file):
    a = make_cube_part("a", texture=texture_file)
    b = make_cube_part("b", offset=(9, 0, 0), size=0.2, texture=texture_file)
    big = make_cube_part("big", size=1.0, texture=texture_file)
    # merge a tiny far cube into the same part as a big one, with a larger "big" made of 2 cubes
    a.vertices = np.vstack([a.vertices, b.vertices])
    a.faces = np.vstack([a.faces, b.faces + 24])
    a.uv = np.vstack([a.uv, b.uv])
    m = TexturedModel(parts=[a])
    # both components have 12 faces: nothing is below 99 % of the largest except by area? count-based -> keep both
    r = apply_geometric_op(m, {"type": "remove_components", "min_fraction": 0.5})
    assert r["faces"] == 24 and big is not None
