"""Explicit offline v18 → v19 migration. No reset, implicit upgrade or downgrade."""
from hashlib import sha256
from itertools import zip_longest
from pathlib import Path
import sqlite3

from common.timestamps import utc_now
from content_factory_resources import contract_path
from .current import SCHEMA_NAME, V18_CHECKSUM, V19_CHECKSUM, SchemaError, connect
from .migrate_measurement import v19_sql, validate_v19 as validate_database


def contract_checksum():
    return V19_CHECKSUM


def _legacy_sql():
    delta = contract_path("migration-18-19.sql").read_text()
    current = v19_sql()
    if not current.endswith("\n" + delta):
        raise SchemaError("migration and fresh contract differ")
    legacy = current[:-len(delta)-1].replace("PRAGMA user_version = 19;", "PRAGMA user_version = 18;", 1)
    if sha256(legacy.encode()).hexdigest() != V18_CHECKSUM:
        raise SchemaError("unsupported legacy contract")
    return legacy


def _validate_legacy(connection):
    expected = sqlite3.connect(":memory:")
    try:
        expected.executescript(_legacy_sql())
        query = "SELECT type,name,tbl_name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY name"
        if [tuple(r) for r in connection.execute(query)] != expected.execute(query).fetchall():
            raise SchemaError("legacy executable schema differs from v18")
    finally:
        expected.close()
    if (connection.execute("PRAGMA user_version").fetchone()[0] != 18
            or [tuple(r) for r in connection.execute("SELECT version,name,checksum FROM schema_migrations")]
            != [(18, SCHEMA_NAME, V18_CHECKSUM)]):
        raise SchemaError("only the exact schema v18 can be migrated")
    if (connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok"
            or connection.execute("PRAGMA foreign_key_check").fetchall()):
        raise SchemaError("legacy integrity or foreign-key check failed")


def _apply(connection):
    # executescript commits an existing transaction; execute complete statements
    # individually so DDL, ledger and user_version roll back together.
    statement = ""
    for line in contract_path("migration-18-19.sql").read_text().splitlines(True):
        statement += line
        if sqlite3.complete_statement(statement):
            connection.execute(statement)
            statement = ""
    if statement.strip():
        raise SchemaError("incomplete migration SQL")
    connection.execute(
        "INSERT INTO schema_migrations(version,name,checksum,applied_at) VALUES (19,?,?,?)",
        (SCHEMA_NAME, contract_checksum(), utc_now()),
    )
    validate_database(connection)


def migrate(path, *, apply=False, backup=None):
    path = Path(path).resolve(strict=True)
    source = connect(path, read_only=not apply)
    try:
        if source.execute("PRAGMA user_version").fetchone()[0] == 19:
            validate_database(source)
            return "already_current"
        _validate_legacy(source)
        if not apply:
            copy = sqlite3.connect(":memory:")
            try:
                source.backup(copy)
                copy.execute("PRAGMA foreign_keys=ON")
                with copy:
                    _apply(copy)
            finally:
                copy.close()
            return "dry_run_ok"
        if backup is None:
            raise ValueError("an unused backup path is required; stop all writers first")
        backup = Path(backup).absolute()
        # Exclusive creation protects existing backup data, including symlinks.
        with backup.open("xb"):
            pass
        snapshot = sqlite3.connect(backup)
        try:
            source.backup(snapshot)
            _validate_legacy(snapshot)
        finally:
            snapshot.close()
        source.execute("BEGIN EXCLUSIVE")
        try:
            _validate_legacy(source)
            # Detect a writer between backup and acquisition of the write lock.
            snapshot = connect(backup, read_only=True)
            try:
                if any(a != b for a, b in zip_longest(source.iterdump(), snapshot.iterdump())):
                    raise SchemaError("database changed since backup; stop writers and retry with a new backup")
            finally:
                snapshot.close()
            _apply(source)
            source.commit()
        except Exception:
            source.rollback()
            raise
        return "migrated"
    finally:
        source.close()
