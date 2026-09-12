"""Portable discovery of external executables.

Why this exists
---------------
On macOS, processes started from the GUI (PowerPoint, the Services menu
item, a double-clicked ``.app``) inherit launchd's minimal environment.
That PATH is typically ``/usr/bin:/bin:/usr/sbin:/sbin`` and does **not**
include ``/usr/local/bin`` or ``/opt/homebrew/bin``, so ``shutil.which``
fails to find tools that work perfectly in a terminal -- even though
``prlctl`` or ``resvg`` are installed.

``login_path_dirs`` reconstructs the directories a login shell would have,
the same way ``/usr/libexec/path_helper`` does: read ``/etc/paths``, then
every file in ``/etc/paths.d`` in lexical order. ``find_executable`` then
searches the current PATH, those login directories, and a list of well-known
install locations, so a GUI-launched run resolves the same binaries a
terminal would.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Iterable, Sequence

#: Directories that commonly hold user-installed CLIs but are absent from
#: launchd's default PATH. Order matters: earlier entries win.
WELL_KNOWN_DIRS: tuple[str, ...] = (
    "/opt/homebrew/bin",  # Homebrew, Apple Silicon
    "/opt/homebrew/sbin",
    "/usr/local/bin",  # Homebrew, Intel; also the Parallels CLI
    "/usr/local/sbin",
    "/opt/local/bin",  # MacPorts
    "/opt/local/sbin",
    "/usr/bin",
    "/bin",
)

_PATHS_FILE = Path("/etc/paths")
_PATHS_D = Path("/etc/paths.d")


def _read_dirs(path: Path) -> list[str]:
    """Read one path_helper-style file: one directory per line, ``#`` comments."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    dirs: list[str] = []
    for line in text.splitlines():
        entry = line.strip()
        if entry and not entry.startswith("#"):
            dirs.append(entry)
    return dirs


def login_path_dirs() -> list[str]:
    """Directories a login shell would have, in path_helper order.

    Mirrors ``/usr/libexec/path_helper``: ``/etc/paths`` first, then each file
    in ``/etc/paths.d`` sorted by name. Duplicates are removed, keeping the
    first occurrence.
    """
    collected: list[str] = _read_dirs(_PATHS_FILE)
    if _PATHS_D.is_dir():
        try:
            entries = sorted(_PATHS_D.iterdir())
        except OSError:
            entries = []
        for entry in entries:
            if entry.is_file():
                collected.extend(_read_dirs(entry))

    ordered: list[str] = []
    for directory in collected:
        if directory not in ordered:
            ordered.append(directory)
    return ordered


def search_dirs(extra_dirs: Iterable[str] = ()) -> list[str]:
    """Ordered candidate directories: explicit, current PATH, login PATH, well-known."""
    ordered: list[str] = []
    sources: Sequence[str] = (
        *extra_dirs,
        *os.environ.get("PATH", "").split(os.pathsep),
        *login_path_dirs(),
        *WELL_KNOWN_DIRS,
    )
    for directory in sources:
        if directory and directory not in ordered:
            ordered.append(directory)
    return ordered


def find_executable(
    name: str,
    *,
    extra_dirs: Iterable[str] = (),
    absolute_candidates: Iterable[str] = (),
) -> str | None:
    """Locate ``name`` the way a terminal would, even from a GUI process.

    Order of resolution:

    1. an absolute ``name`` is checked directly;
    2. ``shutil.which`` (honours the current PATH, and keeps test mocks working);
    3. ``absolute_candidates`` -- known install locations for this tool;
    4. every directory from :func:`search_dirs`.

    Returns the absolute path, or ``None`` when nothing executable was found.
    """
    if os.path.isabs(name):
        return name if os.access(name, os.X_OK) else None

    found = shutil.which(name)
    if found:
        return found

    for candidate in absolute_candidates:
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate

    for directory in search_dirs(extra_dirs):
        candidate = os.path.join(directory, name)
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate

    return None


def ensure_login_path() -> str:
    """Append any missing login/well-known directories to this process's PATH.

    Mutates ``os.environ`` so subprocesses launched later inherit the same
    reachable tool set. Returns the resulting PATH.
    """
    parts = [p for p in os.environ.get("PATH", "").split(os.pathsep) if p]
    for directory in search_dirs():
        if directory not in parts:
            parts.append(directory)
    os.environ["PATH"] = os.pathsep.join(parts)
    return os.environ["PATH"]
