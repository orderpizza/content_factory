import tempfile
import unittest
from pathlib import Path
from urllib.request import urlopen
from threading import Thread
from http.server import ThreadingHTTPServer

from common.models import TrendCandidate
from database.sqlite import Database
from intelligence.dashboard import render_dashboard


class LiveDashboardTests(unittest.TestCase):
    def test_dashboard_contains_auto_refresh(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory) / "content.db")
            database.initialize()
            html = render_dashboard(database)
            database.close()

        self.assertIn("http-equiv='refresh'", html)
        self.assertIn("content='15'", html)

