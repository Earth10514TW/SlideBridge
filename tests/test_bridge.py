import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from slidebridge.bridge import prepare_ole, writeback_ole
from slidebridge.core import SlideBridgeError


REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
OLE_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/oleObject"
IMAGE_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image"
VML_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/vmlDrawing"


def cfb_payload(variant: int = 0) -> bytes:
    data = bytearray(512)
    data[:8] = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
    data[24:32] = (0x0003003E + variant).to_bytes(8, "little")
    return bytes(data)


def minimal_png(width: int = 10, height: int = 10, tag: bytes = b"") -> bytes:
    data = bytearray(24)
    data[:8] = b"\x89PNG\r\n\x1a\n"
    data[16:20] = width.to_bytes(4, "big")
    data[20:24] = height.to_bytes(4, "big")
    return bytes(data) + tag


def minimal_emf(tag: bytes = b"") -> bytes:
    data = bytearray(88)
    data[0:4] = (1).to_bytes(4, "little")
    data[4:8] = (88).to_bytes(4, "little")
    data[40:44] = b" EMF"
    return bytes(data) + tag


def package(path: Path, ole: bytes, *, target: str = "../embeddings/object1.bin",
            target_mode: str | None = None, slide_ole_id: str = "ole1") -> bytes:
    slide = (
        '<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f'<p:oleObj r:id="{slide_ole_id}"/></p:sld>'
    ).encode()
    mode = f' TargetMode="{target_mode}"' if target_mode else ""
    rels = (
        f'<Relationships xmlns="{REL_NS}"><Relationship Id="ole1" Type="{OLE_REL}" '
        f'Target="{target}"{mode}/></Relationships>'
    ).encode()
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("ppt/slides/slide1.xml", slide)
        archive.writestr("ppt/slides/_rels/slide1.xml.rels", rels)
        archive.writestr("ppt/embeddings/object1.bin", ole)
    return path.read_bytes()


def package_with_preview(
    path: Path,
    ole: bytes,
    preview: bytes,
    preview_name: str = "image1.png",
    *,
    spid: str = "_x0000_s1025",
) -> bytes:
    slide = (
        '<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
        'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f'<p:oleObj r:id="ole1" spid="{spid}">'
        '<p:pic><p:blipFill><a:blip r:embed="img1"/></p:blipFill></p:pic>'
        '</p:oleObj></p:sld>'
    ).encode()
    rels = (
        f'<Relationships xmlns="{REL_NS}">'
        f'<Relationship Id="ole1" Type="{OLE_REL}" Target="../embeddings/object1.bin"/>'
        f'<Relationship Id="img1" Type="{IMAGE_REL}" Target="../media/{preview_name}"/>'
        f'</Relationships>'
    ).encode()
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("ppt/slides/slide1.xml", slide)
        archive.writestr("ppt/slides/_rels/slide1.xml.rels", rels)
        archive.writestr("ppt/embeddings/object1.bin", ole)
        archive.writestr(f"ppt/media/{preview_name}", preview)
        archive.writestr("[Content_Types].xml", b'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
    return path.read_bytes()


class PrepareOleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "input.pptx"
        self.destination = self.root / "prepared"

    def test_success_copies_opaque_bytes_and_writes_hash_manifest(self):
        original = package(self.source, cfb_payload())
        result = prepare_ole(self.source, "ppt/embeddings/object1.bin", self.destination)

        self.assertEqual(self.source.read_bytes(), original)
        self.assertEqual((self.destination / "original.bin").read_bytes(), cfb_payload())
        self.assertEqual(
            (self.destination / "original.bin").read_bytes(),
            (self.destination / "editable.bin").read_bytes(),
        )
        manifest = json.loads((self.destination / "manifest.json").read_text())
        self.assertEqual(manifest, {key: result[key] for key in manifest})
        self.assertEqual(manifest["schema_version"], 1)
        self.assertEqual(manifest["source"], str(self.source.absolute()))
        self.assertEqual(manifest["source_sha256"], hashlib.sha256(original).hexdigest())
        self.assertEqual(manifest["ole_sha256"], hashlib.sha256(cfb_payload()).hexdigest())
        self.assertEqual(manifest["member"], "ppt/embeddings/object1.bin")
        self.assertEqual(manifest["references"], [{"slide": "ppt/slides/slide1.xml", "relationship_id": "ole1"}])

    def test_rejects_traversal_before_creating_output(self):
        package(self.source, cfb_payload())
        with self.assertRaises(SlideBridgeError):
            prepare_ole(self.source, "ppt/embeddings/../object1.bin", self.destination)
        self.assertFalse(self.destination.exists())

    def test_rejects_unreferenced_member_and_cleans_partial_output(self):
        package(self.source, cfb_payload(), slide_ole_id="other")
        with self.assertRaises(SlideBridgeError):
            prepare_ole(self.source, "ppt/embeddings/object1.bin", self.destination)
        self.assertFalse(self.destination.exists())

    def test_rejects_external_relationship_and_cleans_partial_output(self):
        package(self.source, cfb_payload(), target="https://example.test/object1.bin", target_mode="External")
        with self.assertRaises(SlideBridgeError):
            prepare_ole(self.source, "ppt/embeddings/object1.bin", self.destination)
        self.assertFalse(self.destination.exists())

    def test_rejects_non_cfb_and_short_header(self):
        package(self.source, b"not a compound file")
        with self.assertRaises(SlideBridgeError):
            prepare_ole(self.source, "ppt/embeddings/object1.bin", self.destination)
        self.assertFalse(self.destination.exists())

        package(self.source, b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"x" * 100)
        with self.assertRaises(SlideBridgeError):
            prepare_ole(self.source, "ppt/embeddings/object1.bin", self.destination)
        self.assertFalse(self.destination.exists())

    def test_existing_destination_is_never_modified(self):
        package(self.source, cfb_payload())
        self.destination.mkdir()
        marker = self.destination / "keep.txt"
        marker.write_text("keep")
        with self.assertRaises(SlideBridgeError):
            prepare_ole(self.source, "ppt/embeddings/object1.bin", self.destination)
        self.assertEqual(marker.read_text(), "keep")


class WritebackOleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "input.pptx"
        self.session = self.root / "session"
        self.output = self.root / "output.pptx"

    def test_prepare_ole_discovers_preview_members(self):
        orig_ole = cfb_payload(0)
        orig_preview = minimal_png(10, 10)
        package_with_preview(self.source, orig_ole, orig_preview)

        result = prepare_ole(self.source, "ppt/embeddings/object1.bin", self.session)
        self.assertEqual(result["preview_members"], ["ppt/media/image1.png"])
        manifest = json.loads((self.session / "manifest.json").read_text())
        self.assertEqual(manifest["preview_members"], ["ppt/media/image1.png"])

    def test_writeback_success_pairs_ole_and_preview(self):
        orig_ole = cfb_payload(0)
        orig_preview = minimal_png(10, 10)
        orig_bytes = package_with_preview(self.source, orig_ole, orig_preview)

        prepare_ole(self.source, "ppt/embeddings/object1.bin", self.session)

        edited_ole = cfb_payload(99)
        new_preview = minimal_png(20, 20, tag=b"new-preview-data")
        (self.session / "edited.bin").write_bytes(edited_ole)
        (self.session / "preview.png").write_bytes(new_preview)

        report = writeback_ole(self.source, self.session, self.output)

        self.assertEqual(report["status"], "success")
        self.assertEqual(report["member"], "ppt/embeddings/object1.bin")
        self.assertEqual(report["ole_sha256_after"], hashlib.sha256(edited_ole).hexdigest())
        self.assertEqual(report["preview_sha256"], hashlib.sha256(new_preview).hexdigest())

        # Source is completely unchanged
        self.assertEqual(self.source.read_bytes(), orig_bytes)

        # Output presentation contains new OLE and new preview
        with zipfile.ZipFile(self.output, "r") as archive:
            self.assertEqual(archive.read("ppt/embeddings/object1.bin"), edited_ole)
            self.assertEqual(archive.read("ppt/media/image1.png"), new_preview)

    def test_writeback_rejects_missing_preview(self):
        orig_ole = cfb_payload(0)
        orig_preview = minimal_png(10, 10)
        package_with_preview(self.source, orig_ole, orig_preview)

        prepare_ole(self.source, "ppt/embeddings/object1.bin", self.session)
        (self.session / "edited.bin").write_bytes(cfb_payload(1))

        with self.assertRaises(SlideBridgeError) as ctx:
            writeback_ole(self.source, self.session, self.output)
        self.assertIn("paired writeback requires a preview image", str(ctx.exception).lower())
        self.assertFalse(self.output.exists())

    def test_writeback_rejects_source_hash_mismatch(self):
        orig_ole = cfb_payload(0)
        orig_preview = minimal_png(10, 10)
        package_with_preview(self.source, orig_ole, orig_preview)

        prepare_ole(self.source, "ppt/embeddings/object1.bin", self.session)
        (self.session / "edited.bin").write_bytes(cfb_payload(1))
        (self.session / "preview.png").write_bytes(minimal_png(20, 20))

        # Tamper with source presentation
        self.source.write_bytes(self.source.read_bytes() + b"\x00")

        with self.assertRaises(SlideBridgeError) as ctx:
            writeback_ole(self.source, self.session, self.output)
        self.assertIn("source presentation has been modified", str(ctx.exception).lower())
        self.assertFalse(self.output.exists())

        # Force bypasses the check
        report = writeback_ole(self.source, self.session, self.output, force=True)
        self.assertEqual(report["status"], "success")
        self.assertTrue(self.output.exists())

    def test_writeback_rejects_ole_member_hash_mismatch(self):
        orig_ole = cfb_payload(0)
        orig_preview = minimal_png(10, 10)
        package_with_preview(self.source, orig_ole, orig_preview)

        prepare_ole(self.source, "ppt/embeddings/object1.bin", self.session)
        (self.session / "edited.bin").write_bytes(cfb_payload(1))
        (self.session / "preview.png").write_bytes(minimal_png(20, 20))

        # Repackage source with different OLE payload
        package_with_preview(self.source, cfb_payload(55), orig_preview)
        # Update manifest source_sha256 so conflict check 1 passes and conflict check 2 triggers
        manifest = json.loads((self.session / "manifest.json").read_text())
        manifest["source_sha256"] = hashlib.sha256(self.source.read_bytes()).hexdigest()
        (self.session / "manifest.json").write_text(json.dumps(manifest))

        with self.assertRaises(SlideBridgeError) as ctx:
            writeback_ole(self.source, self.session, self.output, force=False)
        self.assertIn("ole member in presentation has been modified", str(ctx.exception).lower())
        self.assertFalse(self.output.exists())

    def test_writeback_rejects_invalid_cfb(self):
        orig_ole = cfb_payload(0)
        orig_preview = minimal_png(10, 10)
        package_with_preview(self.source, orig_ole, orig_preview)

        prepare_ole(self.source, "ppt/embeddings/object1.bin", self.session)
        (self.session / "edited.bin").write_bytes(b"invalid cfb bytes")
        (self.session / "preview.png").write_bytes(minimal_png(20, 20))

        with self.assertRaises(SlideBridgeError) as ctx:
            writeback_ole(self.source, self.session, self.output)
        self.assertIn("compound file", str(ctx.exception).lower())
        self.assertFalse(self.output.exists())

    def test_writeback_atomic_output_safety(self):
        orig_ole = cfb_payload(0)
        orig_preview = minimal_png(10, 10)
        package_with_preview(self.source, orig_ole, orig_preview)

        prepare_ole(self.source, "ppt/embeddings/object1.bin", self.session)
        (self.session / "edited.bin").write_bytes(cfb_payload(1))
        (self.session / "preview.png").write_bytes(minimal_png(20, 20))

        # Output already exists
        self.output.write_text("already here")
        with self.assertRaises(SlideBridgeError) as ctx:
            writeback_ole(self.source, self.session, self.output)
        self.assertIn("output already exists", str(ctx.exception).lower())
        self.assertEqual(self.output.read_text(), "already here")

        # Source == Output
        with self.assertRaises(SlideBridgeError) as ctx:
            writeback_ole(self.source, self.session, self.source)
        self.assertIn("different paths", str(ctx.exception).lower())

    def test_writeback_replaces_emf_with_png_and_updates_relationships(self):
        orig_ole = cfb_payload(0)
        orig_preview = minimal_emf()
        package_with_preview(self.source, orig_ole, orig_preview, preview_name="image1.emf")

        prepare_ole(self.source, "ppt/embeddings/object1.bin", self.session)

        edited_ole = cfb_payload(42)
        new_png = minimal_png(30, 30, tag=b"png-from-user")
        (self.session / "edited.bin").write_bytes(edited_ole)
        (self.session / "preview.png").write_bytes(new_png)

        report = writeback_ole(self.source, self.session, self.output)
        self.assertEqual(report["status"], "success")

        with zipfile.ZipFile(self.output, "r") as archive:
            # New PNG preview exists
            self.assertEqual(archive.read("ppt/media/image1.png"), new_png)
            # Relationship is redirected to image1.png
            rels = archive.read("ppt/slides/_rels/slide1.xml.rels").decode("utf-8")
            self.assertIn('Target="../media/image1.png"', rels)
            self.assertNotIn('Target="../media/image1.emf"', rels)
            # Content types has png
            ct = archive.read("[Content_Types].xml").decode("utf-8")
            self.assertIn('Extension="png"', ct)


class CliBridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "input.pptx"
        self.session = self.root / "session"
        self.output = self.root / "output.pptx"

    def test_cli_prepare_and_writeback_success(self):
        from io import StringIO
        from unittest.mock import patch
        from slidebridge.cli import main

        orig_ole = cfb_payload(0)
        orig_preview = minimal_png(10, 10)
        package_with_preview(self.source, orig_ole, orig_preview)

        # 1. prepare-ole via CLI
        with patch("sys.stdout", new=StringIO()) as out:
            rc = main(["prepare-ole", str(self.source), "--member", "ppt/embeddings/object1.bin", "-o", str(self.session), "--json"])
            self.assertEqual(rc, 0)
            data = json.loads(out.getvalue())
            self.assertEqual(data["member"], "ppt/embeddings/object1.bin")

        # Create edit files
        edited_ole = cfb_payload(99)
        new_preview = minimal_png(20, 20)
        (self.session / "edited.bin").write_bytes(edited_ole)
        (self.session / "preview.png").write_bytes(new_preview)

        # 2. writeback-ole via CLI
        with patch("sys.stdout", new=StringIO()) as out:
            rc = main([
                "writeback-ole",
                str(self.source),
                "--session", str(self.session),
                "-o", str(self.output),
                "--json",
            ])
            self.assertEqual(rc, 0)
            data = json.loads(out.getvalue())
            self.assertEqual(data["status"], "success")
            self.assertEqual(data["ole_sha256_after"], hashlib.sha256(edited_ole).hexdigest())

        self.assertTrue(self.output.exists())

    def test_cli_writeback_error_handling(self):
        from io import StringIO
        from unittest.mock import patch
        from slidebridge.cli import main

        orig_ole = cfb_payload(0)
        orig_preview = minimal_png(10, 10)
        package_with_preview(self.source, orig_ole, orig_preview)
        prepare_ole(self.source, "ppt/embeddings/object1.bin", self.session)

        # Run without preview
        with patch("sys.stderr", new=StringIO()) as err:
            rc = main([
                "writeback-ole",
                str(self.source),
                "--session", str(self.session),
                "-o", str(self.output),
            ])
            self.assertEqual(rc, 1)
            self.assertIn("paired writeback requires a preview image", err.getvalue().lower())


if __name__ == "__main__":
    unittest.main()
