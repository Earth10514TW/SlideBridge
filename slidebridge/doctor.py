"""Preflight checks for the Mac PowerPoint one-click flow.

Run ``python3 -m slidebridge doctor`` before testing the one-click flow. A GUI
launched run fails opaquely -- PowerPoint only surfaces a modal alert -- so
this command walks the same chain in the same order and reports each link:
interpreter, project root, installed handler, hypervisor, running guest,
Windows helper.

Checks are ordered by how early they break a real run. ``fail`` means the flow
cannot work; ``warn`` means it may still work but something is off.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

from .core import SlideBridgeError
from .locate import find_executable
from .vm import (
    BACKENDS,
    NoRunningGuestError,
    NoVmBackendError,
    UnsupportedBackendError,
    VmQueryError,
    detect_guest,
)

OK = "ok"
WARN = "warn"
FAIL = "fail"
INFO = "info"

_MIN_PYTHON = (3, 10)

POWERPOINT_APP = Path("/Applications/Microsoft PowerPoint.app")
HANDLER_DIR = Path.home() / "Library/Application Scripts/com.microsoft.Powerpoint"
HANDLER_SCRIPT = HANDLER_DIR / "SlideBridge.scpt"
SERVICE_NAME = "在 Origin 編輯 (SlideBridge).workflow"
SERVICE_DIR = Path.home() / "Library/Services" / SERVICE_NAME
RECORDED_ROOT = Path.home() / ".slidebridge/project-root"

#: AppleScript stores string literals as UTF-16 big-endian in the compiled
#: script, which lets us confirm the installed handler targets this checkout
#: without shelling out to osadecompile.
_SCRIPT_ENCODING = "utf-16-be"


@dataclass
class Check:
    name: str
    status: str
    detail: str
    fix: str = ""


def project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _compiled_script_mentions(path: Path, text: str) -> bool:
    try:
        return text.encode(_SCRIPT_ENCODING) in path.read_bytes()
    except OSError:
        return False


def wrapper_python() -> tuple[str | None, str]:
    """Ask the wrapper which interpreter the one-click flow will actually use.

    The wrapper owns the candidate list, so asking it beats duplicating the
    search here -- the two cannot drift apart.
    """
    script = project_root() / "scripts" / "edit_active_presentation.sh"
    if not script.is_file():
        return None, f"{script} not found"
    try:
        proc = subprocess.run(
            [str(script), "--print-python"], capture_output=True, text=True, timeout=60
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return None, str(exc)

    chosen = proc.stdout.strip()
    if proc.returncode != 0 or not chosen:
        lines = [line for line in (proc.stderr or proc.stdout).splitlines() if line.strip()]
        return None, lines[-1] if lines else "no suitable interpreter found"
    return chosen, ""


def _interpreter_version(interpreter: str) -> tuple[int, ...] | None:
    try:
        proc = subprocess.run(
            [interpreter, "-c", "import sys; print('%d.%d.%d' % sys.version_info[:3])"],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    try:
        return tuple(int(part) for part in proc.stdout.strip().split("."))
    except ValueError:
        return None


def check_python() -> Check:
    """Check the interpreter the one-click flow uses, not whichever one ran doctor."""
    chosen, error = wrapper_python()
    if chosen is None:
        return Check(
            "Python interpreter",
            FAIL,
            f"the one-click wrapper found no usable interpreter ({error})",
            "Install Python 3.10+, or point SLIDEBRIDGE_PYTHON at one you already have.",
        )

    version = _interpreter_version(chosen)
    if version and version[:2] >= _MIN_PYTHON:
        detail = f"{chosen} ({'.'.join(str(p) for p in version)})"
        if Path(sys.executable).resolve() != Path(chosen).resolve():
            detail += f"; this run used {sys.executable}"
        return Check("Python interpreter", OK, detail)

    shown = ".".join(str(p) for p in version) if version else "unusable"
    return Check(
        "Python interpreter",
        FAIL,
        f"the one-click flow would use {chosen} ({shown}), but "
        f">= {'.'.join(map(str, _MIN_PYTHON))} is required",
        "Set SLIDEBRIDGE_PYTHON to a 3.10+ interpreter you already have.",
    )


def check_project_root() -> Check:
    root = project_root()
    if (root / "scripts" / "edit_active_presentation.sh").is_file():
        return Check("Project root", OK, str(root))
    return Check(
        "Project root",
        FAIL,
        f"{root} does not look like a SlideBridge checkout",
        "Run doctor from inside the repository.",
    )


def check_recorded_root() -> Check:
    """The handler prefers ~/.slidebridge/project-root written by the installer."""
    expected = str(project_root())
    if not RECORDED_ROOT.is_file():
        return Check(
            "Recorded project root",
            WARN,
            f"{RECORDED_ROOT} not present",
            "bash scripts/install_mac_integration.sh writes it. Not required if the repo never moves.",
        )
    try:
        recorded = RECORDED_ROOT.read_text(encoding="utf-8").strip()
    except OSError as exc:
        return Check("Recorded project root", WARN, f"unreadable: {exc}")

    if recorded == expected:
        return Check("Recorded project root", OK, recorded)
    return Check(
        "Recorded project root",
        WARN,
        f"points at {recorded}, but this checkout is {expected}",
        "Re-run bash scripts/install_mac_integration.sh so the handler targets this copy.",
    )


def check_powerpoint() -> Check:
    if POWERPOINT_APP.is_dir():
        return Check("Microsoft PowerPoint", OK, str(POWERPOINT_APP))
    return Check(
        "Microsoft PowerPoint",
        FAIL,
        f"{POWERPOINT_APP} not found",
        "The one-click flow needs Mac PowerPoint installed.",
    )


def check_handler() -> Check:
    if not HANDLER_SCRIPT.is_file():
        return Check(
            "PowerPoint handler script",
            FAIL,
            f"{HANDLER_SCRIPT} not found",
            "bash scripts/install_mac_integration.sh",
        )
    if _compiled_script_mentions(HANDLER_SCRIPT, str(project_root())):
        return Check("PowerPoint handler script", OK, f"{HANDLER_SCRIPT.name} targets this checkout")
    return Check(
        "PowerPoint handler script",
        WARN,
        f"{HANDLER_SCRIPT.name} is installed but does not reference {project_root()}",
        "Re-run bash scripts/install_mac_integration.sh to repoint it.",
    )


def check_service() -> Check:
    """The PowerPoint Services menu item, not a Finder Quick Action.

    The Finder Quick Action was retired: the SwiftUI app covers batch repair.
    """
    if SERVICE_DIR.is_dir():
        return Check("PowerPoint Services menu", OK, SERVICE_NAME)
    return Check(
        "PowerPoint Services menu",
        FAIL,
        f"{SERVICE_DIR} not found",
        "bash scripts/install_mac_integration.sh, then enable it in System Settings > Keyboard > "
        "Keyboard Shortcuts > Services.",
    )


def check_backends() -> Check:
    found = []
    usable = []
    for backend in BACKENDS:
        cli = backend.find_cli()
        if cli:
            found.append(f"{backend.display_name} ({cli})")
            if backend.supports_one_click:
                usable.append(backend.display_name)

    if not found:
        return Check(
            "VM hypervisor CLI",
            FAIL,
            "none of " + ", ".join(b.cli_name for b in BACKENDS) + " were found",
            "Install Parallels Desktop (the only backend that supports one-click editing).",
        )
    if not usable:
        return Check(
            "VM hypervisor CLI",
            FAIL,
            "found " + ", ".join(found) + " -- none support one-click editing",
            "Only Parallels Desktop can run the helper without stored guest credentials.",
        )
    detail = "found " + ", ".join(found)
    if len(found) > len(usable):
        return Check("VM hypervisor CLI", OK, detail + f"; one-click capable: {', '.join(usable)}")
    return Check("VM hypervisor CLI", OK, detail)


def check_guest() -> Check:
    """Report whether a Windows guest is reachable.

    Nothing runs inside Windows for this check: it only asks the hypervisor on
    the Mac which VMs are currently running. The three failure modes need very
    different advice, so they are reported separately.
    """
    try:
        guest = detect_guest()
    except NoVmBackendError as exc:
        return Check("Running Windows guest", FAIL, str(exc), "Install Parallels Desktop.")
    except UnsupportedBackendError as exc:
        return Check("Running Windows guest", FAIL, str(exc), "Use Parallels Desktop for one-click editing.")
    except NoRunningGuestError as exc:
        return Check(
            "Running Windows guest",
            FAIL,
            str(exc),
            "Boot the Windows VM in Parallels Desktop, then re-run doctor.",
        )
    except VmQueryError as exc:
        return Check(
            "Running Windows guest",
            FAIL,
            f"Parallels is installed but could not be queried: {exc}",
            "Open Parallels Desktop once so its service initialises, then re-run doctor. "
            "If you are inside a restricted shell that blocks /bin/ps, run doctor from Terminal instead.",
        )
    except SlideBridgeError as exc:
        return Check("Running Windows guest", FAIL, str(exc))
    return Check("Running Windows guest", OK, f"{guest.name} via {guest.backend}")


def check_helper() -> Check:
    root = project_root()
    helper = root / "dist" / "origin-bridge.exe"
    if not helper.is_file():
        legacy_helper = root / "artifacts" / "bin" / "origin-bridge.exe"
        if legacy_helper.is_file():
            helper = legacy_helper
        else:
            return Check(
                "Windows helper binary",
                FAIL,
                f"{helper} not found",
                "bash scripts/build_origin_bridge.sh",
            )
    size_mb = helper.stat().st_size / (1024 * 1024)
    return Check("Windows helper binary", OK, f"{helper.name} ({size_mb:.1f} MB)")


def check_automation_permission() -> Check:
    """macOS Automation consent cannot be read without Full Disk Access."""
    return Check(
        "Automation permission",
        INFO,
        "cannot be checked from here; macOS grants it on first use",
        "The first PowerPoint-triggered run prompts 'PowerPoint wants to control...' -- allow it in "
        "System Settings > Privacy & Security > Automation.",
    )


def run_checks() -> list[Check]:
    return [
        check_python(),
        check_project_root(),
        check_recorded_root(),
        check_powerpoint(),
        check_handler(),
        check_service(),
        check_backends(),
        check_guest(),
        check_helper(),
        check_automation_permission(),
    ]


_SYMBOL = {OK: "[ ok ]", WARN: "[warn]", FAIL: "[FAIL]", INFO: "[info]"}


def format_report(checks: list[Check]) -> str:
    width = max(len(check.name) for check in checks) + 2
    lines = ["SlideBridge preflight for the Mac PowerPoint one-click flow", ""]
    for check in checks:
        lines.append(f"{_SYMBOL.get(check.status, '[????]')} {check.name.ljust(width)}{check.detail}")

    problems = [c for c in checks if c.status in {FAIL, WARN}]
    if problems:
        lines.append("")
        lines.append("Next steps:")
        for check in problems:
            if check.fix:
                lines.append(f"  - {check.name}: {check.fix}")
    else:
        lines.append("")
        lines.append("All checks passed. You can run the one-click flow from PowerPoint.")

    return "\n".join(lines)


def doctor(as_json: bool = False) -> dict:
    checks = run_checks()
    report = {
        "checks": [asdict(check) for check in checks],
        "failures": sum(1 for c in checks if c.status == FAIL),
        "warnings": sum(1 for c in checks if c.status == WARN),
        "ready": all(c.status != FAIL for c in checks),
    }
    if as_json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(format_report(checks))
    return report
