"""Explicit migrations for the target detection/dashboard milestone."""

from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
import sqlite3


SCHEMA_VERSION = 1
MIGRATION_NAME = "detection_dashboard_schema_v1"
ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = ROOT / "docs" / "contracts" / "detection-dashboard-schema-v1.sql"


class SchemaError(RuntimeError):
    """Raised when a database cannot safely satisfy the expected schema."""


def contract_bytes() -> bytes:
    return CONTRACT_PATH.read_bytes()


def contract_checksum() -> str:
    return sha256(contract_bytes()).hexdigest()


def connect(path: str | Path, *, read_only: bool = False) -> sqlite3.Connection:
    database_path = Path(path).resolve()
    if read_only:
        connection = sqlite3.connect(
            f"file:{database_path.as_posix()}?mode=ro",
            uri=True,
            timeout=5,
        )
    else:
        connection = sqlite3.connect(database_path, timeout=5)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 5000")
    return connection


def _application_tables(connection: sqlite3.Connection) -> list[str]:
    return [
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
    ]


def migrate_detection_dashboard(path: str | Path) -> bool:
    """Apply schema v1 once; return True only when a migration was applied."""

    database_path = Path(path).resolve()
    database_path.parent.mkdir(parents=True, exist_ok=True)
    connection = connect(database_path)
    try:
        version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        if version == SCHEMA_VERSION:
            validate_detection_dashboard(connection)
            return False
        if version != 0:
            raise SchemaError(
                f"Unsupported database schema version {version}; expected 0 or {SCHEMA_VERSION}."
            )
        tables = _application_tables(connection)
        if tables:
            raise SchemaError(
                "Database has unversioned/legacy tables and will not be changed implicitly: "
                + ", ".join(tables)
            )

        checksum = contract_checksum()
        applied_at = datetime.now(timezone.utc).isoformat()
        migration_sql = contract_bytes().decode("utf-8")
        escaped_name = MIGRATION_NAME.replace("'", "''")
        script = (
            "BEGIN EXCLUSIVE;\n"
            + migration_sql
            + "\nINSERT INTO schema_migrations "
            + "(version, name, checksum, applied_at) VALUES "
            + f"({SCHEMA_VERSION}, '{escaped_name}', '{checksum}', '{applied_at}');\n"
        )
        try:
            connection.executescript(script)
            violations = connection.execute("PRAGMA foreign_key_check").fetchall()
            if violations:
                raise SchemaError(
                    f"Migration foreign-key check failed: {len(violations)} violation(s)."
                )
            connection.commit()
        except Exception:
            if connection.in_transaction:
                connection.rollback()
            raise
        validate_detection_dashboard(connection)
        return True
    finally:
        connection.close()


def validate_detection_dashboard(connection: sqlite3.Connection) -> None:
    version = int(connection.execute("PRAGMA user_version").fetchone()[0])
    if version != SCHEMA_VERSION:
        raise SchemaError(
            f"Database schema version is {version}; expected {SCHEMA_VERSION}. "
            "Run the explicit setup command."
        )
    try:
        row = connection.execute(
            "SELECT name, checksum FROM schema_migrations WHERE version = ?",
            (SCHEMA_VERSION,),
        ).fetchone()
    except sqlite3.Error as error:
        raise SchemaError("Database does not contain the required migration ledger.") from error
    if row is None or row["name"] != MIGRATION_NAME:
        raise SchemaError("Database migration identity does not match the expected contract.")
    if row["checksum"] != contract_checksum():
        raise SchemaError(
            "Database migration checksum differs from the canonical SQL contract."
        )
    violations = connection.execute("PRAGMA foreign_key_check").fetchall()
    if violations:
        raise SchemaError(f"Database foreign-key check failed: {len(violations)} violation(s).")
