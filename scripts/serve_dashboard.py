"""Serve the loopback-only dashboard and persisted human workflow commands."""

from argparse import ArgumentParser
from hashlib import sha256
import os
import sqlite3
import socket
import sys
import secrets
import json
from datetime import datetime, timezone
from time import monotonic
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from html import escape
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from common.environment import load_environment_file
from common.operation_log import configure_logging, emit, refusal_code
from database.current import SCHEMA_VERSION, SchemaError, connect, validate_database
from dashboard import render_detection_dashboard, render_workflow_trace
from dashboard.detection import AUTO_REFRESH_CSP
from dashboard.evidence import render_candidate, render_evaluation, render_queue_status
from dashboard.flow import render_raw_item, render_job
from workflow import WorkflowStore


ROOT = Path(__file__).resolve().parents[1]


class DashboardHandler(BaseHTTPRequestHandler):
    database_path = str(ROOT / "data" / "development.db")
    artifact_root = (ROOT / "data" / "artifacts").resolve()
    csrf_token = secrets.token_urlsafe(32)

    def do_GET(self):
        request = urlsplit(self.path)
        if request.path == "/asset":
            self._serve_asset(request.query)
            return
        if request.path not in {"/", "/snapshot"}:
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
        try:
            connection = connect(self.database_path, read_only=True)
            try:
                connection.execute("BEGIN")
                # Validate ledger/version on every snapshot; avoid rescanning all
                # retained evidence FKs every ten-second browser refresh.
                validate_database(connection, check_foreign_keys=False)
                body = render_detection_dashboard(
                    connection,
                    query=parameters.get("q", [""])[0],
                    source=parameters.get("source", [""])[0],
                    status=parameters.get("status", [""])[0],
                    page=page,
                    opportunity_page=self._query_int(parameters,'opportunity_page',1),
                    job_page=self._query_int(parameters,'job_page',1),
                )
                base_page = body
                view = parameters.get('view', ['overview'])[0]
                if any(key in parameters for key in ('thread_id', 'thread_page', 'revision_page', 'message_page')):
                    view = 'threads'
                if view in {'overview', 'threads'}:
                    workflow = render_workflow_trace(
                        connection,
                        interactive=True,
                        csrf_token=self.csrf_token,
                        thread_id=self._query_int(parameters, "thread_id", None),
                        thread_page=self._query_int(parameters, "thread_page", 1),
                        revision_page=self._query_int(parameters, "revision_page", 1),
                        message_page=self._query_int(parameters, "message_page", 1),
                    )
                    notice = parameters.get("notice", [""])[0]
                    if notice:
                        workflow = f"<p role='status'>{escape(notice)}</p>" + workflow
                    body = body.replace("</main>", workflow + "</main>", 1)
                queues = render_queue_status(connection)
                detail = ''
                for name, renderer in (("cluster_id", render_candidate), ("candidate_id", render_candidate), ("raw_item_id",render_raw_item), ("job_id",render_job), ("evaluation_id", render_evaluation)):
                    identity = self._query_int(parameters, name, None)
                    if identity:
                        detail += renderer(connection, identity)
                database_label = f"<p class='hint'>Database: {escape(self.database_path)} · schema {SCHEMA_VERSION}</p>"
                body = body.replace("<div id='detail-slot'></div>", database_label + detail)
                body = body.replace("<div class='operations' id='operations'>", queues + "<div class='operations' id='operations'>", 1)
                if view in {'threads', 'operations'}:
                    head, _, main = base_page.partition('<main>')
                    header = main.partition("<div id='detail-slot'></div>")[0]
                    if view == 'threads':
                        content = workflow
                    else:
                        operations = main.partition("<div class='operations' id='operations'>")[2].partition('</main>')[0]
                        content = queues + detail + "<div class='operations' id='operations'>" + operations
                    body = head + '<main>' + header + database_label + content + '</main></body></html>'
                if request.path == '/snapshot':
                    fragment = '<main>' + body.partition('<main>')[2].partition('</main>')[0] + '</main>'
                    body = json.dumps({'html': fragment, 'updated_at': datetime.now(timezone.utc).isoformat()}, ensure_ascii=False)
                body = body.encode("utf-8")
                if request.path == '/snapshot' and len(body) > 8000000:
                    raise ValueError('Dashboard snapshot exceeds 8 MB; narrow the view or thread.')
            finally:
                connection.rollback()
                connection.close()
            status = 200
        except (OSError, sqlite3.Error, SchemaError, ValueError) as error:
            body = (
                "<!doctype html><meta charset='utf-8'><title>Setup required</title>"
                "<h1>Detection dashboard setup required</h1>"
                f"<p>{escape(str(error))}</p>"
                "<p>Run <code>.venv/bin/python scripts/setup_development.py --database &lt;path&gt;</code> explicitly.</p>"
            ).encode("utf-8")
            status = 503
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8" if request.path == '/snapshot' and status == 200 else "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'none'; connect-src 'self'; style-src 'unsafe-inline'; img-src 'self' data:; "
            f"script-src {AUTO_REFRESH_CSP}; "
            "frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
        )
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        self._command_kind = None
        request = urlsplit(self.path)
        if request.path != "/commands":
            self.send_error(404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if not 1 <= length <= 100000:
            self.send_error(413, "Command body must contain 1-100,000 bytes")
            return
        if not self.headers.get("Content-Type", "").startswith("application/x-www-form-urlencoded"):
            self.send_error(415, "Commands require form encoding")
            return
        try:
            values = parse_qs(
                self.rfile.read(length).decode("utf-8"),
                keep_blank_values=True,
                max_num_fields=20,
                strict_parsing=True,
            )
            supplied_token = self._one(values, "csrf_token")
            if not secrets.compare_digest(supplied_token, self.csrf_token):
                raise ValueError("invalid or expired dashboard command token")
            command_kind = self._one(values, "command_kind")
            self._command_kind = command_kind if command_kind in {'new_idea','continue_thread','review_changes','review_approved','review_rejected','post_now','cancel_delivery','request_reconciliation','resolve_reconciliation'} else 'unsupported'
            command_id = self._one(values, "command_id")
            redirect_thread = None
            with WorkflowStore(self.database_path, enforce_storage=True) as store:
                if command_kind == "new_idea":
                    record_id = store.create_human_idea(
                        self._one(values, "body"), command_id=command_id
                    )
                    notice = f"Idea accepted as Intake request #{record_id}."
                elif command_kind == "continue_thread":
                    record_id = store.continue_human_thread(
                        self._integer(values, "thread_id"),
                        self._one(values, "body"),
                        command_id=command_id,
                        expected_row_version=self._integer(values, "row_version"),
                    )
                    notice = f"Reply accepted as Intake request #{record_id}."
                elif command_kind in {"review_approved", "review_rejected"}:
                    decision = "approved" if command_kind == "review_approved" else "rejected"
                    record_id = store.decide_review(
                        self._integer(values, "review_id"),
                        decision=decision,
                        note=self._one(values, "note", required=False),
                        row_version=self._integer(values, "row_version"),
                        command_id=command_id,
                    )
                    notice = f"Preview #{record_id} recorded as {decision}; delivery remains disabled."
                elif command_kind == "post_now":
                    record_id = store.authorize_post_now(
                        self._integer(values, "review_id"),
                        row_version=self._integer(values, "row_version"),
                        command_id=command_id,
                    )
                    notice = f"Post now authorization created delivery record #{record_id}."
                elif command_kind == "review_changes":
                    record_id = store.request_review_changes(
                        self._integer(values, "review_id"),
                        note=self._one(values, "note"),
                        row_version=self._integer(values, "row_version"),
                        command_id=command_id,
                    )
                    notice = f"Changes queued as Intake request #{record_id}."
                elif command_kind == "cancel_delivery":
                    record_id = store.cancel_delivery(
                        self._integer(values, "post_record_id"),
                        row_version=self._integer(values, "row_version"),
                        command_id=command_id,
                    )
                    notice = f"Delivery #{record_id} cancelled before final publication."
                elif command_kind == "request_reconciliation":
                    record_id = store.request_publication_reconciliation(
                        self._integer(values, "post_record_id"), command_id=command_id,
                    )
                    notice = f"Reconciliation request #{record_id} queued; no retry was authorized."
                elif command_kind == "resolve_reconciliation":
                    record_id = store.resolve_publication_unknown(
                        self._integer(values, "reconciliation_request_id"),
                        reconciliation_check_id=self._integer(values, "reconciliation_check_id"),
                        decision=self._one(values, "decision"),
                        note=self._one(values, "note"),
                        row_version=self._integer(values, "row_version"),
                        command_id=command_id,
                    )
                    notice = f"Reconciliation #{record_id} recorded; no publication call was made."
                else:
                    raise ValueError("unsupported dashboard command")
                if command_kind in {"new_idea", "continue_thread", "review_changes"}:
                    redirect_thread = store.connection.execute("SELECT thread_id FROM intake_requests WHERE intake_request_id=?", (record_id,)).fetchone()[0]
        except (UnicodeDecodeError, ValueError, RuntimeError, sqlite3.Error, SchemaError) as error:
            self._command_error(error)
            return
        from urllib.parse import urlencode
        self.send_response(303)
        self.send_header("Location", "/?" + urlencode({"notice": notice, **({"thread_id": redirect_thread} if redirect_thread else {})}))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

    @staticmethod
    def _query_int(parameters, name, default):
        try:
            value = int(parameters.get(name, [default])[0])
            return value if 1 <= value <= 100000000 else default
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _one(values, name: str, *, required: bool = True) -> str:
        items = values.get(name, [])
        if len(items) > 1 or (required and len(items) != 1):
            raise ValueError(f"command field {name} is missing or repeated")
        return "" if not items else items[0]

    @classmethod
    def _integer(cls, values, name: str) -> int:
        try:
            value = int(cls._one(values, name))
        except (TypeError, ValueError) as error:
            raise ValueError(f"command field {name} must be an integer") from error
        if value < 1:
            raise ValueError(f"command field {name} must be positive")
        return value

    def _command_error(self, error: Exception) -> None:
        emit('dashboard', 'command_refused', command_kind=self._command_kind,
             status='refused', error_type=type(error).__name__, error_code=refusal_code(error))
        body = (
            "<!doctype html><meta charset='utf-8'><title>Command refused</title>"
            "<h1>Dashboard command refused</h1>"
            f"<p>{escape(str(error))}</p><p><a href='/'>Return to dashboard</a></p>"
        ).encode("utf-8")
        self.send_response(400)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _serve_asset(self, query: str) -> None:
        try:
            parameters = parse_qs(query, max_num_fields=2, strict_parsing=True)
            asset_id = self._integer(parameters, "render_asset_id")
            connection = connect(self.database_path, read_only=True)
            try:
                row = connection.execute(
                    "SELECT local_path,mime_type,bytes,sha256 FROM render_assets WHERE render_asset_id=? "
                    "AND asset_role IN ('preview_png','delivery_jpeg')",
                    (asset_id,),
                ).fetchone()
            finally:
                connection.close()
            if row is None or row["mime_type"] not in {"image/png", "image/jpeg"}:
                raise FileNotFoundError("review asset does not exist")
            path = Path(row["local_path"]).resolve(strict=True)
            if not path.is_relative_to(self.artifact_root):
                raise PermissionError("review asset is outside the configured artifact root")
            if path.stat().st_size != int(row["bytes"]) or int(row["bytes"]) > 20_000_000:
                raise ValueError("review asset size does not match its manifest")
            data = path.read_bytes()
            if sha256(data).hexdigest() != row["sha256"]:
                raise ValueError("review asset hash does not match its manifest")
        except (OSError, ValueError, sqlite3.Error, SchemaError):
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", row["mime_type"])
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "private, max-age=300")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format, *args):
        return

    def handle_one_request(self):
        start = monotonic()
        self._response_status = None
        try:
            return super().handle_one_request()
        finally:
            if self._response_status is not None:
                path = urlsplit(self.path).path
                emit('dashboard', 'http', method=self.command,
                     path=path if path in {'/', '/snapshot', '/commands', '/asset'} else '/unknown',
                     http_status=self._response_status, duration_ms=round((monotonic()-start)*1000))

    def send_response(self, code, message=None):
        self._response_status = code
        return super().send_response(code, message)


def main():
    load_environment_file(ROOT / ".env")
    parser = ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database",
        default=os.getenv("CONTENT_FACTORY_DB_PATH", str(ROOT / "data" / "development.db")),
    )
    parser.add_argument(
        "--artifacts",
        default=os.getenv("CONTENT_FACTORY_ARTIFACT_ROOT", str(ROOT / "data" / "artifacts")),
    )
    parser.add_argument("--host", default=os.getenv("CONTENT_FACTORY_DASHBOARD_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("CONTENT_FACTORY_DASHBOARD_PORT", "8787")))
    args = parser.parse_args()
    configure_logging('dashboard')
    host = args.host
    port = args.port
    if host not in {"127.0.0.1", "::1", "localhost"}:
        raise SystemExit("Dashboard host must be loopback-only in the local POC")
    if not 1 <= port <= 65535:
        raise SystemExit("Dashboard port must be between 1 and 65535")
    class LoopbackServer(ThreadingHTTPServer):
        address_family = socket.AF_INET6 if host == "::1" else socket.AF_INET
    DashboardHandler.database_path = str(Path(args.database).resolve())
    DashboardHandler.artifact_root = Path(args.artifacts).resolve()
    server = LoopbackServer((host, port), DashboardHandler)
    print(f"Dashboard: http://{'[' + host + ']' if ':' in host else host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Dashboard stopped.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
