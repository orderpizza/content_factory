"""Explicit fresh-database initialization and fail-closed current-schema checks."""

from hashlib import sha256
from pathlib import Path
import sqlite3
from common.timestamps import serialize_timestamp, utc_now
from content_factory_resources import contract_path

SCHEMA_VERSION = 8
CONTRACT_PATH = contract_path("application-schema.sql")
SCHEMA_NAME = "content_factory_application"
LEGACY_V7_CHECKSUM = "3ca7f26a4c3372222df2b9a77a9618db68f7fa15f03a16070b693c0a8dfa7e0f"


class SchemaError(RuntimeError):
    pass


def contract_checksum():
    return sha256(CONTRACT_PATH.read_bytes()).hexdigest()


def connect(path, *, read_only=False):
    path = Path(path).resolve()
    connection = sqlite3.connect(f"{path.as_uri()}?mode=ro" if read_only else path,
                                uri=read_only, timeout=5)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("PRAGMA busy_timeout=5000")
    return connection


def validate_database(connection, *, check_foreign_keys=True):
    if connection.execute("PRAGMA user_version").fetchone()[0] != SCHEMA_VERSION:
        raise SchemaError("Current schema 8 required; run the explicit timestamp migration or create a fresh database")
    try:
        rows = connection.execute("SELECT version,name,checksum FROM schema_migrations").fetchall()
        if len(rows) != 1 or tuple(rows[0]) != (SCHEMA_VERSION, SCHEMA_NAME, contract_checksum()):
            raise SchemaError("Database schema identity/checksum does not match the current contract")
    except sqlite3.Error as error:
        raise SchemaError("Database schema ledger is missing or invalid") from error
    if check_foreign_keys and connection.execute("PRAGMA foreign_key_check").fetchall():
        raise SchemaError("Database foreign-key check failed")


TIMESTAMP_COLUMNS = {
    "applied_at", "created_at", "updated_at", "activated_at", "superseded_at",
    "scheduled_for", "provider_time", "collected_at", "claimed_at", "lease_expires_at",
    "next_attempt_at", "completed_at", "reserved_at", "window_start", "window_end",
    "first_observed_at", "last_observed_at", "effective_observed_at", "evaluation_slot_start",
    "input_frozen_at", "cooldown_until", "selected_at", "first_seen_at", "last_seen_at",
    "closed_at", "cancelled_at", "started_at", "expires_at", "decided_at", "eligible_at",
    "published_at", "publication_unknown_at", "settled_at", "approved_at", "checked_at",
    "valid_until", "final_publication_request_sent_at", "sampled_at", "deleted_at",
}


def _normalize_timestamp_columns(connection: sqlite3.Connection) -> None:
    """Normalize every native timestamp column without changing its instant."""
    tables = connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    for table_row in tables:
        table = str(table_row[0])
        columns = {
            str(row[1]) for row in connection.execute(f'PRAGMA table_info("{table}")')
            if str(row[1]) in TIMESTAMP_COLUMNS
        }
        for column in columns:
            rows = connection.execute(
                f'SELECT rowid, "{column}" FROM "{table}" WHERE "{column}" IS NOT NULL'
            ).fetchall()
            for rowid, value in rows:
                try:
                    normalized = serialize_timestamp(str(value))
                except (TypeError, ValueError) as error:
                    raise SchemaError(f"Cannot normalize {table}.{column} timestamp") from error
                if normalized != value:
                    connection.execute(
                        f'UPDATE "{table}" SET "{column}"=? WHERE rowid=?', (normalized, rowid)
                    )


def migrate_database(path):
    """Explicitly upgrade v7 data to v8's UTC-naive timestamp contract."""
    connection = connect(path)
    try:
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        if version == SCHEMA_VERSION:
            validate_database(connection)
            return False
        if version != 7:
            raise SchemaError("Only the explicit v7-to-v8 timestamp migration is supported")
        row = connection.execute(
            "SELECT version,name,checksum FROM schema_migrations"
        ).fetchall()
        if len(row) != 1 or tuple(row[0]) != (7, SCHEMA_NAME, LEGACY_V7_CHECKSUM):
            raise SchemaError("Database schema identity does not match the supported v7 contract")
        try:
            connection.execute("BEGIN EXCLUSIVE")
            # Timestamp normalization touches immutable evidence timestamps but
            # does not alter their content or lineage. Restore every trigger
            # before committing so normal protections remain uninterrupted.
            triggers = connection.execute(
                "SELECT name,sql FROM sqlite_master WHERE type='trigger' ORDER BY name"
            ).fetchall()
            for name, _sql in triggers:
                connection.execute(f'DROP TRIGGER "{name}"')
            _normalize_timestamp_columns(connection)
            for _name, sql in triggers:
                connection.execute(sql)
            connection.execute("UPDATE schema_migrations SET version=?,checksum=?,applied_at=?",
                               (SCHEMA_VERSION, contract_checksum(), utc_now()))
            connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            validate_database(connection)
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        return True
    finally:
        connection.close()


def initialize_database(path):
    """Create an empty current schema or validate it; never reset data."""
    path = Path(path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = connect(path)
    try:
        if connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION:
            validate_database(connection)
            return False
        if connection.execute("PRAGMA user_version").fetchone()[0] == 7:
            connection.close()
            return migrate_database(path)
        if connection.execute("PRAGMA user_version").fetchone()[0] or connection.execute(
            "SELECT 1 FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' LIMIT 1"
        ).fetchone():
            raise SchemaError("Refusing an existing incompatible database; choose a new filename")
        try:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.executescript("BEGIN EXCLUSIVE;\n" + CONTRACT_PATH.read_text())
            connection.execute("INSERT INTO schema_migrations(version,name,checksum,applied_at) VALUES (?,?,?,?)",
                               (SCHEMA_VERSION, SCHEMA_NAME, contract_checksum(), utc_now()))
            validate_database(connection)
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        return True
    finally:
        connection.close()
