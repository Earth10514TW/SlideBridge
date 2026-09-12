#!/usr/bin/env bash
# Shared environment setup for SlideBridge shell entrypoints.
#
# Rebuilds a usable PATH and discovers an appropriate Python 3.10+ interpreter
# across GUI callers (Finder, Automator, PowerPoint AppleScript) and CLI shells.

# 1. Rebuild a usable PATH. GUI callers lose the login PATH, which is where
#    prlctl and Homebrew/MacPorts python3 live.
for dir in /opt/homebrew/bin /opt/homebrew/sbin /usr/local/bin /usr/local/sbin /opt/local/bin /opt/local/sbin; do
  case ":${PATH:-}:" in
    *":${dir}:"*) ;;
    *) PATH="${dir}:${PATH:-}" ;;
  esac
done
export PATH

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# 2. Pick a Python that satisfies the project's requires-python (>=3.10).
#    In a GUI context `python3` resolves to /usr/bin/python3, which is 3.9 on
#    macOS, so we probe candidates newest-first.
python_candidates() {
  local candidate
  [ -n "${SLIDEBRIDGE_PYTHON:-}" ] && printf '%s\n' "${SLIDEBRIDGE_PYTHON}"
  printf '%s\n' /opt/homebrew/bin/python3 /usr/local/bin/python3
  for candidate in $(ls -d /Library/Frameworks/Python.framework/Versions/*/bin/python3 2>/dev/null \
    | grep -v '/Current/' | sort -Vr); do
    printf '%s\n' "${candidate}"
  done
  printf '%s\n' /opt/local/bin/python3
  command -v python3 2>/dev/null || true
}

pick_python() {
  local candidate
  local cache_file="${HOME}/.slidebridge/python-path"

  # Fast-path 1: Explicit SLIDEBRIDGE_PYTHON override
  if [ -n "${SLIDEBRIDGE_PYTHON:-}" ] && [ -x "${SLIDEBRIDGE_PYTHON}" ]; then
    printf '%s\n' "${SLIDEBRIDGE_PYTHON}"
    return 0
  fi

  # Fast-path 2: Cached python path (avoids spawning probing subshells)
  if [ -f "${cache_file}" ]; then
    candidate="$(cat "${cache_file}" 2>/dev/null || true)"
    if [ -n "${candidate}" ] && [ -x "${candidate}" ]; then
      printf '%s\n' "${candidate}"
      return 0
    fi
  fi

  while IFS= read -r candidate; do
    [ -n "${candidate}" ] || continue
    [ -x "${candidate}" ] || continue
    if "${candidate}" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
      mkdir -p "${HOME}/.slidebridge" 2>/dev/null || true
      printf '%s\n' "${candidate}" > "${cache_file}" 2>/dev/null || true
      printf '%s\n' "${candidate}"
      return 0
    fi
  done < <(python_candidates)
  return 1
}

export PROJECT_ROOT
export PYTHONPATH="${PROJECT_ROOT}${PYTHONPATH:+:${PYTHONPATH}}"
