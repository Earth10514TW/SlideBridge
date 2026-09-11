from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch, MagicMock

from slidebridge.core import SlideBridgeError
from slidebridge.bridge import list_ole_objects
from slidebridge.vm import detect_running_vm, mac_to_vm_path, launch_vm_helper
from test_bridge import package_with_preview, cfb_payload, minimal_png


class VmModuleTests(unittest.TestCase):
    def test_mac_to_vm_path_under_home(self):
        home = Path.home()
        test_path = home / "Documents" / "project" / "test.bin"
        vm_path = mac_to_vm_path(test_path)
        expected = r"\\Mac\Home\Documents\project\test.bin"
        self.assertEqual(vm_path, expected)

    def test_mac_to_vm_path_outside_home(self):
        test_path = Path("/Volumes/External/Data/test.bin")
        vm_path = mac_to_vm_path(test_path)
        expected = r"\\Mac\Host\Volumes\External\Data\test.bin"
        self.assertEqual(vm_path, expected)

    @patch("shutil.which")
    def test_detect_running_vm_missing_prlctl(self, mock_which):
        mock_which.return_value = None
        with self.assertRaises(SlideBridgeError) as ctx:
            detect_running_vm()
        self.assertIn("prlctl' not found", str(ctx.exception))

    @patch("subprocess.run")
    @patch("shutil.which")
    def test_detect_running_vm_selects_windows(self, mock_which, mock_run):
        mock_which.return_value = "/usr/local/bin/prlctl"
        sample_output = (
            "UUID                                    STATUS       IP_ADDR         NAME\n"
            "{11111111-1111-1111-1111-111111111111}  stopped      -               Ubuntu 22.04\n"
            "{22222222-2222-2222-2222-222222222222}  running      -               Windows 11 Lite\n"
        )
        mock_run.return_value = MagicMock(stdout=sample_output, returncode=0)
        vm = detect_running_vm()
        self.assertEqual(vm, "Windows 11 Lite")

    @patch("subprocess.run")
    @patch("shutil.which")
    def test_detect_running_vm_none_running(self, mock_which, mock_run):
        mock_which.return_value = "/usr/local/bin/prlctl"
        sample_output = (
            "UUID                                    STATUS       IP_ADDR         NAME\n"
            "{22222222-2222-2222-2222-222222222222}  stopped      -               Windows 11 Lite\n"
        )
        mock_run.return_value = MagicMock(stdout=sample_output, returncode=0)
        with self.assertRaises(SlideBridgeError) as ctx:
            detect_running_vm()
        self.assertIn("No running Parallels VM found", str(ctx.exception))

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
