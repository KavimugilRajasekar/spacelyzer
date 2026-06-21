import unittest
import tempfile
import shutil
from pathlib import Path
from spacelyzer.formatter import format_bytes, parse_size, format_percent
from spacelyzer.scanner import DiskScanner
from spacelyzer.analyzer import analyze_entry
from spacelyzer.similarity import SimilarityDetector
from spacelyzer.suggestions import SuggestionsAnalyzer

class TestFormatter(unittest.TestCase):
    def test_format_bytes(self):
        self.assertEqual(format_bytes(500), "500 B")
        self.assertEqual(format_bytes(1024), "1.0 KB")
        self.assertEqual(format_bytes(1024 * 1024 * 5.5), "5.5 MB")
        self.assertEqual(format_bytes(500, raw_bytes=True), "500 B")
        
    def test_parse_size(self):
        self.assertEqual(parse_size("100"), 100)
        self.assertEqual(parse_size("1KB"), 1024)
        self.assertEqual(parse_size("1.5MB"), 1.5 * 1024 * 1024)
        self.assertEqual(parse_size("2 GB"), 2 * 1024 * 1024 * 1024)
        
    def test_format_percent(self):
        self.assertEqual(format_percent(50, 100), "50.0%")
        self.assertEqual(format_percent(0, 100), "0.0%")

class TestScannerAndAnalyzer(unittest.TestCase):
    def setUp(self):
        # Create a temp directory structure
        self.temp_dir = tempfile.mkdtemp()
        self.temp_path = Path(self.temp_dir).resolve()
        
        # Create dummy subdirs
        self.node_modules = (self.temp_path / "node_modules").resolve()
        self.node_modules.mkdir()
        self.dummy_file = (self.node_modules / "dummy.txt").resolve()
        self.dummy_file.write_text("Hello World!")
        
        self.pycache = (self.temp_path / "__pycache__").resolve()
        self.pycache.mkdir()
        
    def tearDown(self):
        shutil.rmtree(self.temp_dir)
        
    def test_scanner(self):
        scanner = DiskScanner(self.temp_dir, include_files=True)
        results = scanner.scan()
        
        self.assertTrue(results.folders_scanned >= 2)
        self.assertEqual(results.files_scanned, 1)
        self.assertTrue(str(self.node_modules) in results.entries)
        
    def test_analyzer(self):
        reason, category, icon, safety = analyze_entry(self.node_modules, is_dir=True)
        self.assertEqual(reason, "Node Modules")
        self.assertEqual(category, "Dependency")
        
        reason_py, category_py, icon_py, safety_py = analyze_entry(self.pycache, is_dir=True)
        self.assertEqual(reason_py, "Python Cache")
        self.assertEqual(category_py, "Cache")
        
    def test_suggestions(self):
        scanner = DiskScanner(self.temp_dir, include_files=True)
        results = scanner.scan()
        
        detector = SimilarityDetector(results.files, [e for e in results.entries.values() if e.is_dir])
        duplicates = detector.find_exact_duplicates()
        
        analyzer = SuggestionsAnalyzer(results.entries, duplicates)
        suggestions = analyzer.generate_suggestions()
        
        # Check if node_modules suggestion is present
        node_modules_sug = [s for s in suggestions if s.key == 'node_modules']
        self.assertTrue(len(node_modules_sug) > 0)
        self.assertEqual(node_modules_sug[0].count, 1)

    def test_json_renderer_reclaimable(self):
        scanner = DiskScanner(self.temp_dir, include_files=True)
        results = scanner.scan()
        
        from spacelyzer.renderer import DiskUsageRenderer
        import json
        renderer = DiskUsageRenderer(results)
        json_str = renderer.render_json()
        data = json.loads(json_str)
        
        # Verify both node_modules and __pycache__ are included in reclaimable size
        expected_reclaimable = results.entries[str(self.node_modules)].size + results.entries[str(self.pycache)].size
        self.assertEqual(data["summary"]["potentially_reclaimable_bytes"], expected_reclaimable)

    def test_scanner_permission_denied_root(self):
        from unittest.mock import patch
        scanner = DiskScanner(self.temp_dir, include_files=True)
        with patch('os.scandir', side_effect=PermissionError("Access Denied")):
            with self.assertRaises(PermissionError):
                scanner.scan()

if __name__ == '__main__':
    unittest.main()
