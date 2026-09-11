"""Parallels Desktop VM bridge and orchestration for SlideBridge."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from .core import SlideBridgeError


_DEFAULT_CLSID = "{64CC80B2-4FA1-4F7B-9D6F-1BFACF5715DC}"


def detect_running_vm(prlctl_bin: str = "prlctl") -> str:
    """Find a running Windows Parallels VM.

    Returns the VM name (e.g. 'Windows 11 Lite').
    Raises SlideBridgeError if no running VM is found.
    """
    cmd = shutil.which(prlctl_bin)
    if not cmd:
        raise SlideBridgeError(
            "Parallels CLI 'prlctl' not found. Ensure Parallels Desktop is installed."
        )

    try:
        proc = subprocess.run(
            [cmd, "list", "--all"],
            capture_output=True,
            text=True,
            check=True,
        )
    except (subprocess.SubprocessError, OSError) as exc:
        raise SlideBridgeError(f"Failed to query Parallels VMs via prlctl: {exc}") from exc

    lines = proc.stdout.strip().splitlines()
    if len(lines) <= 1:
        raise SlideBridgeError("No Parallels VMs found.")

    running_vms: list[tuple[str, str]] = []
    for line in lines[1:]:
        parts = line.split(maxsplit=3)
        if len(parts) >= 4:
            _uuid, status, _ip, name = parts
            st = status.lower()
            if st in {"running", "paused"}:
                running_vms.append((name.strip(), st))

    if not running_vms:
        raise SlideBridgeError(
            "No running Parallels VM found. Please start your Windows VM first."
        )

    # Prefer a VM with 'windows' in the name
    chosen_vm, chosen_st = running_vms[0]
    for vm, st in running_vms:
        if "windows" in vm.lower():
            chosen_vm, chosen_st = vm, st
            break

    if chosen_st == "paused":
        try:
            subprocess.run([cmd, "resume", chosen_vm], capture_output=True, check=True)
        except subprocess.SubprocessError:
            pass

    return chosen_vm


def mac_to_vm_path(mac_path: os.PathLike[str] | str) -> str:
    """Convert a macOS POSIX path to a Parallels Windows UNC shared path.

    E.g. /Users/earth/Documents/foo.bin -> \\\\Mac\\Home\\Documents\\foo.bin
    """
    full_path = Path(mac_path).resolve()
    home = Path.home().resolve()

    try:
        rel = full_path.relative_to(home)
        parts = ["\\\\Mac", "Home"] + list(rel.parts)
        return "\\".join(parts)
    except ValueError:
        parts = ["\\\\Mac", "Host"] + [p for p in full_path.parts if p and p != "/"]
        return "\\".join(parts)


def activate_vm_window() -> None:
    """Bring the Parallels Desktop application to the macOS foreground."""
    try:
        subprocess.run(
            ["osascript", "-e", 'tell application "Parallels Desktop" to activate'],
            capture_output=True,
            check=False,
        )
    except OSError:
        pass


def launch_vm_helper(
    vm_name: str,
    session_dir: os.PathLike[str] | str,
    helper_exe: os.PathLike[str] | str | None = None,
    clsid: str = _DEFAULT_CLSID,
    prlctl_bin: str = "prlctl",
) -> int:
    """Launch origin-bridge.exe inside the specified Parallels VM.

    Blocks until the user finishes and closes the helper window.
    Returns the exit code of origin-bridge.exe.
    """
    session_path = Path(session_dir).resolve()
    editable_mac = session_path / "editable.bin"
    edited_mac = session_path / "edited.bin"

    if not editable_mac.is_file():
        raise SlideBridgeError(f"editable.bin not found in session: {session_path}")

    if helper_exe is None:
        project_root = Path(__file__).resolve().parent.parent
        default_exe = project_root / "artifacts" / "bin" / "origin-bridge.exe"
        if default_exe.is_file():
            helper_exe = default_exe
        else:
            raise SlideBridgeError(
                f"Windows Helper executable not found: {default_exe}. "
                "Run bash scripts/build_origin_bridge.sh to compile it."
            )
    else:
        helper_exe = Path(helper_exe).resolve()
        if not helper_exe.is_file():
            raise SlideBridgeError(f"Specified Windows Helper not found: {helper_exe}")

    helper_win = mac_to_vm_path(helper_exe)
    editable_win = mac_to_vm_path(editable_mac)
    edited_win = mac_to_vm_path(edited_mac)

    activate_vm_window()

    cmd = [
        prlctl_bin,
        "exec",
        vm_name,
        "--current-user",
        helper_win,
        "edit",
        editable_win,
        edited_win,
        "--clsid",
        clsid,
    ]

    try:
        result = subprocess.run(cmd)
        return result.returncode
    except (subprocess.SubprocessError, OSError) as exc:
        raise SlideBridgeError(f"Failed to execute Windows Helper via prlctl: {exc}") from exc
