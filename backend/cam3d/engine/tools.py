"""Discovery of external tools: COLMAP, OpenMVS, Blender, FFmpeg.

Search order for each tool:
1. explicit environment variable (``CAM3D_OPENMVS_DIR``, ``CAM3D_COLMAP``,
   ``CAM3D_BLENDER``, ``CAM3D_FFMPEG``),
2. the project's ``third_party/`` folder (installer target),
3. well-known install locations per OS,
4. the PATH.
"""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

OPENMVS_BINARIES = ["InterfaceCOLMAP", "DensifyPointCloud", "ReconstructMesh", "RefineMesh", "TextureMesh"]

_EXE = ".exe" if platform.system() == "Windows" else ""


def project_root() -> Path:
    """Repository root (``.../cam3D``) when running from source."""
    return Path(__file__).resolve().parents[3]


def _candidates_openmvs_dirs() -> list[Path]:
    env = os.environ.get("CAM3D_OPENMVS_DIR")
    c: list[Path] = []
    if env:
        c.append(Path(env))
    root = project_root()
    c += [root / "third_party" / "openmvs" / "bin", root / "third_party" / "openmvs" / "bin" / "OpenMVS"]
    system = platform.system()
    if system == "Linux":
        c += [Path("/opt/openmvs/bin/OpenMVS"), Path("/usr/local/bin/OpenMVS"), Path("/usr/local/bin"), Path("/usr/bin/OpenMVS")]
    elif system == "Darwin":
        c += [Path("/opt/homebrew/bin"), Path("/usr/local/bin"), Path("/opt/homebrew/opt/openmvs/bin/OpenMVS")]
    elif system == "Windows":
        for base in [os.environ.get("ProgramFiles", r"C:\Program Files"), os.environ.get("LOCALAPPDATA", "")]:
            if base:
                c += [Path(base) / "OpenMVS" / "bin", Path(base) / "OpenMVS"]
    return c


@dataclass
class ToolInfo:
    name: str
    path: str | None
    version: str | None = None
    available: bool = False
    note: str | None = None


@dataclass
class ToolRegistry:
    colmap: ToolInfo
    openmvs: dict[str, ToolInfo] = field(default_factory=dict)
    blender: ToolInfo | None = None
    ffmpeg: ToolInfo | None = None
    pycolmap: ToolInfo | None = None

    @property
    def openmvs_available(self) -> bool:
        return all(self.openmvs.get(b) and self.openmvs[b].available for b in OPENMVS_BINARIES if b != "RefineMesh")

    @property
    def openmvs_dir(self) -> Path | None:
        t = self.openmvs.get("DensifyPointCloud")
        return Path(t.path).parent if t and t.path else None

    def openmvs_bin(self, name: str) -> str:
        t = self.openmvs.get(name)
        if not t or not t.available or not t.path:
            raise FileNotFoundError(f"OpenMVS binary not found: {name}")
        return t.path

    def to_dict(self) -> dict:
        return {
            "colmap": self.colmap.__dict__,
            "pycolmap": self.pycolmap.__dict__ if self.pycolmap else None,
            "openmvs": {k: v.__dict__ for k, v in self.openmvs.items()},
            "openmvs_available": self.openmvs_available,
            "blender": self.blender.__dict__ if self.blender else None,
            "ffmpeg": self.ffmpeg.__dict__ if self.ffmpeg else None,
        }


def _version_of(cmd: list[str], timeout: float = 15) -> str | None:
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        text = (out.stdout or out.stderr or "").strip().splitlines()
        return text[0][:120] if text else None
    except Exception:
        return None


def _find_exe(env_var: str, names: list[str], extra_dirs: list[Path]) -> str | None:
    env = os.environ.get(env_var)
    if env and Path(env).exists():
        return str(Path(env))
    for d in extra_dirs:
        for n in names:
            p = d / (n + _EXE)
            if p.exists():
                return str(p)
    for n in names:
        p = shutil.which(n)
        if p:
            return p
    return None


def discover_tools() -> ToolRegistry:
    root = project_root()
    system = platform.system()

    # COLMAP binary (optional: pycolmap covers SfM; the binary is useful for
    # CUDA dense stereo on NVIDIA machines and for the GUI).
    colmap_dirs = [root / "third_party" / "colmap", root / "third_party" / "colmap" / "bin"]
    if system == "Windows":
        colmap_dirs += [Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "COLMAP"]
    elif system == "Darwin":
        colmap_dirs += [Path("/opt/homebrew/bin"), Path("/usr/local/bin"), Path("/Applications/COLMAP.app/Contents/MacOS")]
    colmap_path = _find_exe("CAM3D_COLMAP", ["colmap", "COLMAP"], colmap_dirs)
    colmap = ToolInfo("colmap", colmap_path, _version_of([colmap_path, "-h"]) if colmap_path else None, bool(colmap_path))

    try:
        import pycolmap  # noqa

        pyc = ToolInfo("pycolmap", pycolmap.__file__, pycolmap.__version__, True,
                       note="CUDA" if getattr(pycolmap, "has_cuda", False) else "CPU only")
    except Exception as e:  # pragma: no cover
        pyc = ToolInfo("pycolmap", None, None, False, note=str(e))

    openmvs: dict[str, ToolInfo] = {}
    dirs = _candidates_openmvs_dirs()
    for b in OPENMVS_BINARIES:
        p = _find_exe(f"CAM3D_OPENMVS_{b.upper()}", [b], dirs)
        openmvs[b] = ToolInfo(b, p, None, bool(p))
    if openmvs["DensifyPointCloud"].available:
        openmvs["DensifyPointCloud"].version = _version_of([openmvs["DensifyPointCloud"].path, "--help"])

    blender_dirs = [root / "third_party" / "blender"]
    if system == "Darwin":
        blender_dirs += [Path("/Applications/Blender.app/Contents/MacOS")]
    elif system == "Windows":
        pf = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Blender Foundation"
        if pf.exists():
            blender_dirs += sorted(pf.glob("Blender*"), reverse=True)
    blender_path = _find_exe("CAM3D_BLENDER", ["blender", "Blender"], blender_dirs)
    blender = ToolInfo("blender", blender_path, _version_of([blender_path, "--version"]) if blender_path else None, bool(blender_path))

    ffmpeg_path = _find_exe("CAM3D_FFMPEG", ["ffmpeg"], [root / "third_party" / "ffmpeg", root / "third_party" / "ffmpeg" / "bin"])
    ffmpeg = ToolInfo("ffmpeg", ffmpeg_path, _version_of([ffmpeg_path, "-version"]) if ffmpeg_path else None, bool(ffmpeg_path))

    return ToolRegistry(colmap=colmap, openmvs=openmvs, blender=blender, ffmpeg=ffmpeg, pycolmap=pyc)
