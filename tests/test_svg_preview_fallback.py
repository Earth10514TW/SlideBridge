import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from slidebridge.bridge import prepare_ole, writeback_ole
from slidebridge.core import SlideBridgeError

from test_bridge import cfb_payload, minimal_png, package_with_preview


class SvgPreviewFallbackTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "input.pptx"
        self.session = self.root / "session"
        self.output = self.root / "output.pptx"

        package_with_preview(self.source, cfb_payload(), minimal_png())
        prepare_ole(self.source, "ppt/embeddings/object1.bin", self.session)
        (self.session / "edited.bin").write_bytes(cfb_payload(1))
        (self.session / "preview.svg").write_text("<svg/>")

    def _run(self, run_side_effect, *, executables=("/mock/resvg", "/mock/inkscape"), **kwargs):
        def locate(name, **_kwargs):
            return executables[0] if name == "resvg" else executables[1]

        with patch("slidebridge.bridge.find_executable", side_effect=locate, create=True), patch(
            "slidebridge.bridge.subprocess.run", side_effect=run_side_effect
        ) as run:
            report = writeback_ole(self.source, self.session, self.output, **kwargs)
        return report, run

    def test_resvg_success_skips_inkscape(self):
        def render(command, **_kwargs):
            Path(command[2]).write_bytes(minimal_png(20, 20, b"resvg"))

        report, run = self._run(render)

        self.assertEqual(report["preview_source"], str(self.session / "preview_from_svg.png"))
        self.assertEqual(run.call_count, 1)
        self.assertIn("resvg", run.call_args.args[0][0])
        self.assertTrue((self.session / "preview_from_svg.png").is_file())

    def test_resvg_invalid_output_falls_back_to_inkscape(self):
        def render(command, **_kwargs):
            if "resvg" in command[0]:
                Path(command[2]).write_bytes(b"not a png")
            else:
                Path(command[2].split("=", 1)[1]).write_bytes(minimal_png(30, 30, b"inkscape"))

        report, run = self._run(render)

        self.assertEqual(report["preview_source"], str(self.session / "preview_from_svg.png"))
        self.assertEqual(run.call_count, 2)
        self.assertIn("inkscape", run.call_args.args[0][0])
        self.assertEqual(list(self.session.glob(".slidebridge-svg-*.png")), [])

    def test_resvg_nonzero_exit_falls_back_to_inkscape(self):
        def render(command, **_kwargs):
            if "resvg" in command[0]:
                return SimpleNamespace(returncode=1)
            Path(command[2].split("=", 1)[1]).write_bytes(minimal_png(30, 30, b"inkscape"))

        report, run = self._run(render)

        self.assertEqual(report["preview_source"], str(self.session / "preview_from_svg.png"))
        self.assertEqual(run.call_count, 2)

    def test_resvg_missing_output_falls_back_to_inkscape(self):
        def render(command, **_kwargs):
            if "inkscape" in command[0]:
                Path(command[2].split("=", 1)[1]).write_bytes(minimal_png(30, 30, b"inkscape"))

        report, run = self._run(render)

        self.assertEqual(report["preview_source"], str(self.session / "preview_from_svg.png"))
        self.assertEqual(run.call_count, 2)

    def test_resvg_failure_falls_back_to_inkscape(self):
        def render(command, **_kwargs):
            if "resvg" in command[0]:
                raise OSError("renderer unavailable")
            Path(command[2].split("=", 1)[1]).write_bytes(minimal_png(30, 30, b"inkscape"))

        report, run = self._run(render)

        self.assertEqual(report["preview_source"], str(self.session / "preview_from_svg.png"))
        self.assertEqual(run.call_count, 2)

    def test_failed_svg_attempt_does_not_accept_stale_output_and_uses_manual_preview(self):
        stale = minimal_png(99, 99, b"stale")
        (self.session / "preview_from_svg.png").write_bytes(stale)
        manual = minimal_png(40, 40, b"manual")
        (self.session / "preview.png").write_bytes(manual)

        def render(_command, **_kwargs):
            # A successful exit without a new image must not reuse the stale
            # published image from the previous edit session.
            return SimpleNamespace(returncode=0)

        report, run = self._run(render, executables=("/mock/resvg", None))

        self.assertEqual(report["preview_source"], str(self.session / "preview.png"))
        self.assertEqual(run.call_count, 1)
        self.assertEqual((self.session / "preview_from_svg.png").read_bytes(), stale)

    def test_missing_svg_renderers_use_manual_preview(self):
        manual = minimal_png(40, 40, b"manual")
        (self.session / "preview.png").write_bytes(manual)

        report, run = self._run(lambda *_args, **_kwargs: None, executables=(None, None))

        self.assertEqual(report["preview_source"], str(self.session / "preview.png"))
        run.assert_not_called()

    def test_explicit_preview_bypasses_svg_rendering(self):
        manual = minimal_png(40, 40, b"explicit")
        explicit = self.session / "explicit.png"
        explicit.write_bytes(manual)

        report, run = self._run(lambda *_args, **_kwargs: None, preview_path=explicit)

        self.assertEqual(report["preview_source"], str(explicit))
        run.assert_not_called()

    def test_failed_svg_rendering_preserves_paired_preview_guard(self):
        def render(_command, **_kwargs):
            raise OSError("renderer unavailable")

        with self.assertRaises(SlideBridgeError) as ctx:
            self._run(render, executables=("/mock/resvg", None))
        self.assertIn("paired writeback requires a preview image", str(ctx.exception).lower())
        self.assertFalse((self.session / "preview_from_svg.png").exists())
        self.assertEqual(list(self.session.glob(".slidebridge-svg-*.png")), [])


if __name__ == "__main__":
    unittest.main()
