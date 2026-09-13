"""Explicit migrations for the target detection/dashboard milestone."""

from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
import json
import sqlite3
from content_factory_resources import contract_path


DETECTION_SCHEMA_VERSION = 1
SCHEMA_VERSION = 2
SAFETY_SCHEMA_VERSION = 3
PRODUCTION_SCHEMA_VERSION = 4
LATEST_SCHEMA_VERSION = PRODUCTION_SCHEMA_VERSION
SAFETY_MIGRATION_NAME = "detection_safety_schema_v3"
PRODUCTION_MIGRATION_NAME = "production_workflow_schema_v4"
MIGRATION_NAME = "detection_dashboard_schema_v1"
EDITORIAL_MIGRATION_NAME = "editorial_workflow_schema_v2"
ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = contract_path("detection-dashboard-schema-v1.sql")
EDITORIAL_CONTRACT_PATH = contract_path("editorial-workflow-schema-v2.sql")
SAFETY_CONTRACT_PATH = contract_path("detection-safety-schema-v3.sql")
PRODUCTION_CONTRACT_PATH = contract_path("production-workflow-schema-v4.sql")


class SchemaError(RuntimeError):
    """Raised when a database cannot safely satisfy the expected schema."""


def contract_bytes() -> bytes:
    return CONTRACT_PATH.read_bytes()


def contract_checksum() -> str:
    return sha256(contract_bytes()).hexdigest()


def editorial_contract_checksum() -> str:
    return sha256(EDITORIAL_CONTRACT_PATH.read_bytes()).hexdigest()


def connect(path: str | Path, *, read_only: bool = False) -> sqlite3.Connection:
    database_path = Path(path).resolve()
    if read_only:
        connection = sqlite3.connect(
            f"{database_path.as_uri()}?mode=ro",
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
        if version == DETECTION_SCHEMA_VERSION:
            validate_detection_dashboard(connection)
            return False
        if version != 0:
            raise SchemaError(
                f"Unsupported database schema version {version}; expected 0 or {DETECTION_SCHEMA_VERSION}."
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
            + f"({DETECTION_SCHEMA_VERSION}, '{escaped_name}', '{checksum}', '{applied_at}');\n"
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


def migrate_editorial_workflow(path: str | Path) -> bool:
    """Explicitly migrate a validated detection database from v1 to workflow v2."""

    database_path = Path(path).resolve()
    if not database_path.is_file():
        raise SchemaError("Workflow migration requires an existing v1 database; run detection setup first.")
    connection = connect(database_path)
    try:
        version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        if version in (SCHEMA_VERSION, SAFETY_SCHEMA_VERSION, PRODUCTION_SCHEMA_VERSION):
            validate_editorial_workflow(connection)
            return False
        if version != DETECTION_SCHEMA_VERSION:
            raise SchemaError(f"Unsupported database schema version {version}; expected 1 or 2.")
        _validate_migration(connection, DETECTION_SCHEMA_VERSION, MIGRATION_NAME, contract_checksum())
        now = datetime.now(timezone.utc).isoformat()
        checksum = editorial_contract_checksum()
        sql = EDITORIAL_CONTRACT_PATH.read_text(encoding="utf-8")
        try:
            escaped_name = EDITORIAL_MIGRATION_NAME.replace("'", "''")
            script = (
                "BEGIN EXCLUSIVE;\n" + sql + "\nINSERT INTO schema_migrations "
                "(version,name,checksum,applied_at) VALUES "
                f"({SCHEMA_VERSION},'{escaped_name}','{checksum}','{now}');\n"
            )
            connection.executescript(script)
            violations = connection.execute("PRAGMA foreign_key_check").fetchall()
            if violations:
                raise SchemaError(f"Migration foreign-key check failed: {len(violations)} violation(s).")
            connection.commit()
        except Exception:
            if connection.in_transaction:
                connection.rollback()
            raise
        validate_editorial_workflow(connection)
        return True
    finally:
        connection.close()


def migrate_detection_safety(path: str | Path) -> bool:
    """Explicit forward migration from a validated v2 database; never reset."""
    database_path = Path(path).resolve()
    if not database_path.is_file():
        raise SchemaError("Safety migration requires an existing v2 database.")
    connection = connect(database_path)
    try:
        validate_editorial_workflow(connection)
        if int(connection.execute("PRAGMA user_version").fetchone()[0]) in (SAFETY_SCHEMA_VERSION, PRODUCTION_SCHEMA_VERSION):
            return False
        sql = SAFETY_CONTRACT_PATH.read_bytes()
        checksum = sha256(sql).hexdigest()
        moment = datetime.now(timezone.utc).isoformat()
        try:
            connection.executescript("BEGIN EXCLUSIVE;\n" + sql.decode("utf-8"))
            connection.execute("INSERT INTO schema_migrations(version,name,checksum,applied_at) VALUES (?,?,?,?)", (SAFETY_SCHEMA_VERSION, SAFETY_MIGRATION_NAME, checksum, moment))
            if connection.execute("PRAGMA foreign_key_check").fetchall():
                raise SchemaError("Safety migration foreign-key check failed")
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        validate_detection_dashboard(connection)
        return True
    finally:
        connection.close()


def migrate_production_workflow(path: str | Path) -> bool:
    """Explicitly add credential-ready safety/delivery records to schema v3."""
    database_path = Path(path).resolve()
    if not database_path.is_file():
        raise SchemaError("Production migration requires an existing workflow database.")
    connection = connect(database_path)
    try:
        version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        if version == PRODUCTION_SCHEMA_VERSION:
            validate_production_workflow(connection)
            return False
        if version != SAFETY_SCHEMA_VERSION:
            raise SchemaError(
                f"Production migration requires schema v{SAFETY_SCHEMA_VERSION}; found v{version}."
            )
        validate_editorial_workflow(connection)
        active = connection.execute(
            "SELECT r.manifest_json FROM configuration_activations a "
            "JOIN configuration_releases r ON r.configuration_release_id=a.configuration_release_id "
            "WHERE a.scope_key='global' AND a.status='active'"
        ).fetchone()
        if active is None:
            raise SchemaError("Production migration requires an active detection configuration release.")
        try:
            detection = json.loads(active["manifest_json"])["components"]["detection"]
        except (KeyError, TypeError, json.JSONDecodeError) as error:
            raise SchemaError("Active detection configuration is malformed.") from error
        if (
            detection.get("canonicalization_version") != "canonicalization_v2"
            or detection.get("score_formula_version") != "attention_v2"
        ):
            raise SchemaError(
                "Production v4 is restricted to the fresh Option B normalized/hybrid database; "
                "the legacy database was not changed."
            )
        sql = PRODUCTION_CONTRACT_PATH.read_bytes()
        checksum = sha256(sql).hexdigest()
        moment = datetime.now(timezone.utc).isoformat()
        try:
            connection.executescript("BEGIN EXCLUSIVE;\n" + sql.decode("utf-8"))
            connection.execute(
                "INSERT INTO schema_migrations(version,name,checksum,applied_at) VALUES (?,?,?,?)",
                (PRODUCTION_SCHEMA_VERSION, PRODUCTION_MIGRATION_NAME, checksum, moment),
            )
            if connection.execute("PRAGMA foreign_key_check").fetchall():
                raise SchemaError("Production migration foreign-key check failed")
            connection.commit()
        except Exception:
            if connection.in_transaction:
                connection.rollback()
            raise
        validate_production_workflow(connection)
        return True
    finally:
        connection.close()


def validate_detection_dashboard(connection: sqlite3.Connection, *, check_foreign_keys: bool = True) -> None:
    version = int(connection.execute("PRAGMA user_version").fetchone()[0])
    if version not in (
        DETECTION_SCHEMA_VERSION, SCHEMA_VERSION, SAFETY_SCHEMA_VERSION,
        PRODUCTION_SCHEMA_VERSION,
    ):
        raise SchemaError(
            f"Database schema version is {version}; expected 1 through {LATEST_SCHEMA_VERSION}. "
            "Run the explicit setup command."
        )
    try:
        _validate_migration(connection, DETECTION_SCHEMA_VERSION, MIGRATION_NAME, contract_checksum())
    except sqlite3.Error as error:
        raise SchemaError("Database does not contain the required migration ledger.") from error
    if version >= SCHEMA_VERSION:
        _validate_migration(connection, SCHEMA_VERSION, EDITORIAL_MIGRATION_NAME, editorial_contract_checksum())
    if version >= SAFETY_SCHEMA_VERSION:
        _validate_migration(connection, SAFETY_SCHEMA_VERSION, SAFETY_MIGRATION_NAME, sha256(SAFETY_CONTRACT_PATH.read_bytes()).hexdigest())
    if version >= PRODUCTION_SCHEMA_VERSION:
        _validate_migration(connection, PRODUCTION_SCHEMA_VERSION, PRODUCTION_MIGRATION_NAME, sha256(PRODUCTION_CONTRACT_PATH.read_bytes()).hexdigest())
    if check_foreign_keys:
        violations = connection.execute("PRAGMA foreign_key_check").fetchall()
        if violations:
            raise SchemaError(f"Database foreign-key check failed: {len(violations)} violation(s).")


def _validate_migration(connection: sqlite3.Connection, version: int, name: str, checksum: str) -> None:
    row = connection.execute(
        "SELECT name, checksum FROM schema_migrations WHERE version = ?", (version,)
    ).fetchone()
    if row is None or row["name"] != name:
        raise SchemaError("Database migration identity does not match the expected contract.")
    if row["checksum"] != checksum:
        raise SchemaError("Database migration checksum differs from the canonical SQL contract.")


def validate_editorial_workflow(connection: sqlite3.Connection) -> None:
    if int(connection.execute("PRAGMA user_version").fetchone()[0]) not in (
        SCHEMA_VERSION, SAFETY_SCHEMA_VERSION, PRODUCTION_SCHEMA_VERSION,
    ):
        raise SchemaError("Editorial workflow schema v2 is required; run scripts/setup_workflow.py explicitly.")
    validate_detection_dashboard(connection)


def validate_production_workflow(connection: sqlite3.Connection) -> None:
    if int(connection.execute("PRAGMA user_version").fetchone()[0]) != PRODUCTION_SCHEMA_VERSION:
        raise SchemaError("Production workflow schema v4 is required; run scripts/setup_production.py explicitly.")
    validate_editorial_workflow(connection)
