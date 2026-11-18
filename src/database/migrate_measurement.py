"""Explicit backed-up v19 -> v20 migration; startup never invokes this module."""
from hashlib import sha256
from itertools import zip_longest
from pathlib import Path
import sqlite3

from common.timestamps import utc_now
from content_factory_resources import contract_path
from .current import (CONTRACT_PATH, SCHEMA_NAME, V18_CHECKSUM, V19_CHECKSUM,
                      SchemaError, connect, contract_checksum, validate_database)


def v19_sql():
    delta = contract_path('migration-19-20.sql').read_text()
    current = CONTRACT_PATH.read_text()
    if not current.endswith('\n' + delta):
        raise SchemaError('measurement migration and fresh contract differ')
    legacy = current[:-len(delta)-1]
    if sha256(legacy.encode()).hexdigest() != V19_CHECKSUM:
        raise SchemaError('unsupported v19 contract')
    return legacy


def validate_v19(connection):
    expected = sqlite3.connect(':memory:')
    try:
        expected.executescript(v19_sql())
        query = "SELECT type,name,tbl_name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY name"
        if [tuple(r) for r in connection.execute(query)] != expected.execute(query).fetchall():
            raise SchemaError('legacy executable schema differs from v19')
    finally:
        expected.close()
    ledger = [tuple(r) for r in connection.execute('SELECT version,name,checksum FROM schema_migrations ORDER BY version')]
    if connection.execute('PRAGMA user_version').fetchone()[0] != 19 or ledger not in [
        [(19, SCHEMA_NAME, V19_CHECKSUM)],
        [(18, SCHEMA_NAME, V18_CHECKSUM), (19, SCHEMA_NAME, V19_CHECKSUM)],
    ]:
        raise SchemaError('only the exact schema v19 can be migrated')
    if (connection.execute('PRAGMA integrity_check').fetchone()[0] != 'ok'
            or connection.execute('PRAGMA foreign_key_check').fetchall()):
        raise SchemaError('legacy integrity or foreign-key check failed')


def _apply(connection):
    statement = ''
    for line in contract_path('migration-19-20.sql').read_text().splitlines(True):
        statement += line
        if sqlite3.complete_statement(statement):
            connection.execute(statement)
            statement = ''
    if statement.strip():
        raise SchemaError('incomplete migration SQL')
    connection.execute('INSERT INTO schema_migrations(version,name,checksum,applied_at) VALUES (20,?,?,?)',
                       (SCHEMA_NAME, contract_checksum(), utc_now()))
    validate_database(connection)


def migrate(path, *, apply=False, backup=None):
    path = Path(path).resolve(strict=True)
    source = connect(path, read_only=not apply)
    try:
        if source.execute('PRAGMA user_version').fetchone()[0] == 20:
            validate_database(source)
            return 'already_current'
        validate_v19(source)
        if not apply:
            copy = sqlite3.connect(':memory:')
            try:
                source.backup(copy)
                copy.execute('PRAGMA foreign_keys=ON')
                with copy:
                    _apply(copy)
            finally:
                copy.close()
            return 'dry_run_ok'
        if backup is None:
            raise ValueError('an unused backup path is required; stop all writers first')
        backup = Path(backup).absolute()
        with backup.open('xb'):
            pass
        snapshot = sqlite3.connect(backup)
        try:
            source.backup(snapshot)
            validate_v19(snapshot)
        finally:
            snapshot.close()
        source.execute('BEGIN EXCLUSIVE')
        try:
            validate_v19(source)
            snapshot = connect(backup, read_only=True)
            try:
                if any(a != b for a, b in zip_longest(source.iterdump(), snapshot.iterdump())):
                    raise SchemaError('database changed since backup; stop writers and use a new backup')
            finally:
                snapshot.close()
            _apply(source)
            source.commit()
        except BaseException:
            source.rollback()
            raise
        return 'migrated'
    finally:
        source.close()
