#!/usr/bin/env bash
#
# fix_presentation.sh: CLI and Finder entrypoint to repair EMF images in a PowerPoint file.
#
set -euo pipefail

if [ "$#" -lt 1 ]; then
  echo "Usage: $(basename "$0") <presentation.pptx> [additional options]"
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/python_env.sh
. "${SCRIPT_DIR}/python_env.sh"

if ! PYTHON="$(pick_python)"; then
  echo "SlideBridge: no Python 3.10+ interpreter found." >&2
  echo "Set SLIDEBRIDGE_PYTHON to any 3.10+ interpreter you have." >&2
  exit 1
fi

exec "${PYTHON}" -m slidebridge fix "$@"
