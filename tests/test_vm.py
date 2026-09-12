from contextlib import contextmanager
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from slidebridge.core import SlideBridgeError
from slidebridge.bridge import list_ole_objects
from slidebridge.vm import (
    Guest,
    ParallelsBackend,
    UtmBackend,
    detect_guest,
    detect_running_vm,
    get_backend,
    installed_backends,
    launch_vm_helper,
    mac_to_vm_path,
)
from test_bridge import package_with_preview, cfb_payload, minimal_png


PARALLELS_LIST = (
    "UUID                                    STATUS       IP_ADDR         NAME\n"
    "{11111111-1111-1111-1111-111111111111}  stopped      -               Ubuntu 22.04\n"
    "{22222222-2222-2222-2222-222222222222}  running      -               Windows 11 Lite\n"
)

PARALLELS_PAUSED = (
    "UUID                                    STATUS       IP_ADDR         NAME\n"
    "{22222222-2222-2222-2222-222222222222}  paused       -               Windows 11 Lite\n"
)

UTM_LIST = (
    "UUID                                 Status    Name\n"
    "4A5C6E7F-1234-5678-9ABC-DEF012345678 started   Windows 11\n"
)


def only(name_to_path):
    """Build a find_executable stand-in that only knows the given CLIs."""

    def _fake(name, **_kwargs):
        return name_to_path.get(name)

    return _fake


@contextmanager
def fake_home():
    """Pretend a temporary directory is the user's home folder.

    Keeps the tests off the real home directory (the guest path translation is
    anchored to it) and makes ``\\\\Mac\\Home`` assertions deterministic.
    """
    with tempfile.TemporaryDirectory() as td:
        with patch("pathlib.Path.home", return_value=Path(td)):
            yield Path(td)


def exec_argv(mock_run):
    """Return the argv of the prlctl exec call, if the helper was launched.

    Scans the recorded calls rather than taking the last one: the surrounding
    environment injects its own subprocess calls, and ``subprocess.run`` is
    patched process-wide here.
    """
    for call in mock_run.call_args_list:
        argv = call.args[0] if call.args else []
        if isinstance(argv, (list, tuple)) and argv and str(argv[0]).endswith("prlctl"):
            return list(argv)
    return None


class MacToVmPathTests(unittest.TestCase):
    def test_path_under_home(self):
        test_path = Path.home() / "Documents" / "project" / "test.bin"
        self.assertEqual(
            mac_to_vm_path(test_path), r"\\Mac\Home\Documents\project\test.bin"
        )

    def test_path_outside_home(self):
        test_path = Path("/Volumes/External/Data/test.bin")
        self.assertEqual(
            mac_to_vm_path(test_path), r"\\Mac\Host\Volumes\External\Data\test.bin"
        )


class BackendRegistryTests(unittest.TestCase):
    def test_get_backend_known(self):
        self.assertEqual(get_backend("parallels").cli_name, "prlctl")

    def test_get_backend_unknown_lists_known_names(self):
        with self.assertRaises(SlideBridgeError) as ctx:
            get_backend("hyperv")
        self.assertIn("hyperv", str(ctx.exception))
        self.assertIn("parallels", str(ctx.exception))

    def test_installed_backends_reports_only_found_clis(self):
        with patch("slidebridge.vm.find_executable", side_effect=only({"prlctl": "/x/prlctl"})):
            names = [b.name for b in installed_backends()]
        self.assertEqual(names, ["parallels"])


class DetectGuestTests(unittest.TestCase):
    @patch("subprocess.run")
    @patch("slidebridge.vm.find_executable")
    def test_selects_windows_guest_on_parallels(self, mock_find, mock_run):
        mock_find.side_effect = only({"prlctl": "/usr/local/bin/prlctl"})
        mock_run.return_value = MagicMock(stdout=PARALLELS_LIST, returncode=0)

        guest = detect_guest()

        self.assertEqual(guest.backend, "parallels")
        self.assertEqual(guest.name, "Windows 11 Lite")

    @patch("subprocess.run")
    @patch("slidebridge.vm.find_executable")
    def test_resumes_a_paused_guest(self, mock_find, mock_run):
        mock_find.side_effect = only({"prlctl": "/usr/local/bin/prlctl"})
        mock_run.return_value = MagicMock(stdout=PARALLELS_PAUSED, returncode=0)

        guest = detect_guest()

        self.assertEqual(guest.status, "running")
        commands = [call.args[0] for call in mock_run.call_args_list]
        self.assertIn(["/usr/local/bin/prlctl", "resume", "Windows 11 Lite"], commands)

    @patch("slidebridge.vm.find_executable")
    def test_no_hypervisor_installed_names_what_was_searched(self, mock_find):
        mock_find.side_effect = only({})
        with self.assertRaises(SlideBridgeError) as ctx:
            detect_guest()
        message = str(ctx.exception)
        self.assertIn("prlctl", message)
        self.assertIn("Parallels Desktop", message)

    @patch("subprocess.run")
    @patch("slidebridge.vm.find_executable")
    def test_running_guest_on_unsupported_backend_is_reported_clearly(
        self, mock_find, mock_run
    ):
        """A UTM guest is found, but must not masquerade as a usable one."""
        mock_find.side_effect = only({"utmctl": "/Applications/UTM.app/Contents/MacOS/utmctl"})
        mock_run.return_value = MagicMock(stdout=UTM_LIST, returncode=0)

        with self.assertRaises(SlideBridgeError) as ctx:
            detect_guest()

        message = str(ctx.exception)
        self.assertIn("UTM", message)
        self.assertIn("Windows 11", message)
        self.assertIn("cannot edit through it yet", message)

    @patch("subprocess.run")
    @patch("slidebridge.vm.find_executable")
    def test_installed_but_nothing_running(self, mock_find, mock_run):
        mock_find.side_effect = only({"prlctl": "/usr/local/bin/prlctl"})
        mock_run.return_value = MagicMock(
            stdout="UUID   STATUS   IP_ADDR   NAME\n"
            "{22222222-2222-2222-2222-222222222222}  stopped  -  Windows 11 Lite\n",
            returncode=0,
        )
        with self.assertRaises(SlideBridgeError) as ctx:
            detect_guest()
        self.assertIn("No running Windows VM found", str(ctx.exception))

    @patch("subprocess.run")
    @patch("slidebridge.vm.find_executable")
    def test_preferred_backend_restricts_the_search(self, mock_find, mock_run):
        mock_find.side_effect = only({"utmctl": "/x/utmctl", "prlctl": "/x/prlctl"})
        mock_run.return_value = MagicMock(stdout=UTM_LIST, returncode=0)

        with self.assertRaises(SlideBridgeError):
            detect_guest("utm")

        commands = [call.args[0] for call in mock_run.call_args_list]
        self.assertEqual(commands, [["/x/utmctl", "list"]])

    @patch("subprocess.run")
    @patch("slidebridge.vm.find_executable")
    def test_detect_running_vm_wrapper_returns_name(self, mock_find, mock_run):
        mock_find.side_effect = only({"prlctl": "/usr/local/bin/prlctl"})
        mock_run.return_value = MagicMock(stdout=PARALLELS_LIST, returncode=0)
        self.assertEqual(detect_running_vm(), "Windows 11 Lite")


class BackendCommandTests(unittest.TestCase):
    @patch("subprocess.run")
    def test_parallels_run_program_uses_current_user(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        backend = ParallelsBackend()

        code = backend.run_program(
            "/usr/local/bin/prlctl",
            Guest("parallels", "Windows 11 Lite"),
            [r"\\Mac\Home\helper.exe", "edit", r"\\Mac\Home\editable.bin"],
        )

        self.assertEqual(code, 0)
        self.assertEqual(
            mock_run.call_args.args[0],
            [
                "/usr/local/bin/prlctl",
                "exec",
                "Windows 11 Lite",
                "--current-user",
                r"\\Mac\Home\helper.exe",
                "edit",
                r"\\Mac\Home\editable.bin",
            ],
        )

    def test_unsupported_backend_explains_the_limitation(self):
        with self.assertRaises(SlideBridgeError) as ctx:
            UtmBackend().run_program("/x/utmctl", Guest("utm", "Windows 11"), ["a.exe"])
        message = str(ctx.exception)
        self.assertIn("UTM", message)
        self.assertIn("shared-folder", message)

    @patch("slidebridge.vm.find_executable", side_effect=only({}))
    def test_launch_helper_reports_missing_cli(self, _mock_find):
        with tempfile.TemporaryDirectory() as td:
            session = Path(td)
            (session / "editable.bin").write_bytes(b"x")
            with self.assertRaises(SlideBridgeError) as ctx:
                launch_vm_helper(Guest("parallels", "Windows 11 Lite"), session)
            self.assertIn("prlctl", str(ctx.exception))


class LaunchVmHelperTests(unittest.TestCase):
    """Sessions must live under the home folder -- that is the only path the
    Windows guest can address (\\Mac\\Home)."""

    @patch("subprocess.run")
    @patch("slidebridge.vm.find_executable")
    def test_launches_helper_with_translated_paths(self, mock_find, mock_run):
        mock_find.side_effect = only({"prlctl": "/usr/local/bin/prlctl"})
        mock_run.return_value = MagicMock(returncode=0)

        with fake_home() as home:
            session = home / "session"
            session.mkdir()
            (session / "editable.bin").write_bytes(b"ole")
            helper = session / "origin-bridge.exe"
            helper.write_bytes(b"MZ")

            code = launch_vm_helper(
                Guest("parallels", "Windows 11 Lite"), session, helper_exe=helper
            )
            expected_helper = mac_to_vm_path(helper)
            expected_editable = mac_to_vm_path(session / "editable.bin")

        self.assertEqual(code, 0)
        argv = exec_argv(mock_run)
        self.assertIsNotNone(argv, "the helper was never launched")
        self.assertEqual(argv[:4], ["/usr/local/bin/prlctl", "exec", "Windows 11 Lite", "--current-user"])
        self.assertEqual(argv[4], expected_helper)
        self.assertEqual(argv[5], "edit")
        self.assertEqual(argv[6], expected_editable)
        self.assertEqual(argv[8:], ["--clsid", "auto"])
        self.assertTrue(argv[4].startswith("\\\\Mac\\Home\\"))

    @patch("subprocess.run")
    @patch("slidebridge.vm.find_executable")
    def test_custom_clsid_is_passed_to_helper(self, mock_find, mock_run):
        mock_find.side_effect = only({"prlctl": "/usr/local/bin/prlctl"})
        mock_run.return_value = MagicMock(returncode=0)

        with fake_home() as home:
            session = home / "session"
            session.mkdir()
            (session / "editable.bin").write_bytes(b"ole")
            helper = session / "origin-bridge.exe"
            helper.write_bytes(b"MZ")

            launch_vm_helper(
                Guest("parallels", "Windows 11 Lite"),
                session,
                helper_exe=helper,
                clsid="{64CC80B2-4FA1-4F7B-9D6F-1BFACF5715DC}",
            )

        argv = exec_argv(mock_run)
        self.assertIsNotNone(argv)
        self.assertEqual(argv[8:], ["--clsid", "{64CC80B2-4FA1-4F7B-9D6F-1BFACF5715DC}"])

    @patch("subprocess.run")
    @patch("slidebridge.vm.find_executable")
    def test_bare_vm_name_is_treated_as_parallels(self, mock_find, mock_run):
        """Backwards compatibility for the old launch_vm_helper(vm_name, ...) call."""
        mock_find.side_effect = only({"prlctl": "/usr/local/bin/prlctl"})
        mock_run.return_value = MagicMock(returncode=0)

        with fake_home() as home:
            session = home / "session"
            session.mkdir()
            (session / "editable.bin").write_bytes(b"ole")
            helper = session / "origin-bridge.exe"
            helper.write_bytes(b"MZ")
            launch_vm_helper("Windows 11 Lite", session, helper_exe=helper)

        self.assertEqual(exec_argv(mock_run)[2], "Windows 11 Lite")

    @patch("subprocess.run")
    @patch("slidebridge.vm.find_executable")
    def test_missing_editable_bin_is_reported(self, mock_find, mock_run):
        mock_find.side_effect = only({"prlctl": "/usr/local/bin/prlctl"})
        with fake_home() as home:
            with self.assertRaises(SlideBridgeError) as ctx:
                launch_vm_helper(Guest("parallels", "Windows 11 Lite"), home / "session")
        self.assertIn("editable.bin not found", str(ctx.exception))

    @patch("subprocess.run")
    @patch("slidebridge.vm.find_executable")
    def test_session_outside_home_is_rejected_before_reaching_windows(
        self, mock_find, mock_run
    ):
        """Regression: /var/folders sessions produced an opaque ERROR_BAD_NET_NAME."""
        mock_find.side_effect = only({"prlctl": "/usr/local/bin/prlctl"})
        mock_run.return_value = MagicMock(returncode=0)

        with fake_home():
            with tempfile.TemporaryDirectory() as outside:
                session = Path(outside)
                (session / "editable.bin").write_bytes(b"ole")
                helper = session / "origin-bridge.exe"
                helper.write_bytes(b"MZ")

                with self.assertRaises(SlideBridgeError) as ctx:
                    launch_vm_helper(
                        Guest("parallels", "Windows 11 Lite"), session, helper_exe=helper
                    )

        message = str(ctx.exception)
        self.assertIn("outside your home folder", message)
        self.assertIn("--session", message)
        # The helper must never be launched with an unreachable path.
        self.assertIsNone(exec_argv(mock_run))

    @patch("subprocess.run")
    @patch("slidebridge.vm.find_executable")
    def test_helper_outside_home_is_rejected_too(self, mock_find, mock_run):
        mock_find.side_effect = only({"prlctl": "/usr/local/bin/prlctl"})
        mock_run.return_value = MagicMock(returncode=0)

        with fake_home() as home:
            session = home / "session"
            session.mkdir()
            (session / "editable.bin").write_bytes(b"ole")
            with tempfile.TemporaryDirectory() as outside:
                helper = Path(outside) / "origin-bridge.exe"
                helper.write_bytes(b"MZ")
                with self.assertRaises(SlideBridgeError) as ctx:
                    launch_vm_helper(
                        Guest("parallels", "Windows 11 Lite"), session, helper_exe=helper
                    )

        self.assertIn("Windows Helper path is outside", str(ctx.exception))
        self.assertIsNone(exec_argv(mock_run))


class ListOleObjectsTests(unittest.TestCase):
    def test_list_ole_objects(self):
        with tempfile.TemporaryDirectory() as td:
            pptx_path = Path(td) / "test.pptx"
            package_with_preview(pptx_path, cfb_payload(), minimal_png())
            objects = list_ole_objects(pptx_path)
            self.assertEqual(len(objects), 1)
            self.assertEqual(objects[0]["member"], "ppt/embeddings/object1.bin")
            self.assertEqual(objects[0]["slides"], ["ppt/slides/slide1.xml"])
            self.assertEqual(objects[0]["previews"], ["ppt/media/image1.png"])


if __name__ == "__main__":
    unittest.main()
