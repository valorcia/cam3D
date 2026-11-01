"""Hardware and environment detection.

Used by the installer diagnostic, the server ("capabilities" endpoint) and the
pipeline (to pick CPU/GPU paths and thread counts). Everything here must be
safe to call on Windows, macOS and Linux and must never raise.
"""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass
class GPUInfo:
    name: str
    vendor: str  # nvidia | amd | intel | apple | unknown
    cuda_available: bool = False
    vram_mb: int | None = None


@dataclass
class HardwareInfo:
    os: str
    os_version: str
    arch: str
    python_version: str
    cpu_model: str
    cpu_cores: int
    ram_total_mb: int | None
    ram_available_mb: int | None
    disk_free_mb: int | None
    gpus: list[GPUInfo] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def has_cuda(self) -> bool:
        return any(g.cuda_available for g in self.gpus)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["has_cuda"] = self.has_cuda
        return d


def _read_meminfo() -> tuple[int | None, int | None]:
    """Linux /proc/meminfo -> (total_mb, available_mb)."""
    try:
        total = avail = None
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    total = int(line.split()[1]) // 1024
                elif line.startswith("MemAvailable:"):
                    avail = int(line.split()[1]) // 1024
        return total, avail
    except OSError:
        return None, None


def _ram() -> tuple[int | None, int | None]:
    system = platform.system()
    if system == "Linux":
        return _read_meminfo()
    try:
        import psutil  # optional

        vm = psutil.virtual_memory()
        return vm.total // (1024 * 1024), vm.available // (1024 * 1024)
    except Exception:
        pass
    if system == "Darwin":
        try:
            out = subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True, timeout=5)
            return int(out.stdout.strip()) // (1024 * 1024), None
        except Exception:
            return None, None
    if system == "Windows":
        try:
            import ctypes

            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            st = MEMORYSTATUSEX()
            st.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st))
            return st.ullTotalPhys // (1024 * 1024), st.ullAvailPhys // (1024 * 1024)
        except Exception:
            return None, None
    return None, None


def _cpu_model() -> str:
    system = platform.system()
    try:
        if system == "Linux":
            with open("/proc/cpuinfo") as f:
                for line in f:
                    if line.lower().startswith("model name"):
                        return line.split(":", 1)[1].strip()
        elif system == "Darwin":
            out = subprocess.run(["sysctl", "-n", "machdep.cpu.brand_string"], capture_output=True, text=True, timeout=5)
            if out.stdout.strip():
                return out.stdout.strip()
    except Exception:
        pass
    return platform.processor() or platform.machine() or "unknown"


def _detect_gpus() -> list[GPUInfo]:
    gpus: list[GPUInfo] = []
    # NVIDIA via nvidia-smi (works on Windows and Linux when driver installed)
    if shutil.which("nvidia-smi"):
        try:
            out = subprocess.run(
                ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=10,
            )
            for line in out.stdout.strip().splitlines():
                parts = [p.strip() for p in line.split(",")]
                if parts and parts[0]:
                    vram = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else None
                    gpus.append(GPUInfo(name=parts[0], vendor="nvidia", cuda_available=True, vram_mb=vram))
        except Exception:
            pass
    system = platform.system()
    if system == "Darwin":
        try:
            out = subprocess.run(["system_profiler", "SPDisplaysDataType"], capture_output=True, text=True, timeout=15)
            for line in out.stdout.splitlines():
                if "Chipset Model:" in line:
                    name = line.split(":", 1)[1].strip()
                    vendor = "apple" if "Apple" in name else ("amd" if "AMD" in name or "Radeon" in name else "intel" if "Intel" in name else "unknown")
                    gpus.append(GPUInfo(name=name, vendor=vendor))
        except Exception:
            pass
    elif system == "Linux" and not gpus:
        try:
            out = subprocess.run(["lspci"], capture_output=True, text=True, timeout=10)
            for line in out.stdout.splitlines():
                low = line.lower()
                if "vga" in low or "3d controller" in low or "display" in low:
                    name = line.split(":", 2)[-1].strip()
                    vendor = "nvidia" if "nvidia" in low else "amd" if ("amd" in low or "radeon" in low) else "intel" if "intel" in low else "unknown"
                    gpus.append(GPUInfo(name=name, vendor=vendor))
        except Exception:
            pass
    elif system == "Windows" and not gpus:
        try:
            out = subprocess.run(
                ["powershell", "-NoProfile", "-Command", "Get-CimInstance Win32_VideoController | Select-Object -ExpandProperty Name"],
                capture_output=True, text=True, timeout=20,
            )
            for line in out.stdout.splitlines():
                name = line.strip()
                if name:
                    low = name.lower()
                    vendor = "nvidia" if "nvidia" in low else "amd" if ("amd" in low or "radeon" in low) else "intel" if "intel" in low else "unknown"
                    gpus.append(GPUInfo(name=name, vendor=vendor))
        except Exception:
            pass
    return gpus


def detect_hardware(path_for_disk: str | os.PathLike | None = None) -> HardwareInfo:
    total, avail = _ram()
    try:
        usage = shutil.disk_usage(path_for_disk or os.getcwd())
        disk_free = usage.free // (1024 * 1024)
    except Exception:
        disk_free = None
    gpus = _detect_gpus()
    notes: list[str] = []
    if not any(g.cuda_available for g in gpus):
        notes.append("Pas de GPU NVIDIA/CUDA détecté : la reconstruction dense utilisera OpenMVS sur CPU.")
    if total is not None and total < 8000:
        notes.append("Moins de 8 Go de RAM : privilégier le profil RAPIDE et des images réduites.")
    return HardwareInfo(
        os=platform.system(),
        os_version=platform.version() if platform.system() != "Darwin" else platform.mac_ver()[0],
        arch=platform.machine(),
        python_version=platform.python_version(),
        cpu_model=_cpu_model(),
        cpu_cores=os.cpu_count() or 1,
        ram_total_mb=total,
        ram_available_mb=avail,
        disk_free_mb=disk_free,
        gpus=gpus,
        notes=notes,
    )
