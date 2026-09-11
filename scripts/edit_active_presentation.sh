#!/usr/bin/env bash
#
# edit_active_presentation.sh: Connect to active PowerPoint window,
# edit selected chart in Windows Origin, and auto-reload presentation.
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

export PYTHONPATH="$PROJECT_ROOT:${PYTHONPATH:-}"

python3 -m slidebridge edit-active "$@"
