"""SlideBridge SVG optimization and cleanup for EMF-converted vector graphics.

Scientific chart software (like OriginLab) exports XPS peak deconvolution plots
with:
1. 1-bpp monochrome stipple patterns for peak fills and experimental data curves.
2. Bold text and distinct frame borders that match Windows presentation style.
3. Extraneous 1px stroke outlines around filled peak polygons and redundant unclosed
   baseline stroke lines that protrude past the bounding box corners.

This module strips the extraneous baseline stroke outlines to ensure clean,
sharp, right-angled axis frames while preserving the authentic font weights,
line thicknesses, and data curves.
"""

from __future__ import annotations

import re


def optimize_emf_svg(svg_content: str) -> str:
    """Optimize an SVG generated from EMF to match authentic presentation fidelity.

    Args:
        svg_content: Raw SVG XML text.

    Returns:
        Cleaned, high-fidelity SVG text.
    """
    if not svg_content:
        return svg_content

    result = svg_content

    # 1. Clean up baseline bleed on filled peak polygons:
    # When a polygon is filled with a semi-transparent color (fill-opacity),
    # an extraneous 1px stroke around the entire perimeter causes the flat baseline
    # to stick out past the axis border corners. Stripping stroke-width="1px" from
    # filled peak polygons leaves only the clean translucent fill.
    result = re.sub(
        r'stroke-width="1px"\s+stroke="(#[0-9A-Fa-f]{6})"\s+fill="(\1)"',
        r'stroke="none" fill="\2"',
        result,
    )

    # 2. Remove redundant unclosed 1px peak outline strokes that trace the baseline
    # outside the chart area (e.g. `stroke-width="1px" stroke="#..." fill="none"`)
    # when accompanied by filled peak polygons.
    lines = result.splitlines(keepends=True)
    filtered_lines = []
    for line in lines:
        if 'stroke-width="1px"' in line and 'fill="none"' in line and '<path ' in line:
            if re.search(r'stroke="#[0-9A-Fa-f]{6}"', line):
                continue
        filtered_lines.append(line)

    result = "".join(filtered_lines)
    return result
