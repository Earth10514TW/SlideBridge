#!/usr/bin/env bash
#
# edit_active_presentation.sh: Connect to the active PowerPoint window,
# edit the selected chart in a Windows VM, and auto-reload the presentation.
#
# This script is invoked from PowerPoint (Services menu / VBA) and from
# a double-clicked .app. Both are GUI-launched, so they inherit launchd's
# minimal PATH.
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/python_env.sh
. "${SCRIPT_DIR}/python_env.sh"

# --print-python reports the interpreter the one-click flow would use, so
# `slidebridge doctor` can check the real thing instead of guessing.
if [ "${1:-}" = "--print-python" ]; then
  pick_python
  exit $?
fi

if ! PYTHON="$(pick_python)"; then
  echo "SlideBridge: no Python 3.10+ interpreter found." >&2
  echo "Looked in:" >&2
  python_candidates | sed 's/^/  /' >&2
  echo "Set SLIDEBRIDGE_PYTHON to any 3.10+ interpreter you have." >&2
  exit 1
fi

exec "${PYTHON}" -m slidebridge edit-active "$@"
