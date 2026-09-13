#!/usr/bin/env bash
# Build a patched emf2svg-conv binary from upstream libemf2svg.
# Output: bin/emf2svg-conv
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEST="${REPO_ROOT}/bin"

# Locate cached upstream checkout in .build/upstream-libemf2svg,
# otherwise download and patch into .build/upstream-libemf2svg
if [ -d "${REPO_ROOT}/.build/upstream-libemf2svg/src" ]; then
    SRC="${REPO_ROOT}/.build/upstream-libemf2svg"
elif [ -d "${REPO_ROOT}/artifacts/upstream/src" ]; then
    SRC="${REPO_ROOT}/artifacts/upstream"
else
    echo "==> Upstream source not found locally. Cloning kakwa/libemf2svg..."
    SRC="${REPO_ROOT}/.build/upstream-libemf2svg"
    mkdir -p "${REPO_ROOT}/.build"
    git clone --depth 1 https://github.com/kakwa/libemf2svg.git "${SRC}"
    echo "==> Applying SlideBridge fixes from patches/..."
    git -C "${SRC}" apply "${REPO_ROOT}/patches/slidebridge_pen_fix.patch"
    git -C "${SRC}" apply "${REPO_ROOT}/patches/slidebridge_patinvert_monopattern_fix.patch"
fi
BUILD="${SRC}/build"

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
