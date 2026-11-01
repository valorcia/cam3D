"""Real reconstruction on a real photo set. Enabled with CAM3D_TEST_DATASET=<dir>.

Takes a few minutes on CPU with the FAST profile (11 images of 2832x2128).
"""
import json
import zipfile

import pytest

from cam3d.engine.pipeline import ReconstructionPipeline
from cam3d.engine.tools import discover_tools


@pytest.mark.slow
def test_full_pipeline_fast_profile(dataset_dir, tmp_path):
    tools = discover_tools()
    if not tools.openmvs_available:
        pytest.skip("OpenMVS non installé")
    events = []
    pipe = ReconstructionPipeline(tools=tools, callback=events.append)
    res = pipe.run(dataset_dir, tmp_path / "project", profile="fast", export_formats=("obj", "dae", "glb"))
    assert res.success, res.error
    assert res.num_faces and res.num_faces > 10_000
    assert res.textures and all(t.endswith((".jpg", ".png")) for t in res.textures)
    stages = res.stages
    for s in ("prepare", "sfm", "dense", "mesh", "texture", "cleanup", "export"):
        assert stages[s]["status"] == "finished", (s, stages[s])
    assert stages["sfm"]["num_registered"] >= 0.8 * stages["sfm"]["num_images_total"]
    by = {e["format"]: e for e in res.exports}
    with zipfile.ZipFile(by["dae"]["path"]) as z:
        names = z.namelist()
        assert any(n.endswith(".dae") for n in names) and any(n.startswith("textures/") for n in names)
    assert (tmp_path / "project" / "pipeline_result.json").exists()
    assert (tmp_path / "project" / "previews" / "model.glb").exists()
    # progress events were real (measured), never invented
    sfm_progress = [e for e in events if e.stage.value == "sfm" and e.status == "progress"]
    assert sfm_progress and all(0 <= e.progress <= 1 for e in sfm_progress)
