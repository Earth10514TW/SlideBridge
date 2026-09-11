#!/usr/bin/env bash
set -euo pipefail
task_root="$(cd "$(dirname "$0")/.." && pwd)"
task_out="$task_root/dist/origin-bridge.exe"
mkdir -p "$(dirname "$task_out")"
command -v x86_64-w64-mingw32-g++ >/dev/null || {
  echo 'Install the Windows cross compiler first: brew install mingw-w64' >&2
  exit 1
}
x86_64-w64-mingw32-g++ -std=c++17 -Wall -Wextra -municode -static \
  "$task_root/native/origin-bridge/main.cpp" -o "$task_out" \
  -lole32 -loleaut32 -luuid -luser32 -lgdi32 -lgdiplus
echo "$task_out"
