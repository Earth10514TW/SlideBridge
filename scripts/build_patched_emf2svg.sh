#!/usr/bin/env bash
# Build a patched emf2svg-conv binary from the local upstream checkout.
# The patch is already applied in artifacts/upstream; this script just builds.
# Output: artifacts/bin/emf2svg-conv
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="${REPO_ROOT}/artifacts/upstream"
BUILD="${SRC}/build"
DEST="${REPO_ROOT}/artifacts/bin"

if [ ! -d "${SRC}/src" ]; then
    echo "ERROR: upstream source not found at ${SRC}" >&2
    exit 1
fi

# On macOS, argp-standalone is a keg-only Homebrew formula.
# Help CMake's Findargp.cmake locate the argp headers and library.
CMAKE_EXTRA_ARGS=()
if [ "$(uname -s)" = "Darwin" ]; then
    BREW_PREFIX="$(brew --prefix 2>/dev/null || echo /opt/homebrew)"
    ARGP_PREFIX="${BREW_PREFIX}/opt/argp-standalone"
    if [ -d "${ARGP_PREFIX}" ]; then
        CMAKE_EXTRA_ARGS+=("-DARGP_ROOT_DIR=${ARGP_PREFIX}")
    fi
fi

echo "==> Configuring patched libemf2svg …"
rm -rf "${BUILD}"
mkdir -p "${BUILD}"
cmake -S "${SRC}" -B "${BUILD}" \
    -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_POLICY_VERSION_MINIMUM=3.5 \
    "${CMAKE_EXTRA_ARGS[@]}" \
    2>&1

echo "==> Building emf2svg-conv …"
cmake --build "${BUILD}" --target emf2svg-conv -j "$(sysctl -n hw.ncpu 2>/dev/null || echo 4)" 2>&1

mkdir -p "${DEST}"
cp "${BUILD}/emf2svg-conv" "${DEST}/emf2svg-conv"
chmod +x "${DEST}/emf2svg-conv"

echo "==> Patched binary installed: ${DEST}/emf2svg-conv"
"${DEST}/emf2svg-conv" --help 2>&1 | head -3 || true
