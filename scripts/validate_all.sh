#!/usr/bin/env bash
# cam3D - full validation run (Linux/macOS developer machine).
#
#   scripts/validate_all.sh <photos_dir> [video.mp4 fake_camera.y4m]
#
# 1. backend unit + API tests, real-photo integration test (CAM3D_TEST_DATASET)
# 2. frontend type check + unit tests
# 3. starts a server on a temporary data folder and runs the browser scenarios:
#    tests/e2e.mjs (import, real reconstruction, viewer, exports, phone pairing)
#    tests/e2e_edit.mjs (measure, calibrate, crop, erase, undo, SketchUp export)
#    capture/tests/e2e_remote.mjs (cam3D Capture + local relay) if a fake-camera .y4m is given
#    tests/e2e_capture.mjs only if a video and a fake-camera .y4m are given AND
#    CAM3D_TRUST_TEST_CA=1: it adds the temporary local CA to the current user's
#    NSS store (~/.pki/nssdb) for the duration of the run, then removes it.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PHOTOS="${1:?dossier de photos requis}"
VIDEO="${2:-}"
Y4M="${3:-}"
PY="${ROOT}/.venv/bin/python"
DATA="$(mktemp -d)"
PORT="${CAM3D_PORT:-8765}"
SHOTS="${CAM3D_SHOTS:-${ROOT}/frontend/tests/screenshots}"
export NO_PROXY="*" no_proxy="*"
fail=0
step() { echo; echo "=== $*"; }

step "Tests moteur + API"
(cd "${ROOT}/backend" && "${PY}" -m pytest -q -p no:dash) || fail=1
step "Test d'intégration sur photos réelles"
(cd "${ROOT}/backend" && CAM3D_TEST_DATASET="${PHOTOS}" "${PY}" -m pytest -q -p no:dash -m slow tests/test_pipeline_integration.py) || fail=1
step "Interface : typage + tests unitaires"
(cd "${ROOT}/frontend" && npx tsc --noEmit && npx vitest run) || fail=1
step "cam3D Capture : typage + tests unitaires + build"
(cd "${ROOT}/capture" && npm ci --no-audit --no-fund >/dev/null && npx tsc --noEmit && npx vitest run && NEXT_TELEMETRY_DISABLED=1 npx next build >/dev/null) || fail=1

step "Serveur temporaire (${DATA})"
RELAY_KEY="validation-$(date +%s)-relay-key"
mkdir -p "${DATA}/relay"
(cd "${ROOT}/capture" && RELAY_STORAGE=local RELAY_ACCESS_KEY="${RELAY_KEY}" RELAY_DEV_DIR="${DATA}/relay" \
  exec npx next start -p 3100 > "${DATA}/capture.log" 2>&1) &
CAPTURE=$!
CAM3D_RELAY_ALLOW=http://localhost:3100 CAM3D_DATA_DIR="${DATA}" "${PY}" -m cam3d.cli serve --host 0.0.0.0 --port "${PORT}" > "${DATA}/server.log" 2>&1 &
SERVER=$!
CA_ADDED=0
cleanup() {
  kill "${SERVER}" 2>/dev/null || true
  pkill -P "${CAPTURE}" 2>/dev/null || true; kill "${CAPTURE}" 2>/dev/null || true
  if [ "${CA_ADDED}" = 1 ]; then certutil -D -d "sql:${HOME}/.pki/nssdb" -n "cam3D validation CA" || true; fi
}
trap cleanup EXIT
for _ in $(seq 1 30); do curl -sf "http://127.0.0.1:${PORT}/api/health" >/dev/null && break; sleep 1; done
LAN_IP="$("${PY}" -c 'from cam3d.server.network import lan_addresses; print((lan_addresses() or [""])[0])')"

step "Scénario navigateur : parcours complet"
(cd "${ROOT}/frontend" && CAM3D_URL="http://127.0.0.1:${PORT}" CAM3D_LAN_URL="${LAN_IP:+http://${LAN_IP}:${PORT}}" \
  CAM3D_PHOTOS="${PHOTOS}" CAM3D_SHOTS="${SHOTS}" node tests/e2e.mjs) || fail=1
PID="$(curl -s "http://127.0.0.1:${PORT}/api/projects" | "${PY}" -c 'import sys,json; p=[x for x in json.load(sys.stdin) if x["status"]=="done"]; print(p[0]["id"] if p else "")')"
step "Scénario navigateur : édition, étalonnage, Export SketchUp"
if [ -n "${PID}" ]; then
  (cd "${ROOT}/frontend" && CAM3D_URL="http://127.0.0.1:${PORT}" CAM3D_PROJECT="${PID}" CAM3D_SHOTS="${SHOTS}" node tests/e2e_edit.mjs) || fail=1
else
  echo "aucun projet reconstruit : scénario ignoré"; fail=1
fi
if [ -n "${VIDEO}" ] && [ -n "${Y4M}" ] && [ "${CAM3D_TRUST_TEST_CA:-0}" = 1 ] && [ -n "${LAN_IP}" ]; then
  step "Scénario navigateur : capture mobile HTTPS, repli HTTP, vidéo"
  certutil -A -d "sql:${HOME}/.pki/nssdb" -n "cam3D validation CA" -t "C,," -i "${DATA}/tls/ca.crt" && CA_ADDED=1
  (cd "${ROOT}/frontend" && CAM3D_URL="http://127.0.0.1:${PORT}" CAM3D_LAN_IP="${LAN_IP}" CAM3D_FAKE_CAMERA="${Y4M}" \
    CAM3D_VIDEO="${VIDEO}" CAM3D_PHOTOS="${PHOTOS}" CAM3D_SHOTS="${SHOTS}" node tests/e2e_capture.mjs) || fail=1
else
  echo; echo "(capture mobile non rejouée : fournir vidéo + .y4m et CAM3D_TRUST_TEST_CA=1)"
fi
if [ -n "${Y4M}" ]; then
  step "Scénario navigateur : capture à distance (scan continu, hors connexion, relais chiffré)"
  (cd "${ROOT}/capture" && CAPTURE_URL=http://localhost:3100 CAM3D_URL="http://127.0.0.1:${PORT}" RELAY_ACCESS_KEY="${RELAY_KEY}" \
    RELAY_DEV_DIR="${DATA}/relay" CAM3D_FAKE_CAMERA="${Y4M}" CAM3D_SHOTS="${SHOTS}" node tests/e2e_remote.mjs) || fail=1
fi
echo
[ "${fail}" = 0 ] && echo "VALIDATION : TOUT A RÉUSSI" || echo "VALIDATION : ÉCHECS (voir ci-dessus)"
exit "${fail}"
