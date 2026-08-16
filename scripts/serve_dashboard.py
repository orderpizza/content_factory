"""Serve the read-only Scout dashboard locally."""

import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from database.sqlite import Database
from dashboard import render_dashboard


class DashboardHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        database = Database(os.getenv("CONTENT_FACTORY_DB_PATH", "data/content.db"))
        database.initialize()
        try:
            body = render_dashboard(database).encode("utf-8")
        finally:
            database.close()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        return


def main():
    host = os.getenv("CONTENT_FACTORY_DASHBOARD_HOST", "127.0.0.1")
    port = int(os.getenv("CONTENT_FACTORY_DASHBOARD_PORT", "8765"))
    server = ThreadingHTTPServer((host, port), DashboardHandler)
    print(f"Dashboard: http://{host}:{port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
