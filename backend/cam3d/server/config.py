"""Server settings (environment variables override defaults)."""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path


def default_data_dir() -> Path:
    env = os.environ.get("CAM3D_DATA_DIR")
    if env:
        return Path(env).expanduser()
    return Path.home() / "cam3D"


@dataclass
class Settings:
    data_dir: Path = field(default_factory=default_data_dir)
    max_photo_mb: int = int(os.environ.get("CAM3D_MAX_PHOTO_MB", "60"))
    max_video_mb: int = int(os.environ.get("CAM3D_MAX_VIDEO_MB", "2000"))
    max_photos_per_project: int = int(os.environ.get("CAM3D_MAX_PHOTOS", "2000"))
    # Requests from these client addresses are the desktop user (full rights).
    # Everything else (phones on the LAN) must pair first and present a token.
    trusted_hosts: frozenset[str] = frozenset({"127.0.0.1", "::1", "localhost"})
    # Host header names accepted for desktop rights (anti DNS-rebinding). Tests add "testserver".
    local_host_names: frozenset[str] = frozenset({"127.0.0.1", "localhost", "::1", "[::1]"})
    pairing_ttl_s: int = 600            # a pairing code is valid 10 minutes
    device_token_ttl_s: int = 7 * 86400  # a paired phone stays authorised 7 days
    worker_python: str = sys.executable
    worker_cmd: list[str] | None = None  # override (tests) — default: [python, -m, cam3d.worker]
    cancel_grace_s: float = 15.0         # graceful cancel delay before killing the worker tree
    https_port: int = int(os.environ.get("CAM3D_HTTPS_PORT", "8443"))

    @property
    def projects_dir(self) -> Path:
        return self.data_dir / "projects"

    @property
    def tls_dir(self) -> Path:
        return self.data_dir / "tls"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "cam3d.sqlite3"

    def ensure_dirs(self) -> None:
        self.projects_dir.mkdir(parents=True, exist_ok=True)
