"""Tests for the Mac PowerPoint one-click preflight."""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from slidebridge import doctor
from slidebridge.core import SlideBridgeError
from slidebridge.doctor import Check, FAIL, INFO, OK, WARN, format_report
from slidebridge.vm import (
    NoRunningGuestError,
    NoVmBackendError,
    UnsupportedBackendError,
    VmQueryError,
)


class FakeBackend:
    def __init__(self, name, display_name, cli_name, cli_path, supports_one_click):
        self.name = name
        self.display_name = display_name
        self.cli_name = cli_name
        self.cli_path = cli_path
        self.supports_one_click = supports_one_click

    def find_cli(self):
        return self.cli_path


class PythonCheckTests(unittest.TestCase):
    """The check must reflect what the one-click wrapper will use, not what ran doctor."""

    def test_usable_interpreter_from_the_wrapper_passes(self):
        with patch.object(doctor, "wrapper_python", return_value=("/usr/local/bin/python3", "")):
            with patch.object(doctor, "_interpreter_version", return_value=(3, 14, 7)):
                check = doctor.check_python()
        self.assertEqual(check.status, OK)
        self.assertIn("/usr/local/bin/python3", check.detail)
        self.assertIn("3.14.7", check.detail)

    def test_wrapper_finding_nothing_fails_without_naming_homebrew(self):
        with patch.object(doctor, "wrapper_python", return_value=(None, "no suitable interpreter found")):
            check = doctor.check_python()
        self.assertEqual(check.status, FAIL)
        self.assertIn("SLIDEBRIDGE_PYTHON", check.fix)
        # The advice must not assume Homebrew is installed.
        self.assertNotIn("homebrew", check.fix.lower())

    def test_interpreter_below_minimum_fails(self):
        with patch.object(doctor, "wrapper_python", return_value=("/usr/bin/python3", "")):
            with patch.object(doctor, "_interpreter_version", return_value=(3, 9, 6)):
                check = doctor.check_python()
        self.assertEqual(check.status, FAIL)
        self.assertIn("3.9.6", check.detail)
        self.assertIn("SLIDEBRIDGE_PYTHON", check.fix)

    def test_unreadable_version_is_reported_as_unusable(self):
        with patch.object(doctor, "wrapper_python", return_value=("/weird/python3", "")):
            with patch.object(doctor, "_interpreter_version", return_value=None):
                check = doctor.check_python()
        self.assertEqual(check.status, FAIL)
        self.assertIn("unusable", check.detail)

    def test_detail_mentions_the_running_interpreter_when_it_differs(self):
        with patch.object(doctor, "wrapper_python", return_value=("/usr/local/bin/python3", "")):
            with patch.object(doctor, "_interpreter_version", return_value=(3, 14, 7)):
                check = doctor.check_python()
        if Path(sys.executable).resolve() != Path("/usr/local/bin/python3").resolve():
            self.assertIn("this run used", check.detail)

    def test_wrapper_python_reports_a_missing_script(self):
        with tempfile.TemporaryDirectory() as td:
            with patch.object(doctor, "project_root", return_value=Path(td)):
                chosen, error = doctor.wrapper_python()
        self.assertIsNone(chosen)
        self.assertIn("not found", error)


class RecordedRootTests(unittest.TestCase):
    def test_missing_is_a_warning_not_a_failure(self):
        with tempfile.TemporaryDirectory() as td:
            with patch.object(doctor, "RECORDED_ROOT", Path(td) / "absent"):
                check = doctor.check_recorded_root()
        self.assertEqual(check.status, WARN)
        self.assertIn("install_mac_integration.sh", check.fix)

    def test_matching_root_is_ok(self):
        with tempfile.TemporaryDirectory() as td:
            recorded = Path(td) / "project-root"
            recorded.write_text(str(doctor.project_root()) + "\n")
            with patch.object(doctor, "RECORDED_ROOT", recorded):
                check = doctor.check_recorded_root()
        self.assertEqual(check.status, OK)

    def test_mismatched_root_points_at_the_installer(self):
        with tempfile.TemporaryDirectory() as td:
            recorded = Path(td) / "project-root"
            recorded.write_text("/somewhere/else/SlideBridge\n")
            with patch.object(doctor, "RECORDED_ROOT", recorded):
                check = doctor.check_recorded_root()
        self.assertEqual(check.status, WARN)
        self.assertIn("/somewhere/else/SlideBridge", check.detail)
        self.assertIn("install_mac_integration.sh", check.fix)


class HandlerTests(unittest.TestCase):
    def test_missing_handler_fails(self):
        with tempfile.TemporaryDirectory() as td:
            with patch.object(doctor, "HANDLER_SCRIPT", Path(td) / "SlideBridge.scpt"):
                check = doctor.check_handler()
        self.assertEqual(check.status, FAIL)
        self.assertIn("install_mac_integration.sh", check.fix)

    def test_handler_referencing_this_checkout_is_ok(self):
        """Compiled AppleScript stores literals as UTF-16BE; we read them directly."""
        with tempfile.TemporaryDirectory() as td:
            script = Path(td) / "SlideBridge.scpt"
            script.write_bytes(str(doctor.project_root()).encode("utf-16-be"))
            with patch.object(doctor, "HANDLER_SCRIPT", script):
                check = doctor.check_handler()
        self.assertEqual(check.status, OK)

    def test_handler_pointing_elsewhere_warns(self):
        with tempfile.TemporaryDirectory() as td:
            script = Path(td) / "SlideBridge.scpt"
            script.write_bytes("/somewhere/else".encode("utf-16-be"))
            with patch.object(doctor, "HANDLER_SCRIPT", script):
                check = doctor.check_handler()
        self.assertEqual(check.status, WARN)
        self.assertIn("install_mac_integration.sh", check.fix)


class BackendCheckTests(unittest.TestCase):
    def test_no_hypervisor_found_fails(self):
        backends = (FakeBackend("parallels", "Parallels Desktop", "prlctl", None, True),)
        with patch.object(doctor, "BACKENDS", backends):
            check = doctor.check_backends()
        self.assertEqual(check.status, FAIL)
        self.assertIn("prlctl", check.detail)

    def test_only_unsupported_backends_fails_with_reason(self):
        backends = (
            FakeBackend("parallels", "Parallels Desktop", "prlctl", None, True),
            FakeBackend("utm", "UTM", "utmctl", "/x/utmctl", False),
        )
        with patch.object(doctor, "BACKENDS", backends):
            check = doctor.check_backends()
        self.assertEqual(check.status, FAIL)
        self.assertIn("UTM", check.detail)
        self.assertIn("Parallels Desktop", check.fix)

    def test_parallels_present_is_ok(self):
        backends = (
            FakeBackend("parallels", "Parallels Desktop", "prlctl", "/usr/local/bin/prlctl", True),
        )
        with patch.object(doctor, "BACKENDS", backends):
            check = doctor.check_backends()
        self.assertEqual(check.status, OK)
        self.assertIn("/usr/local/bin/prlctl", check.detail)


class GuestCheckTests(unittest.TestCase):
    """The three failure modes need different advice, so they are reported apart."""

    def test_nothing_running_tells_you_to_boot_the_vm(self):
        with patch.object(
            doctor, "detect_guest", side_effect=NoRunningGuestError("No running Windows VM found.")
        ):
            check = doctor.check_guest()
        self.assertEqual(check.status, FAIL)
        self.assertIn("No running Windows VM found", check.detail)
        self.assertIn("Boot the Windows VM", check.fix)

    def test_unreachable_hypervisor_is_not_reported_as_a_missing_vm(self):
        """The case that caused real confusion: prlctl exists but cannot be queried."""
        with patch.object(
            doctor, "detect_guest", side_effect=VmQueryError("prlctl list returned non-zero")
        ):
            check = doctor.check_guest()
        self.assertEqual(check.status, FAIL)
        self.assertIn("could not be queried", check.detail)
        self.assertIn("Parallels Desktop", check.fix)
        # Must not claim the VM is missing, and must not ask for anything in Windows.
        self.assertNotIn("Boot the Windows VM", check.fix)

    def test_no_hypervisor_at_all(self):
        with patch.object(doctor, "detect_guest", side_effect=NoVmBackendError("none found")):
            check = doctor.check_guest()
        self.assertEqual(check.status, FAIL)
        self.assertIn("Install Parallels Desktop", check.fix)

    def test_unsupported_backend_explains_itself(self):
        with patch.object(doctor, "detect_guest", side_effect=UnsupportedBackendError("UTM only")):
            check = doctor.check_guest()
        self.assertEqual(check.status, FAIL)
        self.assertIn("Parallels Desktop", check.fix)

    def test_unexpected_error_is_still_surfaced(self):
        with patch.object(doctor, "detect_guest", side_effect=SlideBridgeError("something odd")):
            check = doctor.check_guest()
        self.assertEqual(check.status, FAIL)
        self.assertIn("something odd", check.detail)

    def test_running_guest_is_ok(self):
        from slidebridge.vm import Guest

        with patch.object(doctor, "detect_guest", return_value=Guest("parallels", "Windows 11 Lite")):
            check = doctor.check_guest()
        self.assertEqual(check.status, OK)
        self.assertIn("Windows 11 Lite", check.detail)


class HelperCheckTests(unittest.TestCase):
    def test_missing_helper_fails(self):
        with tempfile.TemporaryDirectory() as td:
            with patch.object(doctor, "project_root", return_value=Path(td)):
                check = doctor.check_helper()
        self.assertEqual(check.status, FAIL)
        self.assertIn("build_origin_bridge.sh", check.fix)

    def test_present_helper_reports_size_in_dist(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "dist").mkdir(parents=True)
            (root / "dist" / "origin-bridge.exe").write_bytes(b"MZ" * 1024)
            with patch.object(doctor, "project_root", return_value=root):
                check = doctor.check_helper()
        self.assertEqual(check.status, OK)
        self.assertIn("MB", check.detail)


class ResvgCheckTests(unittest.TestCase):
    def test_resvg_found_reports_ok(self):
        with patch("slidebridge.cli.find_resvg", return_value="/mock/resvg"):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value.stdout = "resvg 0.48.1\n"
                mock_run.return_value.returncode = 0
                check = doctor.check_resvg()
        self.assertEqual(check.status, OK)
        self.assertIn("/mock/resvg", check.detail)

    def test_resvg_missing_reports_fail_with_install_advice(self):
        with patch("slidebridge.cli.find_resvg", return_value=None):
            check = doctor.check_resvg()
        self.assertEqual(check.status, FAIL)
        self.assertIn("install_mac_integration.sh", check.fix)
        self.assertIn("brew install resvg", check.fix)


class ReportTests(unittest.TestCase):
    def test_report_marks_each_status_and_lists_fixes(self):
        checks = [
            Check("Python interpreter", OK, "3.13.12"),
            Check("Running Windows guest", FAIL, "nothing running", "Start the Windows VM."),
        ]
        text = format_report(checks)
        self.assertIn("[ ok ]", text)
        self.assertIn("[FAIL]", text)
        self.assertIn("Start the Windows VM.", text)

    def test_report_with_no_problems_says_so(self):
        text = format_report([Check("Python interpreter", OK, "3.13.12")])
        self.assertIn("All checks passed", text)

    def test_doctor_ready_flag_reflects_failures(self):
        with patch.object(doctor, "run_checks", return_value=[Check("x", OK, "fine")]):
            with patch("builtins.print"):
                self.assertTrue(doctor.doctor()["ready"])

        with patch.object(doctor, "run_checks", return_value=[Check("x", FAIL, "broken", "fix it")]):
            with patch("builtins.print"):
                report = doctor.doctor()
        self.assertFalse(report["ready"])
        self.assertEqual(report["failures"], 1)

    def test_json_output_is_valid(self):
        import json

        with patch.object(doctor, "run_checks", return_value=[Check("x", WARN, "meh", "fix")]):
            captured = {}
            with patch("builtins.print", side_effect=lambda *a, **k: captured.setdefault("out", a[0])):
                report = doctor.doctor(as_json=True)
        self.assertEqual(json.loads(captured["out"])["warnings"], 1)
        self.assertEqual(report["warnings"], 1)

    def test_automation_permission_reports_valid_status(self):
        check = doctor.check_automation_permission()
        self.assertIn(check.status, {OK, INFO, FAIL})
        self.assertEqual(check.name, "Automation permission")

    def test_automation_permission_granted_via_probe(self):
        with patch("subprocess.run") as mock_run:
            def side_effect(cmd, **kwargs):
                from unittest.mock import MagicMock
                res = MagicMock()
                if cmd[0] == "pgrep":
                    res.returncode = 0
                elif "osascript" in cmd:
                    res.returncode = 0
                    res.stdout = "Microsoft PowerPoint\n"
                    res.stderr = ""
                return res
            mock_run.side_effect = side_effect
            with patch("ctypes.cdll.LoadLibrary", side_effect=Exception("mock ctypes bypass")):
                check = doctor.check_automation_permission()
        self.assertEqual(check.status, OK)
        self.assertIn("granted", check.detail)

    def test_automation_permission_denied_via_probe(self):
        with patch("subprocess.run") as mock_run:
            def side_effect(cmd, **kwargs):
                from unittest.mock import MagicMock
                res = MagicMock()
                if cmd[0] == "pgrep":
                    res.returncode = 0
                elif "osascript" in cmd:
                    res.returncode = 1
                    res.stdout = ""
                    res.stderr = "execution error: Not authorized to send Apple events (-1743)\n"
                return res
            mock_run.side_effect = side_effect
            with patch("ctypes.cdll.LoadLibrary", side_effect=Exception("mock ctypes bypass")):
                check = doctor.check_automation_permission()
        self.assertEqual(check.status, FAIL)
        self.assertIn("-1743", check.detail)


if __name__ == "__main__":
    unittest.main()
