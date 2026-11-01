"""End-to-end Streamlit UI check, especially on Windows Python 3.13.

This catches crashes that the HTTP-only health check cannot detect.
Runs entirely offline with intentionally synthetic demo data.
"""
import unittest
from pathlib import Path

APP_PATH = Path(__file__).resolve().parents[1] / 'bot' / 'dashboard' / 'app.py'

from streamlit.testing.v1 import AppTest


class TestPaperDashboardWindows(unittest.TestCase):
    def test_empty_evidence_renders_without_exception(self):
        app = AppTest.from_file(str(APP_PATH), default_timeout=45).run()
        self.assertEqual([], list(app.exception))

    def test_explicitly_synthetic_demo_renders_without_exception(self):
        app = AppTest.from_file(str(APP_PATH), default_timeout=45).run()
        self.assertEqual([], list(app.exception))
        app.sidebar.toggle[0].set_value(True).run()
        self.assertEqual([], list(app.exception))


if __name__ == "__main__":
    unittest.main()
