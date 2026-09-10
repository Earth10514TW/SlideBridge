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
