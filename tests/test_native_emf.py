"""Opt-in tests exercising the actual native parser, not a fake renderer.

SLIDEBRIDGE_TEST_EMF2SVG=/path/to/emf2svg-conv python3 -m unittest discover -s tests
"""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET

from emf_fixture import pen_emf


@unittest.skipUnless(os.environ.get('SLIDEBRIDGE_TEST_EMF2SVG'), 'native backend not selected')
class NativePenTests(unittest.TestCase):
    def render(self, **kwargs):
        with tempfile.TemporaryDirectory() as directory:
            source, target = Path(directory) / 'pen.emf', Path(directory) / 'pen.svg'
            source.write_bytes(pen_emf(**kwargs))
            subprocess.run([os.environ['SLIDEBRIDGE_TEST_EMF2SVG'], '-i', str(source), '-o', str(target)],
                           capture_output=True, check=True, timeout=30)
            root = ET.parse(target).getroot()
            return [e for e in root.iter() if e.get('stroke-width')]

    def test_createpen_preserves_positive_logical_widths(self):
        for width in [1, 2, 13, 46]:
            with self.subTest(width=width):
                paths = self.render(width=width)
                self.assertTrue(paths)
                self.assertEqual(float(paths[0].get('stroke-width')), width)

    def test_zero_width_remains_hairline(self):
        self.assertEqual(float(self.render(width=0)[0].get('stroke-width')), 1)

    def test_extcreatepen_geometric_width_preserved(self):
        self.assertEqual(float(self.render(width=46, style=0x10000, extended=True)[0].get('stroke-width')), 46)

    def test_extcreatepen_cosmetic_stays_hairline(self):
        self.assertEqual(float(self.render(width=1, style=0, extended=True)[0].get('stroke-width')), 1)

    def test_createpen_wide_dash_normalized_to_solid(self):
        """Width 10 + PS_DASH (1) should render as solid width 10 per CreatePen."""
        paths = self.render(width=10, style=1)
        self.assertTrue(paths)
        self.assertEqual(float(paths[0].get('stroke-width')), 10)
        # Dash array must NOT be present after normalization.
        self.assertIsNone(paths[0].get('stroke-dasharray'))

    def test_createpen_width1_dash_stays_dashed(self):
        """Width 1 + PS_DASH should keep the dash pattern (no normalization)."""
        paths = self.render(width=1, style=1)
        self.assertTrue(paths)
        self.assertEqual(float(paths[0].get('stroke-width')), 1)
        self.assertIsNotNone(paths[0].get('stroke-dasharray'))


@unittest.skipUnless(os.environ.get('SLIDEBRIDGE_TEST_EMF2SVG'), 'native backend not selected')
class NativeTextTests(unittest.TestCase):
    def render_text(self, **kwargs):
        from emf_fixture import text_emf
        with tempfile.TemporaryDirectory() as directory:
            source, target = Path(directory) / 'text.emf', Path(directory) / 'text.svg'
            source.write_bytes(text_emf(**kwargs))
            subprocess.run([os.environ['SLIDEBRIDGE_TEST_EMF2SVG'], '-i', str(source), '-o', str(target)],
                           capture_output=True, check=True, timeout=30)
            root = ET.parse(target).getroot()
            return [e for e in root.iter() if e.tag.endswith('text')]

    def test_rotated_text_rotation_center_matches_coordinates(self):
        """Escapement 900 with TA_BASELINE must rotate around (x, y) with no extra translate."""
        elements = self.render_text(text="FE", escapement=900, align=0x18, x=100, y=200, height=-300)
        self.assertTrue(elements)
        text_el = elements[0]
        self.assertEqual(text_el.get('x'), '100.0000')
        self.assertEqual(text_el.get('y'), '200.0000')
        transform = text_el.get('transform', '')
        self.assertEqual(transform, 'rotate(-90, 100.0000, 200.0000)')
        self.assertNotIn('translate', transform)

    def test_rotated_subscript_superscript_keep_true_anchor(self):
        """Different font heights must not introduce differential offsets along or across baseline."""
        el_main = self.render_text(text="FE", escapement=900, align=0x18, x=500, y=1000, height=-738)[0]
        el_sub = self.render_text(text="2", escapement=900, align=0x18, x=500, y=800, height=-181)[0]
        self.assertEqual(el_main.get('transform'), 'rotate(-90, 500.0000, 1000.0000)')
        self.assertEqual(el_sub.get('transform'), 'rotate(-90, 500.0000, 800.0000)')

    def test_unrotated_text_has_no_transform(self):
        """Escapement 0 text should have no transform attribute."""
        elements = self.render_text(text="Normal", escapement=0, align=0x18, x=100, y=200, height=-300)
        self.assertTrue(elements)
        self.assertIsNone(elements[0].get('transform'))


@unittest.skipUnless(os.environ.get('SLIDEBRIDGE_TEST_EMF2SVG'), 'native backend not selected')
class NativeRasterAndPatternTests(unittest.TestCase):
    def render_emf(self, emf_bytes):
        with tempfile.TemporaryDirectory() as directory:
            source, target = Path(directory) / 'test.emf', Path(directory) / 'test.svg'
            source.write_bytes(emf_bytes)
            subprocess.run([os.environ['SLIDEBRIDGE_TEST_EMF2SVG'], '-i', str(source), '-o', str(target)],
                           capture_output=True, check=True, timeout=30)
            return ET.parse(target).getroot()

    def test_bitblt_patinvert_suppressed(self):
        """PATINVERT (0x005A0049) blits used for Win32 GDI XOR bracketing must not render opaque blocker paths."""
        from emf_fixture import bitblt_emf
        root = self.render_emf(bitblt_emf(dwRop=0x005A0049))
        paths = [e for e in root.iter() if e.tag.endswith('path')]
        self.assertEqual(len(paths), 0)

    def test_bitblt_dstinvert_suppressed(self):
        """DSTINVERT (0x00550009) inverting blits must not render opaque blocker paths."""
        from emf_fixture import bitblt_emf
        root = self.render_emf(bitblt_emf(dwRop=0x00550009))
        paths = [e for e in root.iter() if e.tag.endswith('path')]
        self.assertEqual(len(paths), 0)

    def test_bitblt_patcopy_rendered(self):
        """Standard PATCOPY (0x00F00021) pattern blits must render filled rectangle paths."""
        from emf_fixture import bitblt_emf
        root = self.render_emf(bitblt_emf(dwRop=0x00F00021))
        paths = [e for e in root.iter() if e.tag.endswith('path')]
        self.assertEqual(len(paths), 1)

    def test_monopattern_renders_semitransparent_vector_fill(self):
        """1-bpp monochrome stipple patterns with DC brush color render semi-transparent vector fill."""
        from emf_fixture import monopattern_emf
        root = self.render_emf(monopattern_emf(0x93, 0xBC, 0x93))
        paths = [e for e in root.iter() if e.tag.endswith('path')]
        self.assertTrue(paths)
        self.assertEqual(paths[0].get('fill'), '#93BC93')
        self.assertEqual(paths[0].get('fill-opacity'), '0.55')

    def test_monopattern_black_renders_stipple_opacity(self):
        """1-bpp monochrome stipple patterns with black DC brush render 50% opacity matching GDI dithering."""
        from emf_fixture import monopattern_emf
        root = self.render_emf(monopattern_emf(0, 0, 0))
        paths = [e for e in root.iter() if e.tag.endswith('path')]
        self.assertTrue(paths)
        self.assertEqual(paths[0].get('fill'), '#000000')
        self.assertEqual(paths[0].get('fill-opacity'), '0.50')

