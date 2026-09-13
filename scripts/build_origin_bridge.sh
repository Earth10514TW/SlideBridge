#!/usr/bin/env bash
set -euo pipefail
task_root="$(cd "$(dirname "$0")/.." && pwd)"
task_out="$task_root/dist/origin-bridge.exe"
mkdir -p "$(dirname "$task_out")"
command -v x86_64-w64-mingw32-g++ >/dev/null || {
  echo 'Install the Windows cross compiler first: brew install mingw-w64' >&2
  exit 1
}
# -ffunction-sections/-fdata-sections + --gc-sections drop the libstdc++
# pieces nothing references. Together with main.cpp avoiding <iostream> this
# takes the binary from 1.09 MB to ~0.30 MB; the guest runs it under x64
# emulation on Apple Silicon, so there is less to map and translate on every
# launch.
x86_64-w64-mingw32-g++ -O2 -s -std=c++17 -Wall -Wextra -municode -static \
  -ffunction-sections -fdata-sections -Wl,--gc-sections \
  "$task_root/native/origin-bridge/main.cpp" -o "$task_out" \
  -lole32 -loleaut32 -luuid -luser32 -lgdi32 -lgdiplus
echo "$task_out"
