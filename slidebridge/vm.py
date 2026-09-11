"""VM bridge and orchestration for SlideBridge.

SlideBridge drives a Windows guest from macOS. Guest execution is abstracted
behind small backends so the orchestration is not welded to one hypervisor.

Only the Parallels backend is fully implemented, and that is not an accident.
The seamless one-click flow needs two capabilities together:

* running a program in the guest as the logged-in macOS user **without stored
  guest credentials** (``prlctl exec --current-user``), and
* a predictable shared-folder mapping so a macOS path can be translated to a
  guest path (``\\\\Mac\\Home\\...``).

Parallels provides both. VMware Fusion and VirtualBox can run guest programs
but require guest credentials; UTM uses its own sharing model. Those backends
are still detected and listed so the failure is explicit and actionable
instead of a misleading "not installed" message.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from .core import SlideBridgeError
from .locate import find_executable

_DEFAULT_CLSID = "{64CC80B2-4FA1-4F7B-9D6F-1BFACF5715DC}"


class NoVmBackendError(SlideBridgeError):
    """No supported hypervisor CLI was found on this host."""


class VmQueryError(SlideBridgeError):
    """A hypervisor CLI exists but could not be queried."""


class UnsupportedBackendError(SlideBridgeError):
    """A running guest was found, but its backend cannot run the helper."""


class NoRunningGuestError(SlideBridgeError):
    """A hypervisor was reachable, but no Windows guest is running."""


@dataclass(frozen=True)
class Guest:
    """A running (or paused) VM discovered on this host."""

    backend: str
    name: str
    status: str = "running"


class VmBackend:
    """Base class for a hypervisor we can talk to from macOS."""

    name: str = ""
    display_name: str = ""
    cli_name: str = ""
    cli_candidates: tuple[str, ...] = ()
    #: True when the backend can run a guest program with no stored credentials
    #: and can translate macOS paths to guest paths.
    supports_one_click: bool = False
    #: Human-readable reason the backend cannot be used for one-click editing.
    limitation: str = ""

    def find_cli(self) -> str | None:
        """Locate this backend's CLI even when launched from a GUI process."""
        return find_executable(self.cli_name, absolute_candidates=self.cli_candidates)

    def is_installed(self) -> bool:
        return self.find_cli() is not None

    def list_guests(self, cli: str) -> list[Guest]:
        """Running or paused guests. Overridden by each backend."""
        raise NotImplementedError

    def resume(self, cli: str, guest: Guest) -> None:
        """Bring a paused guest back to running. Optional."""

    def activate(self) -> None:
        """Bring the hypervisor's UI to the macOS foreground. Optional."""

    def run_program(self, cli: str, guest: Guest, argv: Sequence[str]) -> int:
        """Run ``argv`` inside ``guest``. Overridden by usable backends."""
        raise SlideBridgeError(
            f"{self.display_name or self.name} is detected, but SlideBridge cannot edit "
            f"charts through it yet. {self.limitation}".strip()
        )


class ParallelsBackend(VmBackend):
    """Parallels Desktop -- the fully supported backend."""

    name = "parallels"
    display_name = "Parallels Desktop"
    cli_name = "prlctl"
    cli_candidates = (
        "/usr/local/bin/prlctl",
        "/opt/homebrew/bin/prlctl",
        "/Applications/Parallels Desktop.app/Contents/MacOS/prlctl",
    )
    supports_one_click = True

    def list_guests(self, cli: str) -> list[Guest]:
        proc = self._run([cli, "list", "--all"], "query Parallels VMs")
        guests: list[Guest] = []
        for line in proc.stdout.strip().splitlines()[1:]:
            parts = line.split(maxsplit=3)
            if len(parts) >= 4:
                _uuid, status, _ip, vm_name = parts
                state = status.lower()
                if state in {"running", "paused"}:
                    guests.append(Guest(self.name, vm_name.strip(), state))
        return guests

    def resume(self, cli: str, guest: Guest) -> None:
        try:
            subprocess.run([cli, "resume", guest.name], capture_output=True, check=True)
        except (subprocess.SubprocessError, OSError):
            pass

    def activate(self) -> None:
        _activate_app("Parallels Desktop")

    def run_program(self, cli: str, guest: Guest, argv: Sequence[str]) -> int:
        cmd = [cli, "exec", guest.name, "--current-user", *argv]
        try:
            return subprocess.run(cmd).returncode
        except (subprocess.SubprocessError, OSError) as exc:
            raise SlideBridgeError(
                f"Failed to execute Windows Helper via prlctl: {exc}"
            ) from exc

    @staticmethod
    def _run(cmd: list[str], what: str) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(cmd, capture_output=True, text=True, check=True)
        except (subprocess.SubprocessError, OSError) as exc:
            raise VmQueryError(f"Failed to {what} via prlctl: {exc}") from exc


class UtmBackend(VmBackend):
    """UTM (QEMU on macOS). Detected only; sharing model differs."""

    name = "utm"
    display_name = "UTM"
    cli_name = "utmctl"
    cli_candidates = (
        "/Applications/UTM.app/Contents/MacOS/utmctl",
        "/usr/local/bin/utmctl",
        "/opt/homebrew/bin/utmctl",
    )
    limitation = (
        "UTM does not expose Parallels' \\\\Mac\\Home shared-folder mapping, so a macOS "
        "path cannot be translated to a guest path automatically."
    )

    def list_guests(self, cli: str) -> list[Guest]:
        try:
            proc = subprocess.run(
                [cli, "list"], capture_output=True, text=True, check=True
            )
        except (subprocess.SubprocessError, OSError):
            return []
        guests: list[Guest] = []
        for line in proc.stdout.strip().splitlines()[1:]:
            parts = line.split()
            if len(parts) >= 3:
                _uuid, status, *rest = parts
                state = status.lower()
                if state in {"started", "running", "paused"}:
                    guests.append(Guest(self.name, " ".join(rest), "running"))
        return guests

    def activate(self) -> None:
        _activate_app("UTM")


class VmwareFusionBackend(VmBackend):
    """VMware Fusion. Detected only; guest execution needs credentials."""

    name = "vmware"
    display_name = "VMware Fusion"
    cli_name = "vmrun"
    cli_candidates = (
        "/Applications/VMware Fusion.app/Contents/Library/vmrun",
        "/usr/local/bin/vmrun",
        "/opt/homebrew/bin/vmrun",
    )
    limitation = (
        "vmrun requires guest credentials (-gu/-gp) to run a program in the guest, "
        "which cannot be collected during a one-click edit."
    )

    def list_guests(self, cli: str) -> list[Guest]:
        try:
            proc = subprocess.run(
                [cli, "list"], capture_output=True, text=True, check=True
            )
        except (subprocess.SubprocessError, OSError):
            return []
        guests: list[Guest] = []
        for line in proc.stdout.strip().splitlines()[1:]:
            entry = line.strip()
            if entry.lower().endswith(".vmx"):
                guests.append(Guest(self.name, Path(entry).stem, "running"))
        return guests

    def activate(self) -> None:
        _activate_app("VMware Fusion")


class VirtualBoxBackend(VmBackend):
    """VirtualBox. Detected only; guest execution needs credentials."""

    name = "virtualbox"
    display_name = "VirtualBox"
    cli_name = "VBoxManage"
    cli_candidates = (
        "/usr/local/bin/VBoxManage",
        "/opt/homebrew/bin/VBoxManage",
        "/Applications/VirtualBox.app/Contents/MacOS/VBoxManage",
    )
    limitation = (
        "VBoxManage guestcontrol requires guest credentials (--username/--password), "
        "which cannot be collected during a one-click edit."
    )

    def list_guests(self, cli: str) -> list[Guest]:
        try:
            proc = subprocess.run(
                [cli, "list", "runningvms"], capture_output=True, text=True, check=True
            )
        except (subprocess.SubprocessError, OSError):
            return []
        guests: list[Guest] = []
        for line in proc.stdout.strip().splitlines():
            entry = line.strip()
            if entry.startswith('"') and '"' in entry[1:]:
                guests.append(Guest(self.name, entry[1 : entry.index('"', 1)], "running"))
        return guests

    def activate(self) -> None:
        _activate_app("VirtualBox")


#: Every backend SlideBridge knows how to look for, in preference order.
BACKENDS: tuple[VmBackend, ...] = (
    ParallelsBackend(),
    UtmBackend(),
    VmwareFusionBackend(),
    VirtualBoxBackend(),
)


def get_backend(name: str) -> VmBackend:
    """Look up a backend by its short name."""
    for backend in BACKENDS:
        if backend.name == name:
            return backend
    known = ", ".join(b.name for b in BACKENDS)
    raise SlideBridgeError(f"Unknown VM backend {name!r}. Known backends: {known}.")


def installed_backends() -> list[VmBackend]:
    """Backends whose CLI was actually found on this host."""
    return [backend for backend in BACKENDS if backend.is_installed()]


def detect_guest(preferred_backend: str | None = None) -> Guest:
    """Return a running Windows guest, searching every known backend.

    Backends are tried in preference order (Parallels first). A guest whose
    name contains "windows" wins within a backend. Raises a SlideBridgeError
    subclass describing what was found when nothing usable is available, so
    callers can tell "no hypervisor" from "hypervisor unreachable" from
    "nothing running".
    """
    backends = [get_backend(preferred_backend)] if preferred_backend else list(BACKENDS)

    found_but_unusable: list[str] = []
    query_errors: list[VmQueryError] = []
    seen_installed = False

    for backend in backends:
        cli = backend.find_cli()
        if not cli:
            continue
        seen_installed = True

        try:
            guests = backend.list_guests(cli)
        except VmQueryError as exc:
            # A broken higher-preference backend must not hide a working one.
            query_errors.append(exc)
            continue

        if not guests:
            continue

        chosen = _prefer_windows(guests)
        if not backend.supports_one_click:
            found_but_unusable.append(f"{backend.display_name} ({chosen.name})")
            continue

        if chosen.status == "paused":
            backend.resume(cli, chosen)
            chosen = Guest(chosen.backend, chosen.name, "running")
        return chosen

    if found_but_unusable:
        detail = "; ".join(found_but_unusable)
        raise UnsupportedBackendError(
            "Found a running Windows VM, but SlideBridge cannot edit through it yet: "
            f"{detail}. Only Parallels Desktop supports credential-free one-click editing."
        )

    if query_errors:
        raise query_errors[0]

    if not seen_installed:
        raise NoVmBackendError(
            "No supported VM hypervisor found. SlideBridge looked for "
            + ", ".join(f"{b.cli_name} ({b.display_name})" for b in backends)
            + ". Install Parallels Desktop, or pass --vm-backend with a supported host."
        )

    raise NoRunningGuestError(
        "No running Windows VM found. Please start your Windows VM first."
    )


def _prefer_windows(guests: list[Guest]) -> Guest:
    for guest in guests:
        if "windows" in guest.name.lower():
            return guest
    return guests[0]


def detect_running_vm(prlctl_bin: str = "prlctl") -> str:
    """Return the name of a running Windows guest (backwards-compatible wrapper).

    Prefer :func:`detect_guest`, which also reports which backend matched.
    """
    return detect_guest().name


def mac_to_vm_path(mac_path: os.PathLike[str] | str) -> str:
    """Convert a macOS POSIX path to a Parallels Windows UNC shared path.

    E.g. /Users/earth/Documents/foo.bin -> \\\\Mac\\Home\\Documents\\foo.bin

    This mapping is Parallels-specific; other hypervisors share folders
    differently and are not supported for one-click editing.
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


def _activate_app(app_name: str) -> None:
    try:
        subprocess.run(
            ["osascript", "-e", f'tell application "{app_name}" to activate'],
            capture_output=True,
            check=False,
        )
    except OSError:
        pass


def launch_vm_helper(
    guest: Guest | str,
    session_dir: os.PathLike[str] | str,
    helper_exe: os.PathLike[str] | str | None = None,
    clsid: str = _DEFAULT_CLSID,
    prlctl_bin: str = "prlctl",
    backend: str | None = None,
) -> int:
    """Launch origin-bridge.exe inside the given guest.

    ``guest`` may be a :class:`Guest` or a bare VM name (Parallels, for
    backwards compatibility). Blocks until the user closes the helper window.
    Returns the helper's exit code.
    """
    if isinstance(guest, str):
        guest = Guest("parallels", guest)

    if backend and backend != guest.backend:
        guest = Guest(backend, guest.name, guest.status)

    host = get_backend(guest.backend)
    cli = host.find_cli()
    if not cli:
        raise SlideBridgeError(
            f"{host.display_name or host.name} CLI {host.cli_name!r} not found. "
            f"Ensure {host.display_name or host.name} is installed."
        )

    session_path = Path(session_dir).resolve()
    editable_mac = session_path / "editable.bin"
    edited_mac = session_path / "edited.bin"

    if not editable_mac.is_file():
        raise SlideBridgeError(f"editable.bin not found in session: {session_path}")

    if helper_exe is None:
        project_root = Path(__file__).resolve().parent.parent
        default_exe = project_root / "dist" / "origin-bridge.exe"
        if not default_exe.is_file():
            legacy_exe = project_root / "artifacts" / "bin" / "origin-bridge.exe"
            if legacy_exe.is_file():
                default_exe = legacy_exe
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

    host.activate()

    _require_guest_reachable(helper_exe, "Windows Helper")
    _require_guest_reachable(editable_mac, "session")

    return host.run_program(
        cli,
        guest,
        [
            mac_to_vm_path(helper_exe),
            "edit",
            mac_to_vm_path(editable_mac),
            mac_to_vm_path(edited_mac),
            "--clsid",
            clsid,
        ],
    )


def _require_guest_reachable(path: Path, label: str) -> None:
    """Fail fast when a path cannot be addressed from the guest.

    The guest reaches the Mac through the home folder share (``\\\\Mac\\Home``).
    Anything outside the home directory is not addressable, and the helper
    reports only an opaque HRESULT, so catch it here with an explanation.
    """
    try:
        path.resolve().relative_to(Path.home().resolve())
    except ValueError:
        raise SlideBridgeError(
            f"The {label} path is outside your home folder: {path}\n"
            "The Windows guest can only see the Mac home folder (as \\\\Mac\\Home), so "
            "SlideBridge cannot hand this path to the helper.\n"
            "Pass --session with a directory under your home folder, or move the project there."
        ) from None
