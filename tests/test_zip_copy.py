"""Unchanged package members must retain bytes and metadata with bounded reads."""

import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from slidebridge.bridge import prepare_ole, writeback_ole
from slidebridge.core import SlideBridgeError, _copy_archive_member, repair
from test_bridge import cfb_payload, minimal_png, package_with_preview


class ZipCopyTests(unittest.TestCase):
    def test_streaming_copy_preserves_bytes_and_metadata(self):
        payload = bytes(range(256)) * 17000
        for compression in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
            with self.subTest(compression=compression):
                source_buffer, output_buffer = io.BytesIO(), io.BytesIO()
                info = zipfile.ZipInfo("ppt/embeddings/large.bin", (2020, 2, 3, 4, 5, 6))
                info.compress_type = compression
                info.comment = b"member comment"
                info.extra = b"\xfe\xca\x02\x00ok"
                info.external_attr = 0o640 << 16
                with zipfile.ZipFile(source_buffer, "w") as archive:
                    archive.writestr(info, payload)
                    archive.writestr("empty/", b"")
                    archive.writestr("zero.bin", b"")
                original_read = zipfile.ZipExtFile.read
                sizes = []

                def bounded_read(stream, n=-1):
                    self.assertGreater(n, 0)
                    self.assertLessEqual(n, 1024 * 1024)
                    sizes.append(n)
                    return original_read(stream, n)

                with zipfile.ZipFile(source_buffer) as source:
                    original_metadata = [(entry.CRC, entry.file_size, entry.compress_size)
                                         for entry in source.infolist()]
                    with zipfile.ZipFile(output_buffer, "w") as destination:
                        with patch.object(zipfile.ZipExtFile, "read", bounded_read):
                            for entry in source.infolist():
                                _copy_archive_member(source, destination, entry)
                    self.assertGreater(len(sizes), 4)
                    with zipfile.ZipFile(output_buffer) as output:
                        for before, after in zip(source.infolist(), output.infolist()):
                            self.assertEqual(source.read(before), output.read(after))
                            for attr in ("filename", "date_time", "compress_type", "comment",
                                         "extra", "external_attr", "create_system", "CRC", "file_size"):
                                self.assertEqual(getattr(before, attr), getattr(after, attr), attr)
                    self.assertEqual(original_metadata,
                                     [(entry.CRC, entry.file_size, entry.compress_size)
                                      for entry in source.infolist()])

    def test_repair_and_writeback_stream_unrelated_members(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "input.pptx"
            package_with_preview(source, cfb_payload(), minimal_png())
            unrelated = "ppt/media/large-video.bin"
            payload = b"unrelated data" * 200000
            with zipfile.ZipFile(source, "a") as archive:
                archive.writestr(unrelated, payload)
                archive.writestr("ppt/presentation.xml", b"<presentation/>")
            session = root / "session"
            prepare_ole(source, "ppt/embeddings/object1.bin", session)
            (session / "edited.bin").write_bytes(cfb_payload(1))
            (session / "preview.png").write_bytes(minimal_png(20, 20))
            original_read = zipfile.ZipFile.read

            def reject_full_read(archive, name, *args, **kwargs):
                member = name.filename if isinstance(name, zipfile.ZipInfo) else name
                self.assertNotEqual(member, unrelated)
                return original_read(archive, name, *args, **kwargs)

            with patch.object(zipfile.ZipFile, "read", reject_full_read):
                repair(source, root / "repaired.pptx")
                writeback_ole(source, session, root / "updated.pptx")
            for name in ("repaired.pptx", "updated.pptx"):
                with zipfile.ZipFile(root / name) as archive:
                    self.assertEqual(archive.read(unrelated), payload)

            def fail_mid_copy(source_stream, target_stream, **kwargs):
                target_stream.write(source_stream.read(8))
                raise OSError("simulated write failure")

            original = source.read_bytes()
            for operation in (lambda output: repair(source, output),
                              lambda output: writeback_ole(source, session, output)):
                with patch("slidebridge.core.shutil.copyfileobj", side_effect=fail_mid_copy):
                    with self.assertRaises(SlideBridgeError):
                        operation(root / "failed.pptx")
                self.assertFalse((root / "failed.pptx").exists())
                self.assertEqual(list(root.glob(".slidebridge-*")), [])
                self.assertEqual(source.read_bytes(), original)
