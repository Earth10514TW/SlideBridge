"""Tests for the hidden backup store.

Most of what this module promises is a negative — no file left beside the
user's presentation, nothing kept forever, nothing restored by accident — so
the interesting tests are the ones asserting what must *not* happen.
"""

import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from slidebridge import backup
from slidebridge.core import SlideBridgeError


class BackupStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.work = self.root / "work"
        self.work.mkdir()
        # Every test gets its own store, so the developer's real
        # ~/Library/Application Support/SlideBridge is never touched.
        self._env = patch.dict(os.environ, {"SLIDEBRIDGE_BACKUP_DIR": str(self.root / "store")})
        self._env.start()
        for name in ("SLIDEBRIDGE_BACKUP_RETENTION_DAYS", "SLIDEBRIDGE_BACKUP_KEEP"):
            os.environ.pop(name, None)

    def tearDown(self):
        self._env.stop()
        self.tmp.cleanup()

    def _deck(self, name="Deck.pptx", payload=b"v1"):
        path = self.work / name
        path.write_bytes(payload)
        return path

    def _store_dir(self, source):
        return Path(backup.list_backups(source)["store"])

    def _backdate(self, source, days):
        """Age every snapshot of ``source`` so retention treats it as expired."""
        store = self._store_dir(source)
        index_file = store / "manifest.json"
        index = json.loads(index_file.read_text(encoding="utf-8"))
        old = time.time() - days * 86400
        for entry in index["backups"]:
            entry["ts"] = old
            entry["created"] = backup._iso(old)
        index_file.write_text(json.dumps(index), encoding="utf-8")

    # --- the reason this module exists -----------------------------------

    def test_create_leaves_nothing_beside_the_presentation(self):
        deck = self._deck()
        backup.create_backup(deck)
        self.assertEqual(sorted(p.name for p in self.work.iterdir()), ["Deck.pptx"])

    def test_backup_is_not_named_like_a_visible_sibling(self):
        deck = self._deck()
        created = backup.create_backup(deck)
        self.assertFalse((self.work / "Deck.sb_backup.pptx").exists())
        self.assertNotEqual(Path(created["backup"]["path"]).parent, self.work)
        self.assertEqual(Path(created["backup"]["path"]).parent, self._store_dir(deck))

    def test_store_is_created_under_the_configured_root(self):
        deck = self._deck()
        backup.create_backup(deck)
        self.assertEqual(backup.backup_root(), self.root / "store")

    def test_separate_presentations_get_separate_stores(self):
        first = self._deck("A.pptx")
        second = self._deck("B.pptx")
        backup.create_backup(first)
        backup.create_backup(second)
        self.assertNotEqual(self._store_dir(first), self._store_dir(second))
        self.assertEqual(backup.list_backups(first)["count"], 1)
        self.assertEqual(backup.list_backups(second)["count"], 1)

    # --- creating ---------------------------------------------------------

    def test_create_records_original_bytes(self):
        deck = self._deck(payload=b"original")
        created = backup.create_backup(deck)
        self.assertEqual(Path(created["backup"]["path"]).read_bytes(), b"original")
        self.assertEqual(created["backup"]["reason"], "in-place-writeback")

    def test_same_second_backups_get_distinct_ids(self):
        deck = self._deck()
        ids = []
        for index in range(3):
            deck.write_bytes(f"v{index}".encode())
            ids.append(backup.create_backup(deck)["backup"]["id"])
        self.assertEqual(len(set(ids)), 3)
        self.assertEqual(backup.list_backups(deck)["count"], 3)

    def test_create_on_missing_presentation_raises(self):
        with self.assertRaises(SlideBridgeError) as ctx:
            backup.create_backup(self.work / "nope.pptx")
        self.assertIn("missing presentation", str(ctx.exception))

    def test_creating_backup_does_not_modify_the_presentation(self):
        deck = self._deck(payload=b"untouched")
        backup.create_backup(deck)
        self.assertEqual(deck.read_bytes(), b"untouched")

    # --- listing ----------------------------------------------------------

    def test_list_is_newest_first_and_reports_total_size(self):
        deck = self._deck()
        for index in range(3):
            deck.write_bytes(b"x" * (100 * (index + 1)))
            backup.create_backup(deck)
        report = backup.list_backups(deck)
        self.assertEqual(report["count"], 3)
        self.assertEqual(report["total_bytes"], 600)
        stamps = [entry["ts"] for entry in report["backups"]]
        self.assertEqual(stamps, sorted(stamps, reverse=True))

    def test_list_for_unknown_presentation_is_empty(self):
        report = backup.list_backups(self.work / "never-edited.pptx")
        self.assertEqual(report["count"], 0)
        self.assertEqual(report["backups"], [])

    def test_list_all_spans_presentations(self):
        first = self._deck("A.pptx")
        second = self._deck("B.pptx")
        backup.create_backup(first)
        backup.create_backup(second)
        report = backup.list_backups()
        self.assertEqual(report["count"], 2)
        self.assertEqual(
            sorted(entry["source"] for entry in report["backups"]),
            sorted([str(first), str(second)]),
        )

    def test_list_reports_retention_policy(self):
        deck = self._deck()
        report = backup.list_backups(deck)
        self.assertEqual(report["retention_days"], backup.DEFAULT_RETENTION_DAYS)
        self.assertEqual(report["max_per_presentation"], backup.DEFAULT_MAX_PER_PRESENTATION)

    def test_index_rebuild_adopts_orphaned_files(self):
        """A deleted index must not orphan snapshots that are still on disk."""
        deck = self._deck()
        backup.create_backup(deck)
        store = self._store_dir(deck)
        (store / "manifest.json").unlink()

        report = backup.list_backups(deck)
        self.assertEqual(report["count"], 1)
        self.assertEqual(report["backups"][0]["reason"], "unknown")

    def test_corrupt_index_is_rebuilt_from_disk(self):
        deck = self._deck()
        backup.create_backup(deck)
        (self._store_dir(deck) / "manifest.json").write_text("{ not json", encoding="utf-8")
        self.assertEqual(backup.list_backups(deck)["count"], 1)

    # --- restoring --------------------------------------------------------

    def test_restore_newest_round_trips_content(self):
        deck = self._deck(payload=b"v1")
        backup.create_backup(deck)
        deck.write_bytes(b"v2")
        backup.create_backup(deck)
        deck.write_bytes(b"v3")

        report = backup.restore_backup(deck)
        self.assertEqual(report["status"], "success")
        self.assertEqual(deck.read_bytes(), b"v2")

    def test_restore_specific_id_round_trips_content(self):
        deck = self._deck(payload=b"v1")
        backup.create_backup(deck)
        oldest = backup.list_backups(deck)["backups"][0]["id"]
        deck.write_bytes(b"v2")
        backup.create_backup(deck)
        deck.write_bytes(b"v3")

        backup.restore_backup(deck, oldest)
        self.assertEqual(deck.read_bytes(), b"v1")

    def test_restore_is_itself_undoable(self):
        deck = self._deck(payload=b"good")
        backup.create_backup(deck)
        oldest = backup.list_backups(deck)["backups"][0]["id"]
        deck.write_bytes(b"bad")

        report = backup.restore_backup(deck, oldest)
        self.assertIsNotNone(report["previous_backup"])
        self.assertEqual(report["previous_backup"]["reason"], "pre-restore")

        # Restoring the safety snapshot must bring the discarded version back.
        backup.restore_backup(deck, report["previous_backup"]["id"])
        self.assertEqual(deck.read_bytes(), b"bad")

    def test_restore_reports_unchanged_when_already_matching(self):
        deck = self._deck(payload=b"same")
        created = backup.create_backup(deck)
        report = backup.restore_backup(deck, created["backup"]["id"])
        self.assertEqual(report["status"], "unchanged")
        self.assertIsNone(report.get("previous_backup"))

    def test_restore_does_not_add_a_snapshot_when_unchanged(self):
        deck = self._deck(payload=b"same")
        backup.create_backup(deck)
        backup.restore_backup(deck)
        self.assertEqual(backup.list_backups(deck)["count"], 1)

    def test_restore_without_backups_raises(self):
        deck = self._deck()
        with self.assertRaises(SlideBridgeError) as ctx:
            backup.restore_backup(deck)
        self.assertIn("no backups available", str(ctx.exception))

    def test_restore_rejects_unknown_id(self):
        deck = self._deck()
        backup.create_backup(deck)
        with self.assertRaises(SlideBridgeError) as ctx:
            backup.restore_backup(deck, "nope.pptx")
        self.assertIn("backup not found", str(ctx.exception))

    def test_restore_rejects_path_traversal(self):
        deck = self._deck()
        backup.create_backup(deck)
        for hostile in ("../../etc/passwd", "/etc/passwd", "sub/dir.pptx"):
            with self.subTest(hostile=hostile):
                with self.assertRaises(SlideBridgeError) as ctx:
                    backup.restore_backup(deck, hostile)
                self.assertIn("invalid backup id", str(ctx.exception))

    def test_restore_on_missing_presentation_raises(self):
        with self.assertRaises(SlideBridgeError) as ctx:
            backup.restore_backup(self.work / "nope.pptx")
        self.assertIn("presentation not found", str(ctx.exception))

    def test_restore_leaves_no_temporary_file_behind(self):
        deck = self._deck(payload=b"v1")
        backup.create_backup(deck)
        deck.write_bytes(b"v2")
        backup.restore_backup(deck)
        self.assertEqual(sorted(p.name for p in self.work.iterdir()), ["Deck.pptx"])

    # --- retention --------------------------------------------------------

    def test_count_retention_keeps_the_newest(self):
        deck = self._deck()
        for index in range(5):
            deck.write_bytes(f"v{index}".encode())
            backup.create_backup(deck, max_per_presentation=2, retention_days=30)

        report = backup.list_backups(deck)
        self.assertEqual(report["count"], 2)
        store = Path(report["store"])
        on_disk = sorted(p.name for p in store.iterdir() if p.name.endswith(".pptx"))
        self.assertEqual(len(on_disk), 2)
        # Index and disk must agree: a file listed but deleted is the bug that
        # silently collapses the store.
        self.assertEqual(sorted(e["id"] for e in report["backups"]), on_disk)

    def test_age_retention_prunes_expired_snapshots(self):
        deck = self._deck()
        backup.create_backup(deck, retention_days=30)
        self._backdate(deck, days=10)

        deck.write_bytes(b"new")
        created = backup.create_backup(deck, retention_days=7, max_per_presentation=5)

        self.assertEqual(len(created["pruned"]), 1)
        self.assertEqual(backup.list_backups(deck)["count"], 1)

    def test_age_retention_survives_a_backdated_index(self):
        deck = self._deck()
        backup.create_backup(deck)
        self._backdate(deck, days=8)
        self.assertEqual(backup.list_backups(deck)["count"], 1)
        report = backup.prune_backups(retention_days=7)
        self.assertEqual(report["removed_count"], 1)
        self.assertEqual(backup.list_backups(deck)["count"], 0)

    def test_retention_reaches_presentations_the_user_stopped_editing(self):
        """A deck edited once and abandoned must not hold space forever."""
        stale = self._deck("Stale.pptx")
        backup.create_backup(stale)
        self._backdate(stale, days=30)

        active = self._deck("Active.pptx")
        backup.create_backup(active, retention_days=7)

        self.assertEqual(backup.list_backups(stale)["count"], 0)

    def test_pruned_store_directory_is_removed(self):
        deck = self._deck()
        backup.create_backup(deck)
        store = self._store_dir(deck)
        self._backdate(deck, days=30)
        backup.prune_backups(retention_days=7)
        self.assertFalse(store.exists())

    def test_prune_reports_freed_bytes(self):
        deck = self._deck(payload=b"z" * 512)
        backup.create_backup(deck)
        self._backdate(deck, days=30)
        report = backup.prune_backups(retention_days=7)
        self.assertEqual(report["removed_bytes"], 512)

    def test_retention_defaults_can_be_overridden_by_environment(self):
        with patch.dict(os.environ, {"SLIDEBRIDGE_BACKUP_RETENTION_DAYS": "1", "SLIDEBRIDGE_BACKUP_KEEP": "2"}):
            self.assertEqual(backup.default_retention_days(), 1)
            self.assertEqual(backup.default_max_per_presentation(), 2)

    def test_invalid_environment_values_fall_back_to_defaults(self):
        with patch.dict(os.environ, {"SLIDEBRIDGE_BACKUP_RETENTION_DAYS": "zero", "SLIDEBRIDGE_BACKUP_KEEP": "-3"}):
            self.assertEqual(backup.default_retention_days(), backup.DEFAULT_RETENTION_DAYS)
            self.assertEqual(backup.default_max_per_presentation(), backup.DEFAULT_MAX_PER_PRESENTATION)

    # --- clearing ---------------------------------------------------------

    def test_clear_removes_this_presentation_only(self):
        first = self._deck("A.pptx")
        second = self._deck("B.pptx")
        backup.create_backup(first)
        backup.create_backup(second)

        report = backup.clear_backups(first)
        self.assertEqual(report["removed_count"], 1)
        self.assertEqual(backup.list_backups(first)["count"], 0)
        self.assertEqual(backup.list_backups(second)["count"], 1)

    def test_clear_everything_empties_the_store(self):
        for name in ("A.pptx", "B.pptx"):
            backup.create_backup(self._deck(name))
        report = backup.clear_backups()
        self.assertEqual(report["removed_count"], 2)
        self.assertEqual(backup.list_backups()["count"], 0)

    def test_clear_reports_freed_bytes(self):
        deck = self._deck(payload=b"q" * 256)
        backup.create_backup(deck)
        self.assertEqual(backup.clear_backups(deck)["removed_bytes"], 256)

    def test_clear_on_presentation_without_backups_is_a_no_op(self):
        report = backup.clear_backups(self._deck())
        self.assertEqual(report["removed_count"], 0)

    def test_cleared_backups_cannot_be_restored(self):
        deck = self._deck(payload=b"v1")
        backup.create_backup(deck)
        deck.write_bytes(b"v2")
        backup.clear_backups(deck)
        with self.assertRaises(SlideBridgeError):
            backup.restore_backup(deck)


class BackupCliTests(unittest.TestCase):
    """The app drives the store through the CLI, so the CLI contract matters."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.work = self.root / "work"
        self.work.mkdir()
        self._env = patch.dict(os.environ, {"SLIDEBRIDGE_BACKUP_DIR": str(self.root / "store")})
        self._env.start()

    def tearDown(self):
        self._env.stop()
        self.tmp.cleanup()

    def _run(self, argv):
        from io import StringIO
        from slidebridge.cli import main

        with patch("sys.stdout", new=StringIO()) as out, patch("sys.stderr", new=StringIO()) as err:
            code = main(argv)
        return code, out.getvalue(), err.getvalue()

    def _deck(self, name="Deck.pptx", payload=b"v1"):
        path = self.work / name
        path.write_bytes(payload)
        return path

    def test_list_json_reports_store_contents(self):
        deck = self._deck()
        backup.create_backup(deck)
        code, out, _ = self._run(["backups", "list", str(deck), "--json"])
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["backups"][0]["source"], str(deck))

    def test_list_all_json_spans_presentations(self):
        backup.create_backup(self._deck("A.pptx"))
        backup.create_backup(self._deck("B.pptx"))
        code, out, _ = self._run(["backups", "list", "--json"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["count"], 2)

    def test_restore_json_round_trips(self):
        deck = self._deck(payload=b"v1")
        backup.create_backup(deck)
        deck.write_bytes(b"v2")
        code, out, _ = self._run(["backups", "restore", str(deck), "--json"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["status"], "success")
        self.assertEqual(deck.read_bytes(), b"v1")

    def test_restore_unknown_id_exits_nonzero(self):
        deck = self._deck()
        backup.create_backup(deck)
        code, _, err = self._run(["backups", "restore", str(deck), "--id", "nope.pptx", "--json"])
        self.assertEqual(code, 1)
        self.assertIn("backup not found", err)

    def test_clear_json_frees_the_store(self):
        deck = self._deck()
        backup.create_backup(deck)
        code, out, _ = self._run(["backups", "clear", str(deck), "--json"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["removed_count"], 1)
        self.assertEqual(backup.list_backups(deck)["count"], 0)

    def test_human_output_does_not_point_at_the_presentation_folder(self):
        deck = self._deck()
        backup.create_backup(deck)
        _, out, _ = self._run(["backups", "list", str(deck)])
        self.assertIn("private store", out)
        self.assertNotIn("sb_backup", out)


if __name__ == "__main__":
    unittest.main()
