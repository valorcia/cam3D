#!/usr/bin/env bash
# Build OpenMVS 2.3.0 from the official sources on Ubuntu 24.04 (Debian-like).
# OpenMVS has no apt package; this is the reproducible build used by cam3D.
#
#   sudo scripts/build_openmvs_linux.sh [install_prefix=/opt/openmvs]
#
# Two small source patches from scripts/patches/ are applied (both fix crashes
# observed with GCC 13 / glibc 2.39; see INSTALLATION.md).
set -euo pipefail
PREFIX="${1:-/opt/openmvs}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BUILD_DIR="${ROOT}/third_party/build"
JOBS="$(nproc 2>/dev/null || echo 2)"

echo "==> Dépendances système (apt)"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq git cmake ninja-build build-essential \
  libeigen3-dev libboost-iostreams-dev libboost-program-options-dev libboost-system-dev \
  libboost-serialization-dev libboost-graph-dev libopencv-dev libcgal-dev libnanoflann-dev libjxl-dev

mkdir -p "${BUILD_DIR}" && cd "${BUILD_DIR}"
[ -d vcglib ] || git clone --depth 1 https://github.com/cdcseacave/VCG.git vcglib
if [ ! -d openMVS ]; then
  git clone --depth 1 --branch v2.3.0 https://github.com/cdcseacave/openMVS.git openMVS
  ( cd openMVS && for p in "${ROOT}"/scripts/patches/openmvs-2.3.0-*.patch; do git apply "$p"; done )
fi
mkdir -p openMVS_build && cd openMVS_build
cmake ../openMVS -GNinja -DCMAKE_BUILD_TYPE=Release -DVCG_ROOT="${BUILD_DIR}/vcglib" \
  -DOpenMVS_USE_CUDA=OFF -DOpenMVS_USE_OPENGL=OFF -DCMAKE_INSTALL_PREFIX="${PREFIX}"
ninja -j"${JOBS}"
ninja install
echo "==> OpenMVS installé dans ${PREFIX}/bin/OpenMVS"
ls "${PREFIX}/bin/OpenMVS"
