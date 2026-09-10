import unittest
import zipfile
from unittest.mock import patch
import test_core
from slidebridge.core import repair
from scripts.verify_package import verify


class VerifyTests(unittest.TestCase):
    setUp = test_core.CoreTests.setUp
    @patch('slidebridge.core.subprocess.run', side_effect=test_core.renderer)
    def test_verifier_rejects_tampered_relationships(self, run):
        repair(self.source, self.output)
        self.assertTrue(verify(self.source, self.output)['passed'])
        with zipfile.ZipFile(self.output) as z:
            entries = {n: z.read(n) for n in z.namelist()}
        rel = 'ppt/slides/_rels/slide1.xml.rels'
        mutations = [
            {rel: entries[rel].replace(b'../media/image1.png', b'../media/missing.png')},
            {rel: entries[rel].replace(b'Id="im1"', b'Id="tampered"')},
        ]
        for mutation in mutations:
            with zipfile.ZipFile(self.output, 'w') as z:
                for n, data in entries.items():
                    z.writestr(n, mutation.get(n, data))
            self.assertFalse(verify(self.source, self.output)['passed'])
        with zipfile.ZipFile(self.output, 'w') as z:
            for n, data in entries.items():
                if n != 'ppt/media/image1.png':
                    z.writestr(n, data)
        self.assertFalse(verify(self.source, self.output)['passed'])


if __name__ == '__main__':
    unittest.main()
