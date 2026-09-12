from pathlib import Path
import tempfile
import unittest
import zipfile
from unittest.mock import patch

import slidebridge.bridge as bridge
from slidebridge.bridge import list_ole_objects


REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
OLE_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/oleObject"
IMAGE_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image"


def cfb_payload(size: int = 512, marker: int = 0) -> bytes:
    data = bytearray(size)
    data[:8] = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
    data[24:32] = marker.to_bytes(8, "little")
    return bytes(data)


def preview_payload(marker: bytes) -> bytes:
    return b"\x89PNG\r\n\x1a\n" + marker


def make_package(path: Path) -> None:
    slide_template = (
        '<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        "{objects}</p:sld>"
    )
    slide1 = slide_template.format(
        objects=(
            '<p:oleObj r:id="ole1"><p:pic><p:blipFill><p:blip r:embed="img1"/>'
            "</p:blipFill></p:pic></p:oleObj>"
            '<p:oleObj r:id="ole2"><p:pic><p:blipFill><p:blip r:embed="img2"/>'
            "</p:blipFill></p:pic></p:oleObj>"
        )
    ).encode()
    slide2 = slide_template.format(
        objects=(
            '<p:oleObj r:id="ole1"><p:pic><p:blipFill><p:blip r:embed="img1"/>'
            "</p:blipFill></p:pic></p:oleObj>"
            '<p:oleObj r:id="external"/>'
        )
    ).encode()
    rels1 = (
        f'<Relationships xmlns="{REL_NS}">'
        f'<Relationship Id="ole1" Type="{OLE_REL}" Target="../embeddings/object1.bin"/>'
        f'<Relationship Id="ole2" Type="{OLE_REL}" Target="../embeddings/object2.bin"/>'
        f'<Relationship Id="img1" Type="{IMAGE_REL}" Target="../media/image1.png"/>'
        f'<Relationship Id="img2" Type="{IMAGE_REL}" Target="../media/image2.png"/>'
        "</Relationships>"
    ).encode()
    rels2 = (
        f'<Relationships xmlns="{REL_NS}">'
        f'<Relationship Id="ole1" Type="{OLE_REL}" Target="../embeddings/object1.bin"/>'
        f'<Relationship Id="img1" Type="{IMAGE_REL}" Target="../media/image1.png"/>'
        f'<Relationship Id="external" Type="{OLE_REL}" Target="https://example.invalid/object.bin" TargetMode="External"/>'
        "</Relationships>"
    ).encode()
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("ppt/slides/slide1.xml", slide1)
        archive.writestr("ppt/slides/_rels/slide1.xml.rels", rels1)
        archive.writestr("ppt/slides/slide2.xml", slide2)
        archive.writestr("ppt/slides/_rels/slide2.xml.rels", rels2)
        archive.writestr("ppt/embeddings/object1.bin", cfb_payload(marker=1))
        archive.writestr("ppt/embeddings/object2.bin", cfb_payload(marker=2))
        archive.writestr("ppt/embeddings/unreferenced.bin", cfb_payload(marker=3))
        archive.writestr("ppt/embeddings/external.bin", cfb_payload(marker=4))
        archive.writestr("ppt/embeddings/not-ole.bin", b"ordinary payload")
        archive.writestr("ppt/media/image1.png", preview_payload(b"one"))
        archive.writestr("ppt/media/image2.png", preview_payload(b"two"))


class _TrackedReader:
    def __init__(self, reader, reads):
        self._reader = reader
        self._reads = reads

    def read(self, size=-1):
        self._reads.append(size)
        return self._reader.read(size)

    def __enter__(self):
        self._reader.__enter__()
        return self

    def __exit__(self, *args):
        return self._reader.__exit__(*args)


class _TrackedArchive:
    def __init__(self, archive):
        self._archive = archive
        self.open_reads = []
        self.read_names = []

    def infolist(self):
        return self._archive.infolist()

    def open(self, info):
        reads = []
        self.open_reads.append((info.filename, reads))
        return _TrackedReader(self._archive.open(info), reads)

    def read(self, name):
        self.read_names.append(name.filename if isinstance(name, zipfile.ZipInfo) else name)
        return self._archive.read(name)

    def close(self):
        return self._archive.close()


class ListOleObjectsTests(unittest.TestCase):
    def test_indexes_references_once_and_filters_members(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "input.pptx"
            make_package(path)
            objects = list_ole_objects(path)

        self.assertEqual([item["member"] for item in objects], [
            "ppt/embeddings/object1.bin",
            "ppt/embeddings/object2.bin",
        ])
        self.assertEqual(objects[0]["slides"], [
            "ppt/slides/slide1.xml",
            "ppt/slides/slide2.xml",
        ])
        self.assertEqual(objects[0]["previews"], ["ppt/media/image1.png"])
        self.assertEqual(objects[0]["bytes"], 512)
        self.assertEqual(objects[0]["references"], [
            {"slide": "ppt/slides/slide1.xml", "relationship_id": "ole1"},
            {"slide": "ppt/slides/slide2.xml", "relationship_id": "ole1"},
        ])
        self.assertEqual(objects[1]["slides"], ["ppt/slides/slide1.xml"])
        self.assertEqual(objects[1]["previews"], ["ppt/media/image2.png"])
        self.assertEqual(objects[1]["references"], [
            {"slide": "ppt/slides/slide1.xml", "relationship_id": "ole2"},
        ])

    def test_ole_members_are_checked_with_prefix_reads_and_index_reads_parts_once(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "input.pptx"
            make_package(path)
            tracked = []
            original_check_archive = bridge._check_archive

            def checked(source):
                archive = original_check_archive(source)
                wrapper = _TrackedArchive(archive)
                tracked.append(wrapper)
                return wrapper

            with patch.object(bridge, "_check_archive", checked):
                objects = list_ole_objects(path)

        self.assertEqual(len(objects), 2)
        archive = tracked[0]
        self.assertEqual(
            [(name, reads) for name, reads in archive.open_reads],
            [
                ("ppt/embeddings/external.bin", [8]),
                ("ppt/embeddings/not-ole.bin", [8]),
                ("ppt/embeddings/object1.bin", [8]),
                ("ppt/embeddings/object2.bin", [8]),
                ("ppt/embeddings/unreferenced.bin", [8]),
            ],
        )
        self.assertEqual(
            archive.read_names.count("ppt/slides/slide1.xml"),
            3,
        )
        self.assertEqual(
            archive.read_names.count("ppt/slides/slide2.xml"),
            2,
        )

    def test_malformed_slide_skips_all_objects(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "input.pptx"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("ppt/slides/slide1.xml", b"<p:sld>")
                archive.writestr("ppt/slides/_rels/slide1.xml.rels", b"<Relationships/>")
                archive.writestr("ppt/embeddings/object1.bin", cfb_payload())

            self.assertEqual(list_ole_objects(path), [])

    def test_malformed_relationships_skip_all_objects(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "input.pptx"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr(
                    "ppt/slides/slide1.xml",
                    '<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
                    'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
                    '<p:oleObj r:id="ole1"/></p:sld>',
                )
                archive.writestr(
                    "ppt/slides/_rels/slide1.xml.rels",
                    b"<Relationships>",
                )
                archive.writestr("ppt/embeddings/object1.bin", cfb_payload())

            self.assertEqual(list_ole_objects(path), [])


if __name__ == "__main__":
    unittest.main()
