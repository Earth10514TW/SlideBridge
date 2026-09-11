"""Tests for portable executable discovery.

The behaviour that matters: a GUI-launched process (PowerPoint, Services menu,
double-clicked .app) inherits launchd's minimal PATH and must still find tools
that live in Homebrew or /usr/local/bin.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from slidebridge import locate


class ReadDirsTests(unittest.TestCase):
    def test_ignores_blanks_and_comments(self):
        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / "paths"
            source.write_text("# a comment\n/usr/bin\n\n/opt/homebrew/bin\n   \n")
            self.assertEqual(locate._read_dirs(source), ["/usr/bin", "/opt/homebrew/bin"])

    def test_missing_file_yields_nothing(self):
        self.assertEqual(locate._read_dirs(Path("/definitely/not/here/paths")), [])


class LoginPathTests(unittest.TestCase):
    def test_etc_paths_then_paths_d_in_lexical_order(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            paths = root / "paths"
            paths.write_text("/usr/local/bin\n/usr/bin\n")
            paths_d = root / "paths.d"
            paths_d.mkdir()
            (paths_d / "20-second").write_text("/opt/homebrew/bin\n")
            (paths_d / "10-first").write_text("/opt/local/bin\n")

            with patch.object(locate, "_PATHS_FILE", paths), patch.object(
                locate, "_PATHS_D", paths_d
            ):
                self.assertEqual(
                    locate.login_path_dirs(),
                    ["/usr/local/bin", "/usr/bin", "/opt/local/bin", "/opt/homebrew/bin"],
                )

    def test_duplicates_collapse_keeping_first(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            paths = root / "paths"
            paths.write_text("/usr/bin\n/usr/bin\n")
            paths_d = root / "paths.d"
            paths_d.mkdir()
            (paths_d / "extra").write_text("/usr/bin\n/opt/homebrew/bin\n")

            with patch.object(locate, "_PATHS_FILE", paths), patch.object(
                locate, "_PATHS_D", paths_d
            ):
                self.assertEqual(locate.login_path_dirs(), ["/usr/bin", "/opt/homebrew/bin"])

    def test_missing_paths_d_is_tolerated(self):
        with tempfile.TemporaryDirectory() as td:
            paths = Path(td) / "paths"
            paths.write_text("/usr/bin\n")
            with patch.object(locate, "_PATHS_FILE", paths), patch.object(
                locate, "_PATHS_D", Path(td) / "absent"
            ):
                self.assertEqual(locate.login_path_dirs(), ["/usr/bin"])


class SearchDirsTests(unittest.TestCase):
    def test_explicit_dirs_come_first_and_duplicates_are_dropped(self):
        with patch.object(locate, "login_path_dirs", return_value=["/usr/bin"]):
            with patch.dict(os.environ, {"PATH": "/usr/bin:/custom"}, clear=False):
                dirs = locate.search_dirs(["/explicit", "/custom"])
        self.assertEqual(dirs[0], "/explicit")
        self.assertEqual(dirs[1], "/custom")
        self.assertEqual(dirs[2], "/usr/bin")
        self.assertIn("/opt/homebrew/bin", dirs)
        self.assertEqual(len(dirs), len(set(dirs)))


class FindExecutableTests(unittest.TestCase):
    def test_absolute_executable_is_returned_as_is(self):
        self.assertEqual(locate.find_executable(sys.executable), sys.executable)

    def test_absolute_missing_path_is_none(self):
        self.assertIsNone(locate.find_executable("/definitely/not/a/tool"))

    def test_path_lookup_wins_when_available(self):
        with patch("shutil.which", return_value="/from/path/tool"):
            self.assertEqual(locate.find_executable("tool"), "/from/path/tool")

    def test_absolute_candidates_rescue_a_gui_launched_lookup(self):
        """The core regression: PATH lookup fails, an install location saves us."""
        with tempfile.TemporaryDirectory() as td:
            tool = Path(td) / "prlctl"
            tool.write_text("#!/bin/sh\n")
            tool.chmod(0o755)
            with patch("shutil.which", return_value=None), patch.object(
                locate, "search_dirs", return_value=[]
            ):
                found = locate.find_executable("prlctl", absolute_candidates=[str(tool)])
        self.assertEqual(found, str(tool))

    def test_search_dirs_are_consulted_last(self):
        with tempfile.TemporaryDirectory() as td:
            tool = Path(td) / "mytool"
            tool.write_text("#!/bin/sh\n")
            tool.chmod(0o755)
            with patch("shutil.which", return_value=None), patch.object(
                locate, "search_dirs", return_value=[td, "/nope"]
            ):
                self.assertEqual(locate.find_executable("mytool"), str(tool))

    def test_non_executable_candidate_is_skipped(self):
        with tempfile.TemporaryDirectory() as td:
            tool = Path(td) / "notexec"
            tool.write_text("data")
            tool.chmod(0o644)
            with patch("shutil.which", return_value=None), patch.object(
                locate, "search_dirs", return_value=[td]
            ):
                self.assertIsNone(locate.find_executable("notexec"))

    def test_nothing_found_returns_none(self):
        with patch("shutil.which", return_value=None), patch.object(
            locate, "search_dirs", return_value=[]
        ):
            self.assertIsNone(locate.find_executable("no-such-tool-anywhere-xyz"))


class EnsureLoginPathTests(unittest.TestCase):
    def test_appends_missing_dirs_without_duplicating(self):
        with patch.object(locate, "search_dirs", return_value=["/usr/bin", "/opt/homebrew/bin"]):
            with patch.dict(os.environ, {"PATH": "/usr/bin"}, clear=False):
                result = locate.ensure_login_path()
                # The mutation must land on the real environment, not a copy.
                self.assertEqual(os.environ["PATH"], result)
        self.assertEqual(result.split(os.pathsep), ["/usr/bin", "/opt/homebrew/bin"])

    def test_existing_entries_keep_their_order(self):
        with patch.object(locate, "search_dirs", return_value=["/opt/homebrew/bin"]):
            with patch.dict(os.environ, {"PATH": "/custom:/usr/bin"}, clear=False):
                result = locate.ensure_login_path()
        self.assertEqual(result.split(os.pathsep), ["/custom", "/usr/bin", "/opt/homebrew/bin"])


if __name__ == "__main__":
    unittest.main()
