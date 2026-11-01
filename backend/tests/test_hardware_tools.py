from cam3d.engine.hardware import detect_hardware
from cam3d.engine.tools import discover_tools


def test_detect_hardware_never_raises():
    hw = detect_hardware()
    assert hw.cpu_cores >= 1
    assert hw.os in ("Linux", "Darwin", "Windows")
    d = hw.to_dict()
    assert "has_cuda" in d and isinstance(d["gpus"], list)


def test_discover_tools_shape():
    t = discover_tools()
    assert set(t.openmvs) >= {"InterfaceCOLMAP", "DensifyPointCloud", "ReconstructMesh", "TextureMesh"}
    assert t.pycolmap is not None
    d = t.to_dict()
    assert "openmvs_available" in d
