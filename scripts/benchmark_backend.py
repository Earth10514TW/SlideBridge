#!/usr/bin/env python3
"""Reproducible synthetic backend timings; no renderer or Windows VM required."""

import gc
import hashlib
import json
from pathlib import Path
import statistics
import sys
import tempfile
import time
import tracemalloc
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from slidebridge.bridge import list_ole_objects
from slidebridge.core import repair
import slidebridge.core as core


def make_deck(path, count, ole_bytes, media_bytes=0):
    rel_ns = "http://schemas.openxmlformats.org/package/2006/relationships"
    office_ns = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    cfb = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"x" * (ole_bytes - 8)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr("[Content_Types].xml",
                         '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
        archive.writestr("ppt/presentation.xml", "<presentation/>")
        for index in range(count):
            archive.writestr(
                f"ppt/slides/slide{index}.xml",
                f'<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
                f'xmlns:r="{office_ns}" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
                '<p:oleObj r:id="ole1"><p:pic><a:blip r:embed="img1"/></p:pic></p:oleObj></p:sld>',
            )
            archive.writestr(
                f"ppt/slides/_rels/slide{index}.xml.rels",
                f'<Relationships xmlns="{rel_ns}"><Relationship Id="ole1" '
                f'Type="{office_ns}/oleObject" Target="../embeddings/object{index}.bin"/>'
                f'<Relationship Id="img1" Type="{office_ns}/image" '
                'Target="../media/preview.png"/></Relationships>',
            )
            archive.writestr(f"ppt/embeddings/object{index}.bin", cfb)
        archive.writestr("ppt/media/preview.png", b"unchanged preview")
        if media_bytes:
            with archive.open("ppt/media/video.bin", "w") as media:
                block = bytes(range(256)) * 4096
                remaining = media_bytes
                while remaining:
                    chunk = block[:min(len(block), remaining)]
                    media.write(chunk)
                    remaining -= len(chunk)


def measure(operation, repeats=3):
    durations = []
    for _ in range(repeats):
        started = time.perf_counter()
        operation()
        durations.append(time.perf_counter() - started)
    gc.collect()
    tracemalloc.start()
    try:
        operation()
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    return {"median_seconds": round(statistics.median(durations), 4),
            "peak_python_mib": round(peak / 1024**2, 2)}


def main():
    with tempfile.TemporaryDirectory(prefix="slidebridge-benchmark-") as temporary:
        root = Path(temporary)
        listing = root / "many-objects.pptx"
        large = root / "large-media.pptx"
        batch = root / "many-metafiles.pptx"
        make_deck(listing, count=80, ole_bytes=128 * 1024)
        make_deck(large, count=1, ole_bytes=512, media_bytes=32 * 1024**2)
        with zipfile.ZipFile(batch, "w") as archive:
            payload = bytes(range(256)) * 8192
            for index in range(24):
                archive.writestr(f"ppt/media/image{index}.emf", payload)
        del payload

        def repair_large():
            output = root / "output.pptx"
            try:
                repair(large, output)
            finally:
                output.unlink(missing_ok=True)

        def render_stub(idx, source, output, data, *args, **kwargs):
            # Exercise input lifetime and worker scheduling without a renderer.
            png = hashlib.sha256(data).digest()
            return source, output, png, {"source": source}

        def convert_batch():
            with zipfile.ZipFile(batch) as archive:
                with patch.object(core, "_convert_single_item", render_stub):
                    core._convert_media(
                        archive, archive.infolist(), set(archive.namelist()),
                        300, str(root), {}, concurrency=2,
                    )

        print(json.dumps({
            "listing_80_objects_128_kib_each": measure(lambda: list_ole_objects(listing)),
            "repair_32_mib_unchanged_media": measure(repair_large),
            "queue_24_metafiles_2_mib_each_2_workers": measure(convert_batch),
            "notes": "Median of 3 timed runs; Python allocation peak measured separately. "
                     "Synthetic stored ZIPs; listing/repair include CRC validation. "
                     "Queue benchmark uses a hashing stub and excludes CRC validation. "
                     "All benchmarks exclude rendering and VM.",
        }, indent=2))


if __name__ == "__main__":
    main()
