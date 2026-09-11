import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from unittest.mock import patch
from slidebridge.bridge import _find_preview_members, prepare_ole, writeback_ole, edit_presentation
from slidebridge.core import SlideBridgeError
from slidebridge.vm import Guest


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


def package_with_alternate_content(
    path: Path,
    ole: bytes,
    preview: bytes,
    preview_name: str = "image7.emf",
) -> bytes:
    """Build the real-world PowerPoint shape for an OLE object.

    PowerPoint wraps each OLE in <mc:AlternateContent> with two branches that
    both carry the same r:id: an <mc:Choice> holding a bare
    <p:oleObj><p:embed/></p:oleObj>, and an <mc:Fallback> holding the preview
    <p:pic>. The preview only exists in the second branch.
    """
    slide = (
        '<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
        'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
        'xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006" '
        'xmlns:v="urn:schemas-microsoft-com:vml">'
        "<p:cSld><p:spTree><p:graphicFrame>"
        "<p:nvGraphicFramePr><p:cNvPr id=\"11\" name=\"object 10\"/></p:nvGraphicFramePr>"
        "<a:graphic><a:graphicData "
        'uri="http://schemas.openxmlformats.org/presentationml/2006/ole">'
        "<mc:AlternateContent>"
        '<mc:Choice Requires="v">'
        '<p:oleObj name="Graph" r:id="ole1" imgW="49532658" imgH="10012769" progId="Origin95.Graph">'
        "<p:embed/></p:oleObj>"
        "</mc:Choice>"
        "<mc:Fallback>"
        '<p:oleObj name="Graph" r:id="ole1" imgW="49532658" imgH="10012769" progId="Origin95.Graph">'
        "<p:embed/>"
        "<p:pic><p:nvPicPr><p:cNvPr id=\"11\" name=\"object 10\"/></p:nvPicPr>"
        f'<p:blipFill><a:blip r:embed="img1"/></p:blipFill></p:pic>'
        "</p:oleObj>"
        "</mc:Fallback>"
        "</mc:AlternateContent>"
        "</a:graphicData></a:graphic></p:graphicFrame></p:spTree></p:cSld></p:sld>"
    ).encode()
    rels = (
        f'<Relationships xmlns="{REL_NS}">'
        f'<Relationship Id="ole1" Type="{OLE_REL}" Target="../embeddings/object1.bin"/>'
        f'<Relationship Id="img1" Type="{IMAGE_REL}" Target="../media/{preview_name}"/>'
        f"</Relationships>"
    ).encode()
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("ppt/slides/slide1.xml", slide)
        archive.writestr("ppt/slides/_rels/slide1.xml.rels", rels)
        archive.writestr("ppt/embeddings/object1.bin", ole)
        archive.writestr(f"ppt/media/{preview_name}", preview)
        archive.writestr(
            "[Content_Types].xml",
            b'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>',
        )
    return path.read_bytes()


class AlternateContentPreviewTests(unittest.TestCase):
    """Regression: the preview lives in the mc:Fallback branch only.

    The original code stopped at the first <p:oleObj> matching the r:id, which
    is the preview-less mc:Choice branch. Writeback then failed with
    "could not find any preview images associated with OLE member".
    """

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "input.pptx"

    def test_preview_is_found_in_the_fallback_branch(self):
        package_with_alternate_content(self.source, cfb_payload(), minimal_png(tag=b"preview"))
        with zipfile.ZipFile(self.source) as archive:
            found = _find_preview_members(
                archive, [{"slide": "ppt/slides/slide1.xml", "relationship_id": "ole1"}]
            )
        self.assertEqual(found, ["ppt/media/image7.emf"])

    def test_writeback_succeeds_end_to_end(self):
        package_with_alternate_content(self.source, cfb_payload(0), minimal_png(tag=b"old"))
        session = self.root / "session"
        prepare_ole(self.source, "ppt/embeddings/object1.bin", session)

        (session / "edited.bin").write_bytes(cfb_payload(1))
        (session / "edited.png").write_bytes(minimal_png(tag=b"new"))

        output = self.root / "out.pptx"
        report = writeback_ole(self.source, session, output_path=output)

        self.assertEqual(report["status"], "success")
        self.assertEqual(report["preview_members"], ["ppt/media/image7.emf"])
        with zipfile.ZipFile(output) as archive:
            self.assertEqual(
                archive.read("ppt/embeddings/object1.bin"), cfb_payload(1)
            )
            self.assertIn(b"image7.png", archive.read("ppt/slides/_rels/slide1.xml.rels"))

    def test_manifest_records_the_preview(self):
        package_with_alternate_content(self.source, cfb_payload(), minimal_png())
        session = self.root / "session"
        prepare_ole(self.source, "ppt/embeddings/object1.bin", session)
        manifest = json.loads((session / "manifest.json").read_text())
        self.assertEqual(manifest["preview_members"], ["ppt/media/image7.emf"])


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

        # A genuinely different OLE, so this exercises the missing-preview path
        # rather than tripping the unchanged-OLE guard.
        (self.session / "edited.bin").write_bytes(cfb_payload(1))

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


class UnchangedOleGuardTests(unittest.TestCase):
    """A writeback that cannot change anything must fail loudly.

    Regression: Origin re-serialises its document with a few bytes of metadata
    even when the chart was never saved inside Origin, so the writeback
    silently produced a presentation that still looked unchanged.
    """

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "input.pptx"
        self.session = self.root / "session"
        self.output = self.root / "out.pptx"

    def _prepare(self, ole: bytes) -> None:
        package_with_preview(self.source, ole, minimal_png())
        prepare_ole(self.source, "ppt/embeddings/object1.bin", self.session)
        (self.session / "edited.png").write_bytes(minimal_png(tag=b"new"))

    @staticmethod
    def _large_cfb(size: int = 200_000) -> bytes:
        data = bytearray(size)
        data[:8] = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
        data[24:32] = (0x0003003E).to_bytes(8, "little")
        return bytes(data)

    def test_identical_ole_is_rejected_with_actionable_advice(self):
        self._prepare(cfb_payload(0))
        (self.session / "edited.bin").write_bytes(cfb_payload(0))

        with self.assertRaises(SlideBridgeError) as ctx:
            writeback_ole(self.source, self.session, output_path=self.output)

        message = str(ctx.exception)
        self.assertIn("byte-identical", message)
        self.assertIn("press Save", message)
        self.assertFalse(self.output.exists())

    def test_metadata_only_difference_is_rejected(self):
        """The observed real-world case: 5 bytes changed, chart untouched."""
        ole = self._large_cfb()
        self._prepare(ole)
        tweaked = bytearray(ole)
        for offset in (1132, 1133, 1134, 1135, 1136):
            tweaked[offset] ^= 0xFF
        (self.session / "edited.bin").write_bytes(bytes(tweaked))

        with self.assertRaises(SlideBridgeError) as ctx:
            writeback_ole(self.source, self.session, output_path=self.output)

        self.assertIn("re-serialised metadata", str(ctx.exception))
        self.assertFalse(self.output.exists())

    def test_force_does_not_bypass_the_guard(self):
        """edit-active always passes force=True for the source-hash check only."""
        self._prepare(cfb_payload(0))
        (self.session / "edited.bin").write_bytes(cfb_payload(0))

        with self.assertRaises(SlideBridgeError):
            writeback_ole(self.source, self.session, output_path=self.output, force=True)

    def test_allow_unchanged_permits_a_deliberate_no_op(self):
        self._prepare(cfb_payload(0))
        (self.session / "edited.bin").write_bytes(cfb_payload(0))

        report = writeback_ole(
            self.source, self.session, output_path=self.output, allow_unchanged=True
        )
        self.assertEqual(report["status"], "success")

    def test_a_real_change_still_writes_back(self):
        self._prepare(cfb_payload(0))
        (self.session / "edited.bin").write_bytes(cfb_payload(1))

        report = writeback_ole(self.source, self.session, output_path=self.output)

        self.assertEqual(report["status"], "success")
        self.assertTrue(self.output.is_file())


class UnchangedPreviewGuardTests(unittest.TestCase):
    """Regression: the helper rendered from Origin's *cached* presentation.

    Origin keeps its live document in the "Contents" stream but does not always
    refresh the "OlePres000/001" presentation cache, so the exported preview
    could be an image of the chart as it looked before the edit. The OLE binary
    changed, so the OLE guard passed, and the stale image was written back
    silently -- the chart in PowerPoint appeared unchanged.
    """

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "input.pptx"
        self.session = self.root / "session"
        self.output = self.root / "out.pptx"
        self.preview = minimal_png(tag=b"unchanged")

    def _prepare(self) -> None:
        package_with_preview(self.source, cfb_payload(0), self.preview)
        prepare_ole(self.source, "ppt/embeddings/object1.bin", self.session)
        # A real OLE change, so the OLE guard does not fire first.
        (self.session / "edited.bin").write_bytes(cfb_payload(1))

    def test_identical_preview_is_rejected_with_the_reason(self):
        self._prepare()
        (self.session / "edited.png").write_bytes(self.preview)

        with self.assertRaises(SlideBridgeError) as ctx:
            writeback_ole(self.source, self.session, output_path=self.output)

        message = str(ctx.exception)
        self.assertIn("byte-identical", message)
        self.assertIn("cached image", message)
        self.assertIn("press Save inside Origin", message)
        self.assertFalse(self.output.exists())

    def test_force_does_not_bypass_the_guard(self):
        self._prepare()
        (self.session / "edited.png").write_bytes(self.preview)

        with self.assertRaises(SlideBridgeError):
            writeback_ole(self.source, self.session, output_path=self.output, force=True)

    def test_allow_unchanged_permits_it(self):
        self._prepare()
        (self.session / "edited.png").write_bytes(self.preview)

        report = writeback_ole(
            self.source, self.session, output_path=self.output, allow_unchanged=True
        )
        self.assertEqual(report["status"], "success")

    def test_a_changed_preview_still_writes_back(self):
        self._prepare()
        (self.session / "edited.png").write_bytes(minimal_png(tag=b"changed"))

        report = writeback_ole(self.source, self.session, output_path=self.output)

        self.assertEqual(report["status"], "success")
        self.assertTrue(self.output.is_file())


class ManualPreviewPrecedenceTests(unittest.TestCase):
    """A preview the user exports from Origin must beat the helper's own render.

    Origin will not render an edited chart for us -- it neither refreshes the
    OLE presentation cache nor draws live in OLEIVERB_OPEN mode -- so the
    documented workflow is: export the graph from Origin into the session folder
    as ``preview.png``. ``writeback_ole`` must then prefer that file over the
    helper's stale ``edited.png``.
    """

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "input.pptx"
        self.session = self.root / "session"
        self.output = self.root / "out.pptx"
        self.original_preview = minimal_png(tag=b"original")

    def _prepare(self) -> None:
        package_with_preview(self.source, cfb_payload(0), self.original_preview)
        prepare_ole(self.source, "ppt/embeddings/object1.bin", self.session)
        (self.session / "edited.bin").write_bytes(cfb_payload(1))
        # The helper's own render is stale: identical to what is already there.
        (self.session / "edited.png").write_bytes(self.original_preview)

    def test_stale_helper_render_on_its_own_is_rejected(self):
        self._prepare()
        with self.assertRaises(SlideBridgeError):
            writeback_ole(self.source, self.session, output_path=self.output)

    def test_user_exported_preview_wins_over_the_stale_render(self):
        self._prepare()
        exported = minimal_png(tag=b"exported-by-user")
        (self.session / "preview.png").write_bytes(exported)

        report = writeback_ole(self.source, self.session, output_path=self.output)

        self.assertEqual(report["status"], "success")
        self.assertEqual(report["preview_source"], str(self.session / "preview.png"))
        with zipfile.ZipFile(self.output) as archive:
            self.assertEqual(archive.read("ppt/media/image1.png"), exported)

    def test_user_exported_emf_is_also_accepted(self):
        """The original decks carry EMF previews, so that path must work too."""
        package_with_preview(
            self.source, cfb_payload(0), minimal_emf(b"original"), preview_name="image1.emf"
        )
        prepare_ole(self.source, "ppt/embeddings/object1.bin", self.session)
        (self.session / "edited.bin").write_bytes(cfb_payload(1))
        # The helper's own render is stale: identical to what is already there.
        (self.session / "edited.emf").write_bytes(minimal_emf(b"original"))
        exported = minimal_emf(b"exported-by-user")
        (self.session / "preview.emf").write_bytes(exported)

        report = writeback_ole(self.source, self.session, output_path=self.output)

        self.assertEqual(report["status"], "success")
        self.assertEqual(report["preview_format"], "emf")
        with zipfile.ZipFile(self.output) as archive:
            self.assertEqual(archive.read("ppt/media/image1.emf"), exported)


class EditPresentationTests(unittest.TestCase):
    """Verify the deep orchestration module slidebridge.bridge.edit_presentation."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.source = self.root / "deck.pptx"
        self.output = self.root / "deck_out.pptx"

    def tearDown(self):
        self.tmp.cleanup()

    def test_missing_file_raises_error(self):
        with self.assertRaises(SlideBridgeError) as ctx:
            edit_presentation(self.root / "nonexistent.pptx")
        self.assertIn("presentation file not found", str(ctx.exception))

    def test_presentation_without_ole_raises_error(self):
        with zipfile.ZipFile(self.source, "w") as arc:
            arc.writestr("ppt/slides/slide1.xml", b"<p:sld/>")
        with self.assertRaises(SlideBridgeError) as ctx:
            edit_presentation(self.source)
        self.assertIn("No embedded OLE objects found", str(ctx.exception))

    def test_edit_presentation_success(self):
        package_with_preview(
            self.source, cfb_payload(0), minimal_png(10, 10, b"original"), preview_name="image1.png"
        )

        def mock_launch(guest, session_dir, **kwargs):
            # Simulate Origin helper editing the object and auto-exporting preview
            (session_dir / "edited.bin").write_bytes(cfb_payload(1))
            (session_dir / "preview.png").write_bytes(minimal_png(20, 20, b"new-chart"))
            return 0

        with patch("slidebridge.vm.detect_guest", return_value=Guest("parallels", "Win11")), patch(
            "slidebridge.vm.launch_vm_helper", side_effect=mock_launch
        ):
            report = edit_presentation(self.source, output_path=self.output)

        self.assertEqual(report["status"], "success")
        self.assertEqual(report["member"], "ppt/embeddings/object1.bin")
        self.assertEqual(report["vm"], "Win11")
        self.assertTrue(self.output.is_file())

    def test_helper_failure_raises_error(self):
        package_with_preview(
            self.source, cfb_payload(0), minimal_png(10, 10, b"original"), preview_name="image1.png"
        )

        with patch("slidebridge.vm.detect_guest", return_value=Guest("parallels", "Win11")), patch(
            "slidebridge.vm.launch_vm_helper", return_value=1
        ):
            with self.assertRaises(SlideBridgeError) as ctx:
                edit_presentation(self.source, output_path=self.output)
            self.assertIn("No edited.bin found in session", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
