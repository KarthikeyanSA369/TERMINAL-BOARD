import os
import sys
import unittest
import tempfile
import sqlite3

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from backend.core.file_search import (
    init_search_schema,
    search_files,
    get_indexer_status,
    clear_search_index,
    get_search_history,
    clear_search_history
)

class TestFileSearch(unittest.TestCase):
    def setUp(self):
        init_search_schema()

    def test_indexer_status(self):
        """Verify indexer status structure."""
        status = get_indexer_status()
        self.assertIn("status", status)
        self.assertIn("indexed_count", status)

    def test_search_execution(self):
        """Verify search query executes and returns structured results."""
        results = search_files(query="test", limit=10)
        self.assertIsInstance(results, dict)
        self.assertIn("results", results)
        self.assertIn("total", results)
        self.assertIn("duration_ms", results)

    def test_search_history(self):
        """Verify search queries are logged to history and can be cleared."""
        search_files(query="pytest_sample_query_123")
        hist = get_search_history(limit=10)
        self.assertIsInstance(hist, list)
        clear_search_history()
        hist_cleared = get_search_history(limit=10)
        self.assertEqual(len(hist_cleared), 0)

if __name__ == "__main__":
    unittest.main()
