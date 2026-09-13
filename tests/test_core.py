import base64
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import subprocess
import zipfile
import xml.etree.ElementTree as ET

from slidebridge.core import scan, repair, SlideBridgeError, png_white_to_transparent
from slidebridge.cli import main

R = 'http://schemas.openxmlformats.org/package/2006/relationships'
PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=')


def fixture(path):
    parts = {
        '[Content_Types].xml': '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="emf" ContentType="image/x-emf"/><Default Extension="wmf" ContentType="image/x-wmf"/></Types>',
        'ppt/presentation.xml': '<p:presentation xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"/>',
        'ppt/slides/slide1.xml': '<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><p:oleObj r:id="ole1" progId="Origin.Graph"><p:embed/><p:pic><p:blipFill><a:blip r:embed="im1"/></p:blipFill></p:pic></p:oleObj></p:sld>',
        'ppt/slides/_rels/slide1.xml.rels': f'<Relationships xmlns="{R}"><Relationship Id="im1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="../media/image1.emf"/><Relationship Id="im2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="../media/image2.WMF"/><Relationship Id="ole1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/oleObject" Target="../embeddings/oleObject1.bin"/><Relationship Id="external" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="https://example.com/image1.emf" TargetMode="External"/></Relationships>',
        'ppt/media/image1.emf': b'fake emf',
        'ppt/media/image2.WMF': b'fake wmf',
        'ppt/embeddings/oleObject1.bin': b'\x00Origin opaque OLE\xff',
        'docProps/custom.xml': '<custom/>',
    }
    with zipfile.ZipFile(path, 'w') as archive:
        for name, data in parts.items():
            archive.writestr(name, data)
    return parts


def renderer(command, **kwargs):
    if "-i" in command and "-o" in command:
        out_svg = command[command.index("-o") + 1]
        Path(out_svg).write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"></svg>')
        return subprocess.CompletedProcess(command, 0, "", "")
    out_png = command[2]
    Path(out_png).write_bytes(PNG)
    return subprocess.CompletedProcess(command, 0, "", "")


class CoreTests(unittest.TestCase):
    def setUp(self):
        def default_which(cmd):
            if "emf2svg" in cmd:
                return "/mock/bin/emf2svg-conv"
            if "resvg" in cmd:
                return "/mock/bin/resvg"
            return None

        discovery = patch('slidebridge.core.shutil.which', side_effect=default_which)
        discovery.start()
        self.addCleanup(discovery.stop)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.source = Path(self.temp.name) / 'input.pptx'
        self.output = Path(self.temp.name) / 'output.pptx'
        fixture(self.source)

    def test_scan_marks_ole_preview(self):
        result = scan(self.source)
        self.assertEqual(result['ole_objects'], 1)
        by_path = {x['path']: x for x in result['media']}
        self.assertTrue(by_path['ppt/media/image1.emf']['ole_preview'])
        self.assertFalse(by_path['ppt/media/image2.WMF']['ole_preview'])

    @patch('slidebridge.core.subprocess.run', side_effect=renderer)
    def test_repair_preserves_ole_slide_and_original(self, run):
        original = self.source.read_bytes()
        result = repair(self.source, self.output)
        self.assertEqual(len(result['converted']), 1)
        self.assertEqual(len(result.get('skipped', [])), 1)
        self.assertEqual(result['skipped'][0]['path'], 'ppt/media/image2.WMF')
        self.assertEqual(self.source.read_bytes(), original)
        with zipfile.ZipFile(self.source) as before, zipfile.ZipFile(self.output) as after:
            for name in ['ppt/embeddings/oleObject1.bin', 'ppt/slides/slide1.xml', 'docProps/custom.xml', 'ppt/media/image2.WMF']:
                self.assertEqual(before.read(name), after.read(name))
            rels = ET.fromstring(after.read('ppt/slides/_rels/slide1.xml.rels'))
            by_id = {x.get('Id'): x for x in rels}
            self.assertTrue(by_id['im1'].get('Target').endswith('.png'))
            self.assertTrue(by_id['im2'].get('Target').endswith('.WMF'))
            self.assertEqual(by_id['ole1'].get('Target'), '../embeddings/oleObject1.bin')
            self.assertEqual(by_id['external'].get('Target'), 'https://example.com/image1.emf')
            self.assertIn('image/png', after.read('[Content_Types].xml').decode())

    def test_refuses_overwrite_and_same_path(self):
        with self.assertRaises(SlideBridgeError):
            repair(self.source, self.source)
        self.output.write_bytes(b'existing')
        with self.assertRaises(SlideBridgeError):
            repair(self.source, self.output)
        self.assertEqual(self.output.read_bytes(), b'existing')

    def test_missing_renderer_leaves_no_output(self):
        def which_no_resvg(cmd):
            if "emf2svg" in cmd:
                return "/mock/bin/emf2svg-conv"
            return None

        with patch('slidebridge.core.shutil.which', side_effect=which_no_resvg):
            with self.assertRaises(SlideBridgeError):
                repair(self.source, self.output)
        self.assertFalse(self.output.exists())

    @patch('slidebridge.core.subprocess.run', return_value=subprocess.CompletedProcess([], 1, '', 'bad metafile'))
    def test_conversion_failure_leaves_no_output(self, run):
        with self.assertRaises(SlideBridgeError):
            repair(self.source, self.output)
        self.assertFalse(self.output.exists())

    def test_success_without_second_image_is_failure(self):
        calls = []
        def once(command, **kwargs):
            calls.append(command)
            if "-i" in command and "-o" in command:
                out_svg = command[command.index("-o") + 1]
                Path(out_svg).write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"></svg>')
                return subprocess.CompletedProcess(command, 0, "", "")
            return subprocess.CompletedProcess(command, 0, '', '')
        with patch('slidebridge.core.subprocess.run', side_effect=once):
            with self.assertRaises(SlideBridgeError):
                repair(self.source, self.output)
        self.assertFalse(self.output.exists())

    def test_normal_picture_is_not_ole_preview(self):
        with zipfile.ZipFile(self.source) as z:
            entries = {n: z.read(n) for n in z.namelist()}
        entries['ppt/slides/slide1.xml'] = entries['ppt/slides/slide1.xml'].replace(
            b'</p:sld>', b'<p:pic><p:blipFill><a:blip r:embed="im2"/></p:blipFill></p:pic></p:sld>')
        with zipfile.ZipFile(self.source, 'w') as z:
            for n, data in entries.items():
                z.writestr(n, data)
        by_path = {x['path']: x for x in scan(self.source)['media']}
        self.assertFalse(by_path['ppt/media/image2.WMF']['ole_preview'])

    def test_emf_intermediate_backend_and_dimension_cap(self):
        calls = []
        def backend(command, **kwargs):
            calls.append(command)
            if '-i' in command:
                Path(command[command.index('-o') + 1]).write_text(
                    '<svg xmlns="http://www.w3.org/2000/svg" width="10201" height="1967"/>')
                return subprocess.CompletedProcess(command, 0, b'', b'')
            return renderer(command, **kwargs)
        with patch('slidebridge.core.subprocess.run', side_effect=backend):
            repair(self.source, self.output)
        self.assertEqual(len(calls), 2)
        resvg_calls = [c for c in calls if len(c) > 1 and c[1].endswith('.svg')]
        self.assertEqual(len(resvg_calls), 1)
        self.assertIn('--width', resvg_calls[0])
        self.assertIn('4096', resvg_calls[0])

    def test_vml_only_preview(self):
        with zipfile.ZipFile(self.source) as z:
            entries = {n: z.read(n) for n in z.namelist()}
        entries['ppt/slides/slide1.xml'] = b'<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><p:oleObj spid="shape1" r:id="ole1"><p:embed/></p:oleObj></p:sld>'
        rel = 'ppt/slides/_rels/slide1.xml.rels'
        entries[rel] = entries[rel].replace(b'</Relationships>', b'<Relationship Id="vml" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/vmlDrawing" Target="../drawings/drawing1.vml"/></Relationships>')
        entries['ppt/drawings/drawing1.vml'] = b'<xml xmlns:v="urn:schemas-microsoft-com:vml" xmlns:o="urn:schemas-microsoft-com:office:office"><v:shape id="shape1"><v:imagedata o:relid="preview"/></v:shape></xml>'
        entries['ppt/drawings/_rels/drawing1.vml.rels'] = f'<Relationships xmlns="{R}"><Relationship Id="preview" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="../media/image1.emf"/></Relationships>'
        with zipfile.ZipFile(self.source, 'w') as z:
            for n, data in entries.items():
                z.writestr(n, data)
        self.assertTrue(scan(self.source)['media'][0]['ole_preview'])

    @patch('slidebridge.core.subprocess.run', side_effect=renderer)
    def test_reference_png_is_embedded_exactly_and_shared(self, run):
        reference = self.source.parent / 'Windows original.png'
        reference.write_bytes(PNG)
        report = repair(self.source, self.output,
                        reference_previews={'ppt/media/image1.emf': reference, 'ppt/media/image2.WMF': reference})
        self.assertEqual(run.call_count, 0)  # Both use reference PNG.
        self.assertEqual(report['converted'][0]['method'], 'reference-png')
        self.assertEqual(report['converted'][1]['method'], 'reference-png')
        with zipfile.ZipFile(self.output) as z:
            self.assertEqual(z.read('ppt/media/image1.png'), PNG)
            self.assertEqual(z.read('ppt/media/image2.png'), PNG)
            self.assertEqual(z.read('ppt/embeddings/oleObject1.bin'), b'\x00Origin opaque OLE\xff')

    @patch('slidebridge.core.subprocess.run')
    def test_reference_validation_precedes_conversion(self, run):
        reference = self.source.parent / 'bad.png'
        reference.write_bytes(b'not a PNG')
        for member in ['ppt/media/missing.emf', 'ppt/media/image1.emf']:
            with self.assertRaises(SlideBridgeError):
                repair(self.source, self.output, reference_previews={member: reference})
        run.assert_not_called()
        self.assertFalse(self.output.exists())

    def test_invalid_zip(self):
        self.source.write_bytes(b'not a zip')
        with self.assertRaises(SlideBridgeError):
            scan(self.source)

    def test_cli_error_exit(self):
        with patch('sys.stderr'):
            self.assertEqual(main(['scan', str(self.source.parent / 'missing.pptx')]), 1)


    @patch('slidebridge.core.subprocess.run', side_effect=renderer)
    def test_concurrent_repair_matches_sequential(self, run):
        out_seq = self.source.parent / 'output_seq.pptx'
        out_par = self.source.parent / 'output_par.pptx'
        rep_seq = repair(self.source, out_seq, concurrency=1)
        rep_par = repair(self.source, out_par, concurrency=4)
        self.assertEqual(len(rep_seq['converted']), len(rep_par['converted']))
        self.assertTrue(out_seq.is_file())
        self.assertTrue(out_par.is_file())
        with zipfile.ZipFile(out_seq) as z1, zipfile.ZipFile(out_par) as z2:
            self.assertEqual(set(z1.namelist()), set(z2.namelist()))
            for name in z1.namelist():
                self.assertEqual(z1.read(name), z2.read(name))

    def test_concurrent_repair_failure_cleans_up(self):
        calls = []
        def fail_second(command, **kwargs):
            calls.append(command)
            if len(calls) == 1:
                return renderer(command, **kwargs)
            raise subprocess.CalledProcessError(1, command)

        with patch('slidebridge.core.subprocess.run', side_effect=fail_second):
            with self.assertRaises(SlideBridgeError):
                repair(self.source, self.output, concurrency=4)
        self.assertFalse(self.output.exists())

    def test_emf_conversion_chain_uses_resvg_and_skips_wmf(self):
        recorded_calls = []

        def fake_which(cmd):
            if "emf2svg" in cmd:
                return "/mock/bin/emf2svg-conv"
            if "resvg" in cmd:
                return "/mock/bin/resvg"
            return None

        def fake_run(cmd, **kwargs):
            recorded_calls.append(list(cmd))
            if "emf2svg-conv" in cmd[0]:
                out_svg = cmd[cmd.index("-o") + 1]
                Path(out_svg).write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"></svg>')
                return subprocess.CompletedProcess(cmd, 0, "", "")
            elif "resvg" in cmd[0]:
                out_png = cmd[2]
                Path(out_png).write_bytes(PNG)
                return subprocess.CompletedProcess(cmd, 0, "", "")
            return subprocess.CompletedProcess(cmd, 0, "", "")

        with patch('slidebridge.core.shutil.which', side_effect=fake_which), \
             patch('slidebridge.core.subprocess.run', side_effect=fake_run):
            report = repair(self.source, self.output)

        resvg_invocations = [c for c in recorded_calls if c and "resvg" in c[0]]
        # Image1 (EMF) should go through emf2svg-conv and then resvg
        self.assertTrue(any("intermediate.svg" in c[1] and "--dpi" in c for c in resvg_invocations))
        # Image2 (WMF) was skipped
        self.assertEqual(len(report.get('skipped', [])), 1)
        self.assertEqual(report['skipped'][0]['path'], 'ppt/media/image2.WMF')
        # No inkscape calls
        self.assertFalse(any("inkscape" in c[0] for c in recorded_calls))

    def test_resvg_obeys_4096_width_limit(self):
        recorded_calls = []

        def fake_which(cmd):
            if "emf2svg" in cmd:
                return "/mock/bin/emf2svg-conv"
            if "resvg" in cmd:
                return "/mock/bin/resvg"
            return None

        def fake_run(cmd, **kwargs):
            recorded_calls.append(list(cmd))
            if "emf2svg-conv" in cmd[0]:
                out_svg = cmd[cmd.index("-o") + 1]
                # viewBox 2000x1000 at 300 DPI: 2000 * 300 / 96 = 6250 > 4096 -> width 4096
                Path(out_svg).write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 2000 1000"></svg>')
                return subprocess.CompletedProcess(cmd, 0, "", "")
            elif "resvg" in cmd[0]:
                out_png = cmd[2]
                Path(out_png).write_bytes(PNG)
                return subprocess.CompletedProcess(cmd, 0, "", "")
            return subprocess.CompletedProcess(cmd, 0, "", "")

        with patch('slidebridge.core.shutil.which', side_effect=fake_which), \
             patch('slidebridge.core.subprocess.run', side_effect=fake_run):
            repair(self.source, self.output)

        resvg_invocations = [c for c in recorded_calls if c and "resvg" in c[0]]
        self.assertTrue(any("--width" in c and "4096" in c for c in resvg_invocations))

    def test_png_white_to_transparent_integration(self):
        rgba_sample = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAYAAABytg0kAAAAFElEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==')
        result = png_white_to_transparent(rgba_sample)
        self.assertEqual(len(result), len(rgba_sample))

    def test_cli_renderer_and_transparency_flags(self):
        recorded_calls = []

        def fake_run(cmd, **kwargs):
            recorded_calls.append(list(cmd))
            if "emf2svg-conv" in cmd[0]:
                out_svg = cmd[cmd.index("-o") + 1]
                Path(out_svg).write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"></svg>')
                return subprocess.CompletedProcess(cmd, 0, "", "")
            out_png = cmd[2]
            Path(out_png).write_bytes(PNG)
            return subprocess.CompletedProcess(cmd, 0, "", "")

        out = self.source.parent / "cli_out.pptx"
        with patch('slidebridge.core.subprocess.run', side_effect=fake_run):
            ret = main(['fix', str(self.source), '-o', str(out), '--renderer', '/custom/resvg', '--no-transparent'])
            self.assertEqual(ret or 0, 0)
        self.assertTrue(out.is_file())

    def test_cli_rejects_removed_inkscape_flag(self):
        with patch('sys.stderr'), self.assertRaises(SystemExit) as cm:
            main(['fix', str(self.source), '--inkscape', '/custom/inkscape'])
        self.assertEqual(cm.exception.code, 2)

    def test_repair_rejects_removed_inkscape_kwarg(self):
        with self.assertRaisesRegex(TypeError, "unexpected keyword argument"):
            repair(self.source, self.output, inkscape="/custom/legacy_inkscape")

    def test_repair_rejects_unknown_keywords(self):
        with self.assertRaisesRegex(TypeError, "unexpected keyword argument"):
            repair(self.source, self.output, transparant=False)
        self.assertFalse(self.output.exists())

    def test_missing_resvg_raises_repair_error(self):
        def which_no_resvg(cmd):
            if "emf2svg" in cmd:
                return "/mock/bin/emf2svg-conv"
            return None

        def fake_run(cmd, **kwargs):
            if "emf2svg-conv" in cmd[0]:
                out_svg = cmd[cmd.index("-o") + 1]
                Path(out_svg).write_text('<svg xmlns="http://www.w3.org/2000/svg"/>')
                return subprocess.CompletedProcess(cmd, 0, "", "")
            return subprocess.CompletedProcess(cmd, 0, "", "")

        with patch('slidebridge.core.shutil.which', side_effect=which_no_resvg), \
             patch('slidebridge.core.subprocess.run', side_effect=fake_run):
            with self.assertRaisesRegex(SlideBridgeError, "resvg executable not found"):
                repair(self.source, self.output)

    def test_emf_conversion_failure_includes_stderr_detail(self):
        def fake_run(cmd, **kwargs):
            if "emf2svg-conv" in cmd[0]:
                return subprocess.CompletedProcess(cmd, 1, "", "dyld: Library not loaded: @rpath/libemf2svg.1.dylib")
            return subprocess.CompletedProcess(cmd, 0, "", "")

        with patch('slidebridge.core.subprocess.run', side_effect=fake_run):
            with self.assertRaises(SlideBridgeError) as cm:
                repair(self.source, self.output)
            self.assertIn("EMF to SVG conversion failed for ppt/media/image1.emf", str(cm.exception))
            self.assertIn("dyld: Library not loaded: @rpath/libemf2svg.1.dylib", str(cm.exception))

    def test_emf_converter_fallback_on_broken_local_bin(self):
        def which_with_local(cmd):
            if cmd == "emf2svg-conv":
                return "/opt/homebrew/bin/emf2svg-conv"
            if "resvg" in cmd:
                return "/mock/bin/resvg"
            return "/repo/bin/emf2svg-conv"

        def fake_run(cmd, **kwargs):
            if cmd[0] == "/repo/bin/emf2svg-conv":
                return subprocess.CompletedProcess(cmd, -6, "", "dyld: Library not loaded")
            if "emf2svg-conv" in cmd[0]:
                out_svg = cmd[cmd.index("-o") + 1]
                Path(out_svg).write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"/>')
                return subprocess.CompletedProcess(cmd, 0, "", "")
            out_png = cmd[2]
            Path(out_png).write_bytes(PNG)
            return subprocess.CompletedProcess(cmd, 0, "", "")

        with patch('slidebridge.core.shutil.which', side_effect=which_with_local), \
             patch('slidebridge.core.subprocess.run', side_effect=fake_run):
            repair(self.source, self.output)
            self.assertTrue(self.output.is_file())


if __name__ == '__main__':
    unittest.main()
