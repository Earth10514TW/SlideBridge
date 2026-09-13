#!/usr/bin/env bash
set -euo pipefail
task_root="$(cd "$(dirname "$0")/.." && pwd)"
task_out="$task_root/dist/origin-bridge.exe"
task_src="$task_root/native/origin-bridge"
build_dir="$task_root/.build"
mkdir -p "$(dirname "$task_out")" "$build_dir"
command -v x86_64-w64-mingw32-g++ >/dev/null || {
  echo 'Install the Windows cross compiler first: brew install mingw-w64' >&2
  exit 1
}
command -v x86_64-w64-mingw32-windres >/dev/null || {
  echo 'Install the Windows cross compiler first: brew install mingw-w64' >&2
  exit 1
}

# resources.rc carries two things main.cpp cannot express on its own:
#   * the manifest, which is what makes Windows apply common-controls v6
#     theming (without it every BUTTON renders in the classic Win2000 style)
#     and honour the per-monitor DPI declaration
#   * the multi-size app icon, also used by Explorer and the taskbar
x86_64-w64-mingw32-windres --include-dir "$task_src" \
  "$task_src/resources.rc" -O coff -o "$build_dir/origin-bridge-resources.o"

# -ffunction-sections/-fdata-sections + --gc-sections drop the libstdc++
# pieces nothing references. Together with main.cpp avoiding <iostream> this
# takes the binary from 1.09 MB to ~0.32 MB; the guest runs it under x64
# emulation on Apple Silicon, so there is less to map and translate on every
# launch.
x86_64-w64-mingw32-g++ -O2 -s -std=c++17 -Wall -Wextra -municode -static \
  -ffunction-sections -fdata-sections -Wl,--gc-sections \
  "$task_src/main.cpp" "$build_dir/origin-bridge-resources.o" -o "$task_out" \
  -lole32 -loleaut32 -luuid -luser32 -lgdi32 -lgdiplus
echo "$task_out"
