import base64
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import subprocess
import zipfile
import xml.etree.ElementTree as ET

from slidebridge.core import scan, repair, SlideBridgeError
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
    target = next(str(x).split('=', 1)[1] for x in command if str(x).startswith('--export-filename='))
    Path(target).write_bytes(PNG)
    return subprocess.CompletedProcess(command, 0, '', '')


class CoreTests(unittest.TestCase):
    def setUp(self):
        discovery = patch('slidebridge.core.shutil.which', return_value=None)
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
        self.assertEqual(len(result['converted']), 2)
        self.assertEqual(self.source.read_bytes(), original)
        with zipfile.ZipFile(self.source) as before, zipfile.ZipFile(self.output) as after:
            for name in ['ppt/embeddings/oleObject1.bin', 'ppt/slides/slide1.xml', 'docProps/custom.xml']:
                self.assertEqual(before.read(name), after.read(name))
            rels = ET.fromstring(after.read('ppt/slides/_rels/slide1.xml.rels'))
            by_id = {x.get('Id'): x for x in rels}
            self.assertTrue(by_id['im1'].get('Target').endswith('.png'))
            self.assertTrue(by_id['im2'].get('Target').endswith('.png'))
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

    @patch('slidebridge.core.subprocess.run', side_effect=FileNotFoundError('missing renderer'))
    def test_missing_renderer_leaves_no_output(self, run):
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
            if len(calls) == 1:
                return renderer(command, **kwargs)
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
        with patch('slidebridge.core.shutil.which', return_value='/fake/emf2svg-conv'):
            with patch('slidebridge.core.subprocess.run', side_effect=backend):
                repair(self.source, self.output)
        self.assertEqual(len(calls), 3)
        self.assertTrue(calls[1][1].endswith('.svg'))
        self.assertIn('--export-width=4096', calls[1])

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

    def test_invalid_zip(self):
        self.source.write_bytes(b'not a zip')
        with self.assertRaises(SlideBridgeError):
            scan(self.source)

    def test_cli_error_exit(self):
        with patch('sys.stderr'):
            self.assertEqual(main(['scan', str(self.source.parent / 'missing.pptx')]), 1)


if __name__ == '__main__':
    unittest.main()
