"""Batch conversion should bound input reads without blocking free workers."""

import threading
import unittest
from unittest.mock import patch
import zipfile

from slidebridge.core import RepairError, _convert_media


class ConversionQueueTests(unittest.TestCase):
    def test_serial_reads_each_input_only_when_needed(self):
        infos = [zipfile.ZipInfo(f"ppt/media/image{i}.emf") for i in range(5)]
        reads = []

        class Archive:
            def read(self, info):
                reads.append(info.filename)
                return b"metafile"

        def convert(idx, source, output, data, *args, **kwargs):
            self.assertEqual(len(reads), idx + 1)
            return source, output, b"png", {"source": source}

        with patch("slidebridge.core._convert_single_item", side_effect=convert):
            _convert_media(Archive(), infos, set(), 300, "unused", {}, concurrency=1)
        self.assertEqual(reads, [info.filename for info in infos])

    def test_parallel_reads_are_bounded_and_refilled_without_reordering(self):
        infos = [zipfile.ZipInfo(f"ppt/media/image{i}.emf") for i in range(6)]
        owner = threading.get_ident()
        lock = threading.Lock()
        third_started = threading.Event()
        completed = set()
        reads = []
        outstanding = []
        test = self

        class Archive:
            def read(self, info):
                test.assertEqual(threading.get_ident(), owner)
                with lock:
                    reads.append(info.filename)
                    outstanding.append(len(reads) - len(completed))
                return b"metafile"

        def convert(idx, source, output, data, *args, **kwargs):
            if idx == 0:
                self.assertTrue(third_started.wait(3), "free worker was not refilled")
            elif idx == 2:
                third_started.set()
            with lock:
                completed.add(source)
            return source, output, str(idx).encode(), {"source": source}

        reference = infos[3].filename
        existing = {info.filename for info in infos} | {"ppt/media/image0.png"}
        with patch("slidebridge.core._convert_single_item", side_effect=convert):
            replacements, generated, converted, skipped = _convert_media(
                Archive(), infos, existing, 300, "unused", {reference: b"reference"},
                concurrency=2,
            )
        self.assertLessEqual(max(outstanding), 2)
        self.assertNotIn(reference, reads)
        expected = [reference] + [info.filename for info in infos if info.filename != reference]
        self.assertEqual(list(replacements), expected)
        self.assertEqual([entry["source"] for entry in converted], expected)
        self.assertEqual(list(generated), [replacements[name] for name in expected])
        self.assertEqual(generated[replacements[reference]], b"reference")
        self.assertNotEqual(replacements[infos[0].filename], "ppt/media/image0.png")

    def test_failure_does_not_read_remaining_inputs(self):
        infos = [zipfile.ZipInfo(f"ppt/media/image{i}.emf") for i in range(6)]
        reads = []

        class Archive:
            def read(self, info):
                reads.append(info.filename)
                return b"metafile"

        def convert(idx, source, output, data, *args, **kwargs):
            raise RepairError("conversion failed")

        with patch("slidebridge.core._convert_single_item", side_effect=convert):
            with self.assertRaisesRegex(RepairError, "conversion failed"):
                _convert_media(Archive(), infos, set(), 300, "unused", {}, concurrency=2)
        self.assertLessEqual(len(reads), 2)
