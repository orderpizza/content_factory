"""Serve the read-only detection dashboard locally."""

import os
import sqlite3
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from html import escape
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from common.environment import load_environment_file
from database.migrations import SchemaError, connect, validate_detection_dashboard
from dashboard import render_detection_dashboard


ROOT = Path(__file__).resolve().parents[1]


class DashboardHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        request = urlsplit(self.path)
        if request.path != "/":
            self.send_error(404)
            return
        try:
            parameters = parse_qs(
                request.query, keep_blank_values=False, max_num_fields=10
            )
        except ValueError:
            parameters = {}
        try:
            page = int(parameters.get("page", ["1"])[0])
        except ValueError:
            page = 1
        database_path = os.getenv(
            "CONTENT_FACTORY_DB_PATH", str(ROOT / "data" / "content.db")
        )
        try:
            connection = connect(database_path, read_only=True)
            try:
                validate_detection_dashboard(connection)
                body = render_detection_dashboard(
                    connection,
                    query=parameters.get("q", [""])[0],
                    source=parameters.get("source", [""])[0],
                    status=parameters.get("status", [""])[0],
                    page=page,
                ).encode("utf-8")
            finally:
                connection.close()
            status = 200
        except (OSError, sqlite3.Error, SchemaError) as error:
            body = (
                "<!doctype html><meta charset='utf-8'><title>Setup required</title>"
                "<h1>Detection dashboard setup required</h1>"
                f"<p>{escape(str(error))}</p>"
                "<p>Run <code>py scripts/setup_detection.py</code> explicitly.</p>"
            ).encode("utf-8")
            status = 503
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'none'; style-src 'unsafe-inline'; img-src https: data:; "
            "frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
        )
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        return


def main():
    load_environment_file(ROOT / ".env")
    host = os.getenv("CONTENT_FACTORY_DASHBOARD_HOST", "127.0.0.1")
    port = int(os.getenv("CONTENT_FACTORY_DASHBOARD_PORT", "8787"))
    if host not in {"127.0.0.1", "::1", "localhost"}:
        raise SystemExit("Dashboard host must be loopback-only in the local POC")
    if not 1 <= port <= 65535:
        raise SystemExit("Dashboard port must be between 1 and 65535")
    server = ThreadingHTTPServer((host, port), DashboardHandler)
    print(f"Dashboard: http://{host}:{port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
