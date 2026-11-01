#!/usr/bin/env bash
# cam3D - installation développeur (Linux / macOS).
#   ./scripts/install.sh
# 1. environnement virtuel Python + dépendances (pycolmap, Open3D, trimesh, FastAPI…)
# 2. vérification des outils externes (OpenMVS, FFmpeg, Blender optionnel)
# 3. diagnostic matériel (cam3d doctor)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "${ROOT}"
PY="${PYTHON:-python3}"
"${PY}" - <<'PYCHK'
import sys
assert sys.version_info >= (3, 10), f"Python >= 3.10 requis (trouvé {sys.version})"
PYCHK
[ -d .venv ] || "${PY}" -m venv .venv
. .venv/bin/activate
pip install --upgrade pip -q
pip install -q -e "backend[dev]"
echo
echo "==> Outils externes"
OS="$(uname -s)"
if ! command -v DensifyPointCloud >/dev/null 2>&1 && [ ! -x /opt/openmvs/bin/OpenMVS/DensifyPointCloud ] && [ -z "${CAM3D_OPENMVS_DIR:-}" ]; then
  case "${OS}" in
    Darwin) echo "OpenMVS absent : brew install openmvs   (puis export CAM3D_OPENMVS_DIR=\$(brew --prefix)/bin si besoin)";;
    *)      echo "OpenMVS absent : sudo scripts/build_openmvs_linux.sh";;
  esac
fi
command -v ffmpeg >/dev/null 2>&1 || echo "FFmpeg absent (nécessaire pour l'import vidéo) : apt install ffmpeg / brew install ffmpeg"
echo
cam3d doctor || true
echo
echo "Installation terminée. Démarrage : ./scripts/start.sh"
