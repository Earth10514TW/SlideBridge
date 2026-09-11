#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -lt 1 ]; then
  echo "Usage: $(basename "$0") <presentation.pptx> [additional options]"
  exit 1
fi

project_root="$(cd "$(dirname "$0")/.." && pwd)"
export PYTHONPATH="$project_root${PYTHONPATH:+:$PYTHONPATH}"
exec python3 -m slidebridge edit "$@"
