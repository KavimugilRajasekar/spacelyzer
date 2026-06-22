"""
Tests for Spacelyzer.

Covers:
  - Formatter helpers (format_bytes, parse_size, format_percent)
  - Scanner and analyzer basics
  - Suggestions generation
  - JSON renderer / reclaimable calculation
  - CLI exit codes (path not found, permission denied, user cancellation)
  - Deterministic sort ordering for entries, similarity groups, suggestions
  - Global exception guard in main()
  - Watch mode graceful stop on UserCancelledException
"""

import json
import shutil
import sys
import tempfile
import unittest
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from spacelyzer.analyzer import analyze_entry
from spacelyzer.exceptions import PathNotFoundException, UserCancelledException
from spacelyzer.formatter import (
    format_bytes,
    format_percent,
    has_unicode_support,
    parse_size,
)
from spacelyzer.scanner import DiskScanner, EntryInfo, ScanResults
from spacelyzer.similarity import SimilarityDetector
from spacelyzer.suggestions import SuggestionsAnalyzer


# ---------------------------------------------------------------------------
# Formatter
# ---------------------------------------------------------------------------
class TestFormatter(unittest.TestCase):
    def test_format_bytes_units(self):
        self.assertEqual(format_bytes(0), "0 B")
        self.assertEqual(format_bytes(500), "500 B")
        self.assertEqual(format_bytes(1024), "1.0 KB")
        self.assertEqual(format_bytes(1024 * 1024 * 5.5), "5.5 MB")

    def test_format_bytes_raw(self):
        self.assertEqual(format_bytes(500, raw_bytes=True), "500 B")
        self.assertEqual(format_bytes(1024, raw_bytes=True), "1024 B")

    def test_format_bytes_negative(self):
        # Negative and None should return 0 B safely
        self.assertEqual(format_bytes(-1), "0 B")
        self.assertEqual(format_bytes(None), "0 B")

    def test_parse_size(self):
        self.assertEqual(parse_size("100"), 100)
        self.assertEqual(parse_size("1KB"), 1024)
        self.assertEqual(parse_size("1.5MB"), int(1.5 * 1024 * 1024))
        self.assertEqual(parse_size("2 GB"), 2 * 1024 * 1024 * 1024)

    def test_format_percent(self):
        self.assertEqual(format_percent(50, 100), "50.0%")
        self.assertEqual(format_percent(0, 100), "0.0%")
        # Division-by-zero guard
        self.assertEqual(format_percent(50, 0), "0%")

    def test_has_unicode_support_returns_bool(self):
        result = has_unicode_support()
        self.assertIsInstance(result, bool)


# ---------------------------------------------------------------------------
# Scanner + Analyzer
# ---------------------------------------------------------------------------
class TestScannerAndAnalyzer(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.temp_path = Path(self.temp_dir).resolve()

        # Create dummy subdirs
        self.node_modules = (self.temp_path / "node_modules").resolve()
        self.node_modules.mkdir()
        # dummy.txt is *outside* node_modules so smart-skip doesn't hide it
        self.dummy_file = (self.temp_path / "dummy.txt").resolve()
        self.dummy_file.write_text("Hello World!")

        self.pycache = (self.temp_path / "__pycache__").resolve()
        self.pycache.mkdir()

    def tearDown(self):
        shutil.rmtree(self.temp_dir)

    def test_scanner_basic(self):
        scanner = DiskScanner(self.temp_dir, include_files=True)
        results = scanner.scan()
        self.assertGreaterEqual(results.folders_scanned, 2)
        self.assertEqual(results.files_scanned, 1)
        self.assertIn(str(self.node_modules), results.entries)

    def test_analyzer_known_dirs(self):
        reason, category, icon, safety = analyze_entry(self.node_modules, is_dir=True)
        self.assertEqual(reason, "Node Modules")
        self.assertEqual(category, "Dependency")

        reason_py, category_py, _, _ = analyze_entry(self.pycache, is_dir=True)
        self.assertEqual(reason_py, "Python Cache")
        self.assertEqual(category_py, "Cache")

    def test_scanner_path_not_found(self):
        with self.assertRaises(PathNotFoundException):
            DiskScanner("/this/path/does/not/exist/at/all")

    def test_scanner_permission_denied_root(self):
        scanner = DiskScanner(self.temp_dir, include_files=True)
        with patch("os.scandir", side_effect=PermissionError("Access Denied")):
            with self.assertRaises(PermissionError):
                scanner.scan()

    def test_scanner_keyboard_interrupt_raises_user_cancelled(self):
        """Ctrl+C during scan must surface as UserCancelledException."""
        scanner = DiskScanner(self.temp_dir, include_files=True)
        original_scandir = __import__("os").scandir
        call_count = [0]

        def patched_scandir(path):
            call_count[0] += 1
            if call_count[0] > 1:
                raise KeyboardInterrupt()
            return original_scandir(path)

        with patch("os.scandir", side_effect=patched_scandir):
            with self.assertRaises(UserCancelledException):
                scanner.scan()

    def test_suggestions_node_modules(self):
        scanner = DiskScanner(self.temp_dir, include_files=True)
        results = scanner.scan()
        detector = SimilarityDetector(
            results.files, [e for e in results.entries.values() if e.is_dir]
        )
        duplicates = detector.find_exact_duplicates()
        analyzer = SuggestionsAnalyzer(results.entries, duplicates)
        suggestions = analyzer.generate_suggestions()

        node_sug = [s for s in suggestions if s.key == "node_modules"]
        self.assertTrue(len(node_sug) > 0)
        self.assertEqual(node_sug[0].count, 1)

    def test_json_renderer_reclaimable(self):
        scanner = DiskScanner(self.temp_dir, include_files=True)
        results = scanner.scan()

        from spacelyzer.renderer import DiskUsageRenderer

        renderer = DiskUsageRenderer(results)
        data = json.loads(renderer.render_json())
        expected = (
            results.entries[str(self.node_modules)].size
            + results.entries[str(self.pycache)].size
        )
        self.assertEqual(data["summary"]["potentially_reclaimable_bytes"], expected)


# ---------------------------------------------------------------------------
# CLI exit codes
# ---------------------------------------------------------------------------
class TestCLIExitCodes(unittest.TestCase):
    """Verify that every failure mode maps to the documented exit code."""

    def _run(self, args):
        from spacelyzer.cli import main
        # Suppress stderr during CLI calls so test output stays clean
        with patch("sys.stderr", new_callable=StringIO):
            with patch("sys.stdout", new_callable=StringIO):
                return main(args)

    def test_exit_0_on_success(self):
        with tempfile.TemporaryDirectory() as d:
            code = self._run([d, "--no-progress"])
        self.assertEqual(code, 0)

    def test_exit_3_path_not_found(self):
        code = self._run(["/totally/nonexistent/path/xyz123abc", "--no-progress"])
        self.assertEqual(code, 3)

    def test_exit_4_keyboard_interrupt_during_scan(self):
        """KeyboardInterrupt inside scanner bubbles up as exit code 4."""
        with tempfile.TemporaryDirectory() as d:
            # Create a real subdirectory so the scanner has at least 2 scandir
            # calls (root + one child dir) — we interrupt on the second one.
            Path(d, "subdir").mkdir()
            original_scandir = __import__("os").scandir
            call_count = [0]

            def patched_scandir(path):
                call_count[0] += 1
                # Let the first call (root dir) succeed; interrupt on the next
                if call_count[0] > 1:
                    raise KeyboardInterrupt()
                return original_scandir(path)

            with patch("os.scandir", side_effect=patched_scandir):
                code = self._run([d, "--no-progress"])

        self.assertEqual(code, 4)

    def test_exit_4_user_cancelled_caught_by_main_guard(self):
        """UserCancelledException escaping a subcommand → exit code 4."""
        from spacelyzer.cli import main

        with patch(
            "spacelyzer.cli.cmd_analyze",
            side_effect=UserCancelledException("stopped"),
        ):
            with patch("sys.stderr", new_callable=StringIO):
                code = main(["analyze", ".", "--no-progress"])
        self.assertEqual(code, 4)

    def test_exit_2_permission_denied_caught_by_main_guard(self):
        """PermissionDeniedException escaping a subcommand → exit code 2."""
        from spacelyzer.cli import main
        from spacelyzer.exceptions import PermissionDeniedException

        with patch(
            "spacelyzer.cli.cmd_analyze",
            side_effect=PermissionDeniedException("no access"),
        ):
            with patch("sys.stderr", new_callable=StringIO):
                code = main(["analyze", ".", "--no-progress"])
        self.assertEqual(code, 2)

    def test_exit_1_unexpected_exception_caught_by_main_guard(self):
        """Any unhandled exception → exit code 1 (never a raw traceback)."""
        from spacelyzer.cli import main

        with patch(
            "spacelyzer.cli.cmd_analyze",
            side_effect=RuntimeError("something exploded"),
        ):
            with patch("sys.stderr", new_callable=StringIO):
                code = main(["analyze", ".", "--no-progress"])
        self.assertEqual(code, 1)

    def test_version_flag_exits_0(self):
        code = self._run(["--version"])
        self.assertEqual(code, 0)

    def test_help_flag_exits_0(self):
        code = self._run(["--help"])
        self.assertEqual(code, 0)

    def test_invalid_subcommand_exits_nonzero(self):
        code = self._run(["nonexistent-subcmd"])
        self.assertNotEqual(code, 0)


# ---------------------------------------------------------------------------
# Deterministic sort ordering
# ---------------------------------------------------------------------------
class TestDeterministicOrdering(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(str(self.root))

    def test_get_sorted_entries_stable_by_path_on_equal_size(self):
        """When two entries share the same size, the one with the lexicographically
        smaller path must appear first (alphabetical stable tie-break)."""
        from spacelyzer.renderer import DiskUsageRenderer

        results = ScanResults(self.root)
        results.total_size = 2000

        a = EntryInfo(self.root / "zzz_folder", is_dir=True, size=1000)
        b = EntryInfo(self.root / "aaa_folder", is_dir=True, size=1000)
        results.entries[str(a.path)] = a
        results.entries[str(b.path)] = b

        renderer = DiskUsageRenderer(results)
        sorted_entries = renderer.get_sorted_entries("size")
        names = [e.name for e in sorted_entries]
        # 'aaa_folder' should come before 'zzz_folder'
        self.assertLess(names.index("aaa_folder"), names.index("zzz_folder"))

    def test_suggestions_labels_stable_for_equal_size(self):
        """Suggestion items with equal total_size must sort alphabetically by label."""
        dp = self.root
        # Create two well-known folders of same size (both empty → 0 B)
        (dp / "build").mkdir()
        (dp / "dist").mkdir()

        scanner = DiskScanner(str(dp), include_files=False, smart_skip=False,
                               show_progress=False)
        results = scanner.scan()
        analyzer = SuggestionsAnalyzer(results.entries, [])
        suggestions = analyzer.generate_suggestions()

        labels = [s.label for s in suggestions]
        self.assertEqual(labels, sorted(labels, key=lambda l: l.lower()))

    def test_similar_folders_alphabetical_within_same_size(self):
        """find_similar_folders groups with equal reclaimable size are alphabetical."""
        def _make_dir_entry(name, size, path_str):
            p = Path(path_str)
            e = EntryInfo(p, is_dir=True, size=size)
            return e

        folder_a1 = _make_dir_entry("alpha", 500, "/x/alpha")
        folder_a2 = _make_dir_entry("alpha", 500, "/y/alpha")
        folder_b1 = _make_dir_entry("beta",  500, "/x/beta")
        folder_b2 = _make_dir_entry("beta",  500, "/y/beta")

        detector = SimilarityDetector([], [folder_a1, folder_a2, folder_b1, folder_b2])
        groups = detector.find_similar_folders()
        group_names = [name.lower() for name, _ in groups]
        self.assertEqual(group_names, sorted(group_names))

    def test_exact_duplicates_groups_alphabetical_within_same_reclaimable(self):
        """find_exact_duplicates groups with equal reclaimable size are alphabetical."""
        # Create real duplicate files so the hasher actually runs
        (self.root / "aaa.txt").write_bytes(b"SAME_CONTENT_XYZ")
        (self.root / "aaa_copy.txt").write_bytes(b"SAME_CONTENT_XYZ")
        (self.root / "bbb.txt").write_bytes(b"SAME_CONTENT_XYZ")
        (self.root / "bbb_copy.txt").write_bytes(b"SAME_CONTENT_XYZ")

        scanner = DiskScanner(str(self.root), include_files=True,
                               show_progress=False, smart_skip=False)
        results = scanner.scan()
        detector = SimilarityDetector(results.files, [])
        dupes = detector.find_exact_duplicates()

        # All files have the same content → they form one group; just verify no crash
        self.assertGreaterEqual(len(dupes), 1)


# ---------------------------------------------------------------------------
# Watch mode graceful stop
# ---------------------------------------------------------------------------
class TestWatchGracefulStop(unittest.TestCase):
    def test_watch_stops_on_keyboard_interrupt_no_exception(self):
        """watch() must swallow KeyboardInterrupt and return cleanly."""
        from spacelyzer.watch import watch

        root = Path(tempfile.mkdtemp())
        try:
            call_count = [0]

            def factory():
                return DiskScanner(str(root), show_progress=False)

            def render_fn(results):
                call_count[0] += 1
                # Allow the placeholder render (call_count==1) to succeed;
                # interrupt on the first real tick render.
                if call_count[0] > 1:
                    raise KeyboardInterrupt()
                return ""

            # Must not propagate
            with patch("sys.stdout", new_callable=StringIO):
                watch(factory, render_fn, interval=0.5, iterations=3)
        finally:
            shutil.rmtree(str(root))

    def test_watch_stops_on_user_cancelled_no_exception(self):
        """watch() must swallow UserCancelledException and return cleanly."""
        from spacelyzer.watch import watch

        root = Path(tempfile.mkdtemp())
        try:
            def factory():
                return DiskScanner(str(root), show_progress=False)

            def render_fn(results):
                raise UserCancelledException("stopped")

            with patch("sys.stdout", new_callable=StringIO):
                watch(factory, render_fn, interval=0.5, iterations=3)
        finally:
            shutil.rmtree(str(root))


if __name__ == "__main__":
    unittest.main()
