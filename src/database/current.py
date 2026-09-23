"""Explicit fresh-database initialization and fail-closed current-schema checks."""

from hashlib import sha256
from pathlib import Path
import sqlite3
from common.timestamps import utc_now
from content_factory_resources import contract_path

SCHEMA_VERSION = 10
CONTRACT_PATH = contract_path("application-schema.sql")
SCHEMA_NAME = "content_factory_application"


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
        raise SchemaError("Current schema 10 required; create a fresh database with a new filename")
    try:
        rows = connection.execute("SELECT version,name,checksum FROM schema_migrations").fetchall()
        if len(rows) != 1 or tuple(rows[0]) != (SCHEMA_VERSION, SCHEMA_NAME, contract_checksum()):
            raise SchemaError("Database schema identity/checksum does not match the current contract")
    except sqlite3.Error as error:
        raise SchemaError("Database schema ledger is missing or invalid") from error
    if check_foreign_keys and connection.execute("PRAGMA foreign_key_check").fetchall():
        raise SchemaError("Database foreign-key check failed")


def initialize_database(path):
    """Create an empty current schema or validate it; never reset data."""
    path = Path(path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = connect(path)
    try:
        if connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION:
            validate_database(connection)
            return False
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
