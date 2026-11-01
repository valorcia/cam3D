#!/usr/bin/env bash
# Démarre l'API locale cam3D (phase 3) ; en attendant, expose la CLI.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "${ROOT}"
. .venv/bin/activate
exec cam3d serve --host "${CAM3D_HOST:-127.0.0.1}" --port "${CAM3D_PORT:-8765}"
