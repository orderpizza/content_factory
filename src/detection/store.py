"""SQLite repository for deterministic detection handoffs."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from typing import Any, Iterable
import json
import sqlite3
from common.diagnostics import safe_diagnostic
from common.timestamps import utc_now

from database.current import SchemaError, connect, validate_database
from .configuration import canonical_json, validate_manifest


class DetectionStore:
    def __init__(self, path: str | Path, *, read_only: bool = False):
        self.path = Path(path).resolve()
        if not self.path.is_file():
            raise SchemaError(
                f"Database does not exist: {self.path}. Run the explicit setup command."
            )
        self.connection = connect(self.path, read_only=read_only)
        try:
            validate_database(self.connection)
        except Exception:
            self.connection.close()
            raise
        self.read_only = read_only

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> "DetectionStore":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def apply_manifest(
        self,
        manifest: dict[str, Any],
        *,
        operator_id: str = "local_owner",
        reason: str = "explicit local activation",
    ) -> int:
        if self.read_only:
            raise RuntimeError("A read-only store cannot apply configuration")
        validate_manifest(manifest)
        manifest_json = canonical_json(manifest)
        manifest_hash = sha256(manifest_json.encode("utf-8")).hexdigest()
        now = utc_now()
        self.connection.execute("BEGIN IMMEDIATE")
        with self.connection:
            target_normalization = manifest["components"]["detection"]["canonicalization_version"]
            for release in self.connection.execute("SELECT manifest_json FROM configuration_releases WHERE validation_outcome='validated'"):
                if json.loads(release[0])["components"]["detection"]["canonicalization_version"] != target_normalization:
                    raise ValueError("Normalization changes require a separately named fresh database; existing identities and handoffs are never rewritten or merged implicitly")
            existing = self.connection.execute(
                "SELECT configuration_release_id, manifest_hash FROM configuration_releases "
                "WHERE scope_key=? AND release_name=?",
                (manifest["scope_key"], manifest["release_name"]),
            ).fetchone()
            if existing and existing["manifest_hash"] != manifest_hash:
                raise ValueError("Release name already exists with different canonical content")
            if existing:
                release_id = int(existing["configuration_release_id"])
            else:
                cursor = self.connection.execute(
                    "INSERT INTO configuration_releases "
                    "(release_name, scope_key, schema_id, schema_version, manifest_json, "
                    "manifest_hash, validation_outcome, diagnostics_json, operator_id, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, 'validated', '[]', ?, ?)",
                    (
                        manifest["release_name"], manifest["scope_key"], manifest["schema_id"],
                        manifest["schema_version"], manifest_json, manifest_hash, operator_id, now,
                    ),
                )
                release_id = int(cursor.lastrowid)
                self._materialize_detection(release_id, manifest, now)

            active = self.connection.execute(
                "SELECT configuration_activation_id, configuration_release_id "
                "FROM configuration_activations WHERE scope_key='global' AND status='active'"
            ).fetchone()
            if active and int(active["configuration_release_id"]) == release_id:
                return release_id
            if active:
                self.connection.execute(
                    "UPDATE configuration_activations SET status='superseded', "
                    "superseded_at=?, updated_at=?, row_version=row_version+1 "
                    "WHERE configuration_activation_id=? AND status='active'",
                    (now, now, active["configuration_activation_id"]),
                )
            self.connection.execute(
                "INSERT INTO configuration_activations "
                "(scope_key, configuration_release_id, status, actor_id, reason, "
                "activated_at, created_at, updated_at) VALUES "
                "('global', ?, 'active', ?, ?, ?, ?, ?)",
                (release_id, operator_id, reason, now, now, now),
            )
        return release_id

    def _materialize_detection(
        self, release_id: int, manifest: dict[str, Any], now: str
    ) -> None:
        detection = manifest["components"]["detection"]
        for source in sorted(detection["sources"], key=lambda item: item["stable_id"]):
            source_json = canonical_json(source)
            fingerprint = sha256(source_json.encode("utf-8")).hexdigest()
            self.connection.execute(
                "INSERT INTO detection_source_instances "
                "(stable_id, source_kind, adapter_version, provider_name, endpoint_url, "
                "delivery_format, coverage_note, enabled, cadence_seconds, availability_seconds, "
                "trust_weight, independence_group, language_scope, region_scope, quota_limit, "
                "secret_ref, config_json, config_fingerprint, configuration_release_id, "
                "created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    source["stable_id"], source["source_kind"], source["adapter_version"],
                    source["provider_name"], source["endpoint_url"], source["delivery_format"],
                    source["coverage_note"], int(source["enabled"]), source["cadence_seconds"],
                    source["availability_seconds"], source["trust_weight"],
                    source["independence_group"], source["language_scope"],
                    source["region_scope"], source["quota_limit"], source["secret_ref"],
                    source_json, fingerprint, release_id, now, now,
                ),
            )
    def active_release(self) -> sqlite3.Row:
        row = self.connection.execute(
            "SELECT r.* FROM configuration_activations a "
            "JOIN configuration_releases r ON r.configuration_release_id=a.configuration_release_id "
            "WHERE a.scope_key='global' AND a.status='active'"
        ).fetchone()
        if row is None:
            raise RuntimeError("No active global configuration release; run setup first")
        return row

    def normalization_version(self, release_id: int) -> str:
        row = self.connection.execute("SELECT manifest_json FROM configuration_releases WHERE configuration_release_id=?", (release_id,)).fetchone()
        return json.loads(row[0])["components"]["detection"]["canonicalization_version"]

    def enabled_sources(self) -> list[sqlite3.Row]:
        release_id = int(self.active_release()["configuration_release_id"])
        return self.connection.execute(
            "SELECT * FROM detection_source_instances "
            "WHERE configuration_release_id=? AND enabled=1 ORDER BY stable_id",
            (release_id,),
        ).fetchall()

    def heartbeat(
        self,
        worker_type: str,
        instance_id: str,
        state: str,
        summary: str,
        *,
        claim_type: str | None = None,
        claim_id: int | None = None,
    ) -> None:
        now = utc_now()
        self.connection.execute(
            "INSERT INTO worker_heartbeats "
            "(worker_type, instance_id, started_at, last_seen_at, state, claim_type, "
            "claim_id, build_version, safe_summary, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 'detection_dashboard_v1', ?, ?, ?) "
            "ON CONFLICT(worker_type, instance_id) DO UPDATE SET "
            "last_seen_at=excluded.last_seen_at, state=excluded.state, "
            "claim_type=excluded.claim_type, claim_id=excluded.claim_id, "
            "build_version=excluded.build_version, safe_summary=excluded.safe_summary, "
            "updated_at=excluded.updated_at",
            (worker_type, instance_id, now, now, state, claim_type, claim_id, safe_diagnostic(summary), now, now),
        )
        self.connection.commit()

    def start_worker_run(
        self, worker_type: str, instance_id: str, claim_type: str, claim_id: int
    ) -> int:
        now = utc_now()
        cursor = self.connection.execute(
            "INSERT INTO worker_runs "
            "(worker_type, instance_id, claim_type, claim_id, started_at, status, created_at) "
            "VALUES (?, ?, ?, ?, ?, 'running', ?)",
            (worker_type, instance_id, claim_type, claim_id, now, now),
        )
        self.connection.commit()
        return int(cursor.lastrowid)

    def finish_worker_run(
        self,
        worker_run_id: int,
        status: str,
        *,
        summary: str | None = None,
        error: str | None = None,
    ) -> None:
        self.connection.execute(
            "UPDATE worker_runs SET completed_at=?, status=?, safe_summary=?, safe_error=? "
            "WHERE worker_run_id=? AND status='running'",
            (utc_now(), status, safe_diagnostic(summary) if summary else None, safe_diagnostic(error) if error else None, worker_run_id),
        )
        self.connection.commit()


def row_json(row: sqlite3.Row, key: str) -> Any:
    return json.loads(row[key])
