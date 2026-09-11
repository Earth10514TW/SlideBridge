import unittest
from slidebridge.svg_cleaner import optimize_emf_svg


class TestSvgCleaner(unittest.TestCase):
    def test_empty_or_none(self):
        self.assertEqual(optimize_emf_svg(""), "")

    def test_preserves_authentic_font_weight(self):
        svg = '<text font-family="Arial" font-weight="700" font-size="266">Binding Energy</text>'
        cleaned = optimize_emf_svg(svg)
        self.assertIn('font-weight="700"', cleaned)
        self.assertNotIn('font-weight="normal"', cleaned)

    def test_preserves_authentic_stroke_widths(self):
        svg = (
            '<path stroke-width="42.0000" stroke="#000000" />'
            '<path stroke-width="33.0000" stroke="#C8E997" />'
            '<path stroke-width="21.0000" stroke="#000000" />'
            '<path stroke-width="14.0000" stroke="#000000" />'
        )
        cleaned = optimize_emf_svg(svg)
        self.assertIn('stroke-width="42.0000"', cleaned)
        self.assertIn('stroke-width="33.0000"', cleaned)
        self.assertIn('stroke-width="21.0000"', cleaned)
        self.assertIn('stroke-width="14.0000"', cleaned)

    def test_baseline_stroke_cleanup(self):
        svg = (
            '<path d="M 10 10 L 20 20 Z" stroke-width="1px" stroke="#C8E997" fill="#C8E997" fill-opacity="0.55" />\n'
            '<path d="M 0 0 L 100 0" stroke-width="1px" stroke="#C8E997" fill="none" />\n'
        )
        cleaned = optimize_emf_svg(svg)
        # Stroke on filled polygon stripped to stroke="none"
        self.assertIn('stroke="none" fill="#C8E997"', cleaned)
        # Redundant unclosed stroke line removed
        self.assertNotIn('fill="none"', cleaned)


if __name__ == "__main__":
    unittest.main()
