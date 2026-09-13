-- Forward migration: credential-ready production safety and delivery audit.
-- Applied only after detection safety schema v3; do not edit v1-v3.

CREATE TABLE social_destinations (
    social_destination_id INTEGER PRIMARY KEY AUTOINCREMENT,
    configuration_release_id INTEGER NOT NULL
        REFERENCES configuration_releases(configuration_release_id) ON DELETE RESTRICT,
    destination_key TEXT NOT NULL,
    platform TEXT NOT NULL CHECK(platform IN ('instagram','x')),
    account_key TEXT NOT NULL,
    provider_account_id TEXT NOT NULL,
    secret_ref TEXT NOT NULL,
    enabled INTEGER NOT NULL CHECK(enabled IN (0,1)),
    config_json TEXT NOT NULL CHECK(json_valid(config_json)),
    config_fingerprint TEXT NOT NULL CHECK(length(config_fingerprint)=64),
    created_at TEXT NOT NULL,
    UNIQUE(configuration_release_id,destination_key),
    UNIQUE(configuration_release_id,platform,account_key)
);

CREATE TABLE production_configurations (
    production_configuration_id INTEGER PRIMARY KEY AUTOINCREMENT,
    configuration_release_id INTEGER NOT NULL UNIQUE
        REFERENCES configuration_releases(configuration_release_id) ON DELETE RESTRICT,
    policy_version TEXT NOT NULL,
    configuration_json TEXT NOT NULL CHECK(json_valid(configuration_json)),
    configuration_hash TEXT NOT NULL UNIQUE CHECK(length(configuration_hash)=64),
    approved_by TEXT NOT NULL,
    approved_at TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE posting_policies (
    posting_policy_id INTEGER PRIMARY KEY AUTOINCREMENT,
    social_destination_id INTEGER NOT NULL
        REFERENCES social_destinations(social_destination_id) ON DELETE RESTRICT,
    policy_version TEXT NOT NULL,
    timezone_name TEXT NOT NULL,
    max_posts_per_day INTEGER NOT NULL CHECK(max_posts_per_day>0),
    min_post_interval_minutes INTEGER NOT NULL CHECK(min_post_interval_minutes>=0),
    immediate_bypasses_cadence INTEGER NOT NULL CHECK(immediate_bypasses_cadence=0),
    authorization_ttl_hours INTEGER NOT NULL CHECK(authorization_ttl_hours>0),
    created_at TEXT NOT NULL,
    UNIQUE(social_destination_id,policy_version)
);

CREATE TABLE capability_readiness (
    capability_readiness_id INTEGER PRIMARY KEY AUTOINCREMENT,
    social_destination_id INTEGER NOT NULL UNIQUE
        REFERENCES social_destinations(social_destination_id) ON DELETE RESTRICT,
    configuration_release_id INTEGER NOT NULL
        REFERENCES configuration_releases(configuration_release_id) ON DELETE RESTRICT,
    status TEXT NOT NULL CHECK(status IN ('ready','degraded','blocked','unknown')),
    reasons_json TEXT NOT NULL CHECK(json_valid(reasons_json)),
    facts_json TEXT NOT NULL CHECK(json_valid(facts_json)),
    checked_at TEXT NOT NULL,
    valid_until TEXT NOT NULL,
    row_version INTEGER NOT NULL DEFAULT 1 CHECK(row_version>0),
    updated_at TEXT NOT NULL
);

CREATE TABLE capability_readiness_checks (
    capability_readiness_check_id INTEGER PRIMARY KEY AUTOINCREMENT,
    capability_readiness_id INTEGER NOT NULL
        REFERENCES capability_readiness(capability_readiness_id) ON DELETE RESTRICT,
    status TEXT NOT NULL CHECK(status IN ('ready','degraded','blocked','unknown')),
    evidence_json TEXT NOT NULL CHECK(json_valid(evidence_json)),
    evidence_hash TEXT NOT NULL CHECK(length(evidence_hash)=64),
    checked_at TEXT NOT NULL
);

ALTER TABLE output_bindings ADD COLUMN social_destination_id INTEGER
    REFERENCES social_destinations(social_destination_id) ON DELETE RESTRICT;
ALTER TABLE output_bindings ADD COLUMN delivery_enabled INTEGER NOT NULL DEFAULT 0
    CHECK(delivery_enabled IN (0,1));
ALTER TABLE output_bindings ADD COLUMN profile_approved INTEGER NOT NULL DEFAULT 0
    CHECK(profile_approved IN (0,1));

ALTER TABLE adaptation_runs ADD COLUMN adapted_body_json TEXT
    CHECK(adapted_body_json IS NULL OR json_valid(adapted_body_json));
ALTER TABLE adaptation_runs ADD COLUMN adapted_body_hash TEXT
    CHECK(adapted_body_hash IS NULL OR length(adapted_body_hash)=64);
ALTER TABLE adaptation_runs ADD COLUMN metadata_json TEXT
    CHECK(metadata_json IS NULL OR json_valid(metadata_json));
ALTER TABLE adaptation_runs ADD COLUMN metadata_hash TEXT
    CHECK(metadata_hash IS NULL OR length(metadata_hash)=64);

ALTER TABLE render_assets ADD COLUMN encoder_version TEXT;
ALTER TABLE render_assets ADD COLUMN deleted_at TEXT;
ALTER TABLE render_assets ADD COLUMN deletion_reason TEXT;

ALTER TABLE review_requests ADD COLUMN destination_key TEXT;

ALTER TABLE post_requests ADD COLUMN render_run_id INTEGER
    REFERENCES render_runs(render_run_id) ON DELETE RESTRICT;
ALTER TABLE post_requests ADD COLUMN package_hash TEXT
    CHECK(package_hash IS NULL OR length(package_hash)=64);
ALTER TABLE post_requests ADD COLUMN manifest_hash TEXT
    CHECK(manifest_hash IS NULL OR length(manifest_hash)=64);
ALTER TABLE post_requests ADD COLUMN destination_key TEXT;

ALTER TABLE post_records ADD COLUMN policy_snapshot_json TEXT
    CHECK(policy_snapshot_json IS NULL OR json_valid(policy_snapshot_json));
ALTER TABLE post_records ADD COLUMN external_post_id TEXT;
ALTER TABLE post_records ADD COLUMN published_at TEXT;
ALTER TABLE post_records ADD COLUMN publication_unknown_at TEXT;

CREATE TABLE post_attempts (
    post_attempt_id INTEGER PRIMARY KEY AUTOINCREMENT,
    post_record_id INTEGER NOT NULL
        REFERENCES post_records(post_record_id) ON DELETE RESTRICT,
    attempt_number INTEGER NOT NULL CHECK(attempt_number>0),
    status TEXT NOT NULL CHECK(status IN (
        'created','staging','ready_to_publish','final_request_sent','succeeded',
        'retryable_failed','failed','cancelled','outcome_unknown'
    )),
    failure_category TEXT,
    failure_detail TEXT,
    final_publication_request_sent_at TEXT,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    UNIQUE(post_record_id,attempt_number)
);

CREATE TABLE publication_resources (
    publication_resource_id INTEGER PRIMARY KEY AUTOINCREMENT,
    post_attempt_id INTEGER NOT NULL
        REFERENCES post_attempts(post_attempt_id) ON DELETE RESTRICT,
    resource_type TEXT NOT NULL,
    asset_ordinal INTEGER CHECK(asset_ordinal IS NULL OR asset_ordinal>0),
    remote_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN (
        'created','ready','published','cleanup_pending','cleaned','retained','failed'
    )),
    safe_metadata_json TEXT NOT NULL CHECK(json_valid(safe_metadata_json)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(post_attempt_id,resource_type,remote_id)
);

CREATE TABLE delivery_cleanup_tasks (
    delivery_cleanup_task_id INTEGER PRIMARY KEY AUTOINCREMENT,
    publication_resource_id INTEGER NOT NULL
        REFERENCES publication_resources(publication_resource_id) ON DELETE RESTRICT,
    object_key TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('pending','claimed','retry_wait','succeeded','failed','cancelled')),
    claim_owner TEXT,
    claimed_at TEXT,
    lease_expires_at TEXT,
    claim_version INTEGER NOT NULL DEFAULT 0 CHECK(claim_version>=0),
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK(attempt_count>=0),
    attempt_limit INTEGER NOT NULL CHECK(attempt_limit>0),
    next_attempt_at TEXT,
    failure_reason TEXT,
    created_at TEXT NOT NULL,
    completed_at TEXT,
    UNIQUE(publication_resource_id,object_key)
);
CREATE INDEX ix_delivery_cleanup_pickup
    ON delivery_cleanup_tasks(status,next_attempt_at,created_at);

CREATE TABLE reconciliation_requests (
    reconciliation_request_id INTEGER PRIMARY KEY AUTOINCREMENT,
    post_record_id INTEGER NOT NULL
        REFERENCES post_records(post_record_id) ON DELETE RESTRICT,
    reason TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('pending','claimed','retry_wait','needs_human','resolved','failed','cancelled')),
    claim_owner TEXT,
    claimed_at TEXT,
    lease_expires_at TEXT,
    claim_version INTEGER NOT NULL DEFAULT 0 CHECK(claim_version>=0),
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK(attempt_count>=0),
    attempt_limit INTEGER NOT NULL CHECK(attempt_limit>0),
    next_attempt_at TEXT,
    failure_reason TEXT,
    row_version INTEGER NOT NULL DEFAULT 1 CHECK(row_version>0),
    created_at TEXT NOT NULL,
    completed_at TEXT
);
CREATE UNIQUE INDEX uq_reconciliation_active_post
    ON reconciliation_requests(post_record_id)
    WHERE status IN ('pending','claimed','retry_wait','needs_human');

CREATE TABLE reconciliation_checks (
    reconciliation_check_id INTEGER PRIMARY KEY AUTOINCREMENT,
    reconciliation_request_id INTEGER NOT NULL
        REFERENCES reconciliation_requests(reconciliation_request_id) ON DELETE RESTRICT,
    outcome TEXT NOT NULL CHECK(outcome IN (
        'confirmed_published','confirmed_not_published','ambiguous','provider_unavailable'
    )),
    query_version TEXT NOT NULL,
    evidence_json TEXT NOT NULL CHECK(json_valid(evidence_json)),
    evidence_hash TEXT NOT NULL CHECK(length(evidence_hash)=64),
    checked_at TEXT NOT NULL
);

CREATE TABLE human_reconciliation_decisions (
    human_reconciliation_decision_id INTEGER PRIMARY KEY AUTOINCREMENT,
    reconciliation_request_id INTEGER NOT NULL UNIQUE
        REFERENCES reconciliation_requests(reconciliation_request_id) ON DELETE RESTRICT,
    reconciliation_check_id INTEGER NOT NULL
        REFERENCES reconciliation_checks(reconciliation_check_id) ON DELETE RESTRICT,
    decision TEXT NOT NULL CHECK(decision IN ('published','not_published_cancel','leave_unknown')),
    actor_id TEXT NOT NULL,
    note TEXT NOT NULL,
    created_at TEXT NOT NULL
);

ALTER TABLE gemini_budget_reservations ADD COLUMN content_job_id INTEGER
    REFERENCES content_jobs(content_job_id) ON DELETE RESTRICT;
ALTER TABLE gemini_budget_reservations ADD COLUMN phase TEXT;
ALTER TABLE gemini_budget_reservations ADD COLUMN price_snapshot_hash TEXT
    CHECK(price_snapshot_hash IS NULL OR length(price_snapshot_hash)=64);
ALTER TABLE gemini_budget_reservations ADD COLUMN max_input_tokens INTEGER
    CHECK(max_input_tokens IS NULL OR max_input_tokens>0);
ALTER TABLE gemini_budget_reservations ADD COLUMN max_output_tokens INTEGER
    CHECK(max_output_tokens IS NULL OR max_output_tokens>0);
ALTER TABLE gemini_budget_reservations ADD COLUMN daily_limit_micro_usd INTEGER
    CHECK(daily_limit_micro_usd IS NULL OR daily_limit_micro_usd>0);
ALTER TABLE gemini_budget_reservations ADD COLUMN daily_warning_micro_usd INTEGER
    CHECK(daily_warning_micro_usd IS NULL OR daily_warning_micro_usd>0);
ALTER TABLE gemini_budget_reservations ADD COLUMN job_limit_micro_usd INTEGER
    CHECK(job_limit_micro_usd IS NULL OR job_limit_micro_usd>0);

CREATE TABLE storage_samples (
    storage_sample_id INTEGER PRIMARY KEY AUTOINCREMENT,
    state TEXT NOT NULL CHECK(state IN ('normal','storage_warning','storage_critical','read_only_emergency')),
    free_bytes INTEGER NOT NULL CHECK(free_bytes>=0),
    total_bytes INTEGER NOT NULL CHECK(total_bytes>0),
    database_bytes INTEGER NOT NULL CHECK(database_bytes>=0),
    wal_bytes INTEGER NOT NULL CHECK(wal_bytes>=0),
    artifact_bytes INTEGER NOT NULL CHECK(artifact_bytes>=0),
    backup_bytes INTEGER NOT NULL CHECK(backup_bytes>=0),
    summary_json TEXT NOT NULL CHECK(json_valid(summary_json)),
    sampled_at TEXT NOT NULL
);

CREATE TABLE maintenance_runs (
    maintenance_run_id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL CHECK(kind IN (
        'sqlite_backup','backup_retention','restore_verify','wal_checkpoint','artifact_reconcile'
    )),
    status TEXT NOT NULL CHECK(status IN ('running','succeeded','failed','skipped_overlap')),
    backup_path TEXT,
    checksum TEXT CHECK(checksum IS NULL OR length(checksum)=64),
    summary_json TEXT NOT NULL CHECK(json_valid(summary_json)),
    failure_reason TEXT,
    started_at TEXT NOT NULL,
    completed_at TEXT
);

CREATE TABLE artifact_reconciliations (
    artifact_reconciliation_id INTEGER PRIMARY KEY AUTOINCREMENT,
    render_run_id INTEGER
        REFERENCES render_runs(render_run_id) ON DELETE RESTRICT,
    original_path TEXT NOT NULL,
    quarantine_path TEXT NOT NULL,
    reason TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX ix_post_records_pickup_v4 ON post_records(status,eligible_at,next_attempt_at);
CREATE INDEX ix_post_attempts_record ON post_attempts(post_record_id,attempt_number);
CREATE INDEX ix_publication_resources_attempt ON publication_resources(post_attempt_id,resource_type);
CREATE INDEX ix_budget_accounting_day ON gemini_budget_reservations(accounting_day,status);
CREATE INDEX ix_storage_samples_recent ON storage_samples(sampled_at DESC);
CREATE INDEX ix_maintenance_runs_kind ON maintenance_runs(kind,started_at DESC);

-- Production releases are append-only. Operational state (readiness, claims,
-- attempts, cleanup and reconciliation) has its own explicitly mutable rows.
CREATE TRIGGER production_configurations_immutable_update
BEFORE UPDATE ON production_configurations
BEGIN SELECT RAISE(ABORT, 'production configuration is immutable'); END;
CREATE TRIGGER production_configurations_immutable_delete
BEFORE DELETE ON production_configurations
BEGIN SELECT RAISE(ABORT, 'production configuration is immutable'); END;
CREATE TRIGGER social_destinations_immutable_update
BEFORE UPDATE ON social_destinations
BEGIN SELECT RAISE(ABORT, 'production destination is immutable'); END;
CREATE TRIGGER social_destinations_immutable_delete
BEFORE DELETE ON social_destinations
BEGIN SELECT RAISE(ABORT, 'production destination is immutable'); END;
CREATE TRIGGER posting_policies_immutable_update
BEFORE UPDATE ON posting_policies
BEGIN SELECT RAISE(ABORT, 'posting policy is immutable'); END;
CREATE TRIGGER posting_policies_immutable_delete
BEFORE DELETE ON posting_policies
BEGIN SELECT RAISE(ABORT, 'posting policy is immutable'); END;
CREATE TRIGGER human_reconciliation_decisions_immutable_update
BEFORE UPDATE ON human_reconciliation_decisions
BEGIN SELECT RAISE(ABORT, 'human reconciliation decision is immutable'); END;
CREATE TRIGGER human_reconciliation_decisions_immutable_delete
BEFORE DELETE ON human_reconciliation_decisions
BEGIN SELECT RAISE(ABORT, 'human reconciliation decision is immutable'); END;

PRAGMA user_version = 4;
