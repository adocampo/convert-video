import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from clutch.logs import _read_log_entries


SAMPLE_LOG = """\
2026-04-20T10:00:01 [DEBUG] clutch: Starting watcher loop
2026-04-20T10:00:02 [INFO] clutch: Watching /media/videos
2026-04-20T10:00:03 [INFO] converter: Processing file.mkv
2026-04-20T10:00:04 [DEBUG] converter: Probing streams
2026-04-20T10:00:05 [WARNING] converter: Low disk space on /tmp
2026-04-20T10:00:06 [ERROR] converter: ffmpeg exited with code 1
2026-04-20T10:00:07 [INFO] clutch: Job queued for retry
2026-04-20T10:00:08 [CRITICAL] clutch: Unrecoverable failure
2026-04-20T10:00:09 [DEBUG] scheduler: Next run in 300s
2026-04-20T10:00:10 [INFO] watcher: Scan complete
"""


class TestLogFiltering(unittest.TestCase):
    """Test that the log level filter uses exact matching (not hierarchical)."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.logfile = os.path.join(self.tmpdir, "clutch.log")
        with open(self.logfile, "w") as f:
            f.write(SAMPLE_LOG)

    def tearDown(self):
        os.remove(self.logfile)
        os.rmdir(self.tmpdir)

    def _read(self, **kwargs):
        with patch("clutch.output.get_log_dir", return_value=self.tmpdir):
            return _read_log_entries(**kwargs)

    # ── No filter: returns all entries ──

    def test_no_filter_returns_all(self):
        result = self._read()
        self.assertEqual(result["total"], 10)

    # ── Exact level filtering ──

    def test_filter_debug_returns_only_debug(self):
        result = self._read(level="DEBUG")
        levels = {e["level"] for e in result["entries"]}
        self.assertEqual(levels, {"DEBUG"})
        self.assertEqual(result["total"], 3)

    def test_filter_info_returns_only_info(self):
        result = self._read(level="INFO")
        levels = {e["level"] for e in result["entries"]}
        self.assertEqual(levels, {"INFO"})
        self.assertEqual(result["total"], 4)

    def test_filter_warning_returns_only_warning(self):
        result = self._read(level="WARNING")
        levels = {e["level"] for e in result["entries"]}
        self.assertEqual(levels, {"WARNING"})
        self.assertEqual(result["total"], 1)

    def test_filter_error_returns_only_error(self):
        result = self._read(level="ERROR")
        levels = {e["level"] for e in result["entries"]}
        self.assertEqual(levels, {"ERROR"})
        self.assertEqual(result["total"], 1)

    def test_filter_critical_returns_only_critical(self):
        result = self._read(level="CRITICAL")
        levels = {e["level"] for e in result["entries"]}
        self.assertEqual(levels, {"CRITICAL"})
        self.assertEqual(result["total"], 1)

    # ── Case insensitivity of filter parameter ──

    def test_filter_level_case_insensitive(self):
        result = self._read(level="error")
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["entries"][0]["level"], "ERROR")

    # ── Search combined with level ──

    def test_search_combined_with_level(self):
        result = self._read(level="INFO", search="watcher")
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["entries"][0]["source"], "watcher")

    # ── Search alone ──

    def test_search_alone(self):
        result = self._read(search="ffmpeg")
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["entries"][0]["level"], "ERROR")

    # ── Pagination ──

    def test_pagination(self):
        result = self._read(page=1, limit=3)
        self.assertEqual(result["total"], 10)
        self.assertEqual(len(result["entries"]), 3)
        # Newest first
        self.assertEqual(result["entries"][0]["timestamp"], "2026-04-20T10:00:10")

    def test_pagination_page_two(self):
        result = self._read(page=2, limit=3)
        self.assertEqual(len(result["entries"]), 3)

    # ── Empty / missing file ──

    def test_missing_file_returns_empty(self):
        with patch("clutch.output.get_log_dir", return_value="/nonexistent"):
            result = _read_log_entries()
        self.assertEqual(result["entries"], [])
        self.assertEqual(result["total"], 0)

    # ── Reverse chronological order ──

    def test_entries_are_newest_first(self):
        result = self._read()
        timestamps = [e["timestamp"] for e in result["entries"]]
        self.assertEqual(timestamps, sorted(timestamps, reverse=True))

    # ── Field parsing ──

    def test_entry_fields_parsed_correctly(self):
        result = self._read(level="ERROR")
        entry = result["entries"][0]
        self.assertEqual(entry["timestamp"], "2026-04-20T10:00:06")
        self.assertEqual(entry["level"], "ERROR")
        self.assertEqual(entry["source"], "converter")
        self.assertIn("ffmpeg", entry["message"])


if __name__ == "__main__":
    unittest.main()
