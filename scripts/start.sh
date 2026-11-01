#!/usr/bin/env bash
# Démarre l'API locale cam3D.
# Par défaut l'API écoute sur toutes les interfaces pour que le téléphone puisse
# la joindre sur le réseau local ; tout appareil autre que cet ordinateur doit
# d'abord être appairé (code à 6 chiffres + approbation explicite).
# Pour n'écouter que localement : CAM3D_HOST=127.0.0.1 ./scripts/start.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "${ROOT}"
. .venv/bin/activate
exec cam3d serve --host "${CAM3D_HOST:-0.0.0.0}" --port "${CAM3D_PORT:-8765}"
