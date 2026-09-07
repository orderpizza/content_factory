PRAGMA foreign_keys = ON;

CREATE TABLE schema_migrations (
    schema_migration_id INTEGER PRIMARY KEY AUTOINCREMENT,
    version INTEGER NOT NULL CHECK (version > 0),
    name TEXT NOT NULL,
    checksum TEXT NOT NULL CHECK (length(checksum) = 64),
    applied_at TEXT NOT NULL,
    UNIQUE (version),
    UNIQUE (checksum)
);

CREATE TABLE configuration_releases (
    configuration_release_id INTEGER PRIMARY KEY AUTOINCREMENT,
    release_name TEXT NOT NULL,
    scope_key TEXT NOT NULL CHECK (scope_key = 'global'),
    schema_id TEXT NOT NULL,
    schema_version INTEGER NOT NULL CHECK (schema_version > 0),
    manifest_json TEXT NOT NULL CHECK (json_valid(manifest_json)),
    manifest_hash TEXT NOT NULL CHECK (length(manifest_hash) = 64),
    validation_outcome TEXT NOT NULL
        CHECK (validation_outcome IN ('validated', 'rejected')),
    diagnostics_json TEXT NOT NULL CHECK (json_valid(diagnostics_json)),
    operator_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (scope_key, release_name),
    UNIQUE (manifest_hash)
);

CREATE TABLE configuration_activations (
    configuration_activation_id INTEGER PRIMARY KEY AUTOINCREMENT,
    scope_key TEXT NOT NULL CHECK (scope_key = 'global'),
    configuration_release_id INTEGER NOT NULL
        REFERENCES configuration_releases(configuration_release_id)
        ON DELETE RESTRICT,
    status TEXT NOT NULL CHECK (status IN ('active', 'superseded')),
    actor_id TEXT NOT NULL,
    reason TEXT NOT NULL,
    row_version INTEGER NOT NULL DEFAULT 1 CHECK (row_version > 0),
    activated_at TEXT NOT NULL,
    superseded_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE UNIQUE INDEX uq_configuration_activations_active_scope
    ON configuration_activations(scope_key)
    WHERE status = 'active';

CREATE TABLE detection_source_instances (
    detection_source_instance_id INTEGER PRIMARY KEY AUTOINCREMENT,
    stable_id TEXT NOT NULL,
    source_kind TEXT NOT NULL,
    adapter_version TEXT NOT NULL,
    provider_name TEXT NOT NULL,
    endpoint_url TEXT NOT NULL,
    delivery_format TEXT,
    coverage_note TEXT NOT NULL,
    enabled INTEGER NOT NULL CHECK (enabled IN (0, 1)),
    cadence_seconds INTEGER NOT NULL CHECK (cadence_seconds > 0),
    availability_seconds INTEGER NOT NULL CHECK (availability_seconds > 0),
    trust_weight REAL NOT NULL CHECK (trust_weight >= 0 AND trust_weight <= 1),
    independence_group TEXT NOT NULL,
    language_scope TEXT,
    region_scope TEXT,
    quota_limit INTEGER CHECK (quota_limit IS NULL OR quota_limit > 0),
    secret_ref TEXT,
    config_json TEXT NOT NULL CHECK (json_valid(config_json)),
    config_fingerprint TEXT NOT NULL CHECK (length(config_fingerprint) = 64),
    configuration_release_id INTEGER NOT NULL
        REFERENCES configuration_releases(configuration_release_id)
        ON DELETE RESTRICT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (stable_id, configuration_release_id)
);

CREATE INDEX ix_detection_source_instances_enabled
    ON detection_source_instances(configuration_release_id, enabled, source_kind, stable_id);

CREATE TABLE detection_cluster_aliases (
    detection_cluster_alias_id INTEGER PRIMARY KEY AUTOINCREMENT,
    alias_key TEXT NOT NULL,
    target_cluster_key TEXT NOT NULL,
    canonicalization_version TEXT NOT NULL,
    configuration_version TEXT NOT NULL,
    active INTEGER NOT NULL CHECK (active IN (0, 1)),
    reason TEXT NOT NULL,
    configuration_release_id INTEGER NOT NULL
        REFERENCES configuration_releases(configuration_release_id)
        ON DELETE RESTRICT,
    created_at TEXT NOT NULL,
    UNIQUE (
        alias_key,
        canonicalization_version,
        configuration_version,
        configuration_release_id
    )
);

CREATE TABLE source_collection_attempts (
    source_collection_attempt_id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_instance_id INTEGER NOT NULL
        REFERENCES detection_source_instances(detection_source_instance_id)
        ON DELETE RESTRICT,
    configuration_release_id INTEGER NOT NULL
        REFERENCES configuration_releases(configuration_release_id)
        ON DELETE RESTRICT,
    scheduled_for TEXT NOT NULL,
    request_json TEXT NOT NULL CHECK (json_valid(request_json)),
    request_hash TEXT NOT NULL CHECK (length(request_hash) = 64),
    provider_time TEXT,
    collected_at TEXT,
    response_hash TEXT CHECK (response_hash IS NULL OR length(response_hash) = 64),
    item_count INTEGER NOT NULL DEFAULT 0 CHECK (item_count >= 0),
    complete INTEGER NOT NULL DEFAULT 0 CHECK (complete IN (0, 1)),
    quota_units_reserved INTEGER NOT NULL DEFAULT 0 CHECK (quota_units_reserved >= 0),
    status TEXT NOT NULL
        CHECK (status IN ('pending', 'claimed', 'running', 'completed', 'retry_wait', 'failed', 'cancelled')),
    claim_owner TEXT,
    claimed_at TEXT,
    lease_expires_at TEXT,
    claim_version INTEGER NOT NULL DEFAULT 0 CHECK (claim_version >= 0),
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    attempt_limit INTEGER NOT NULL CHECK (attempt_limit > 0),
    next_attempt_at TEXT,
    failure_category TEXT,
    failure_detail TEXT,
    created_at TEXT NOT NULL,
    completed_at TEXT,
    UNIQUE (source_instance_id, scheduled_for, configuration_release_id)
);

CREATE INDEX ix_source_collection_attempts_pickup
    ON source_collection_attempts(status, scheduled_for, next_attempt_at);

CREATE TABLE source_request_executions (
    source_request_execution_id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_collection_attempt_id INTEGER NOT NULL
        REFERENCES source_collection_attempts(source_collection_attempt_id)
        ON DELETE RESTRICT,
    source_instance_id INTEGER NOT NULL
        REFERENCES detection_source_instances(detection_source_instance_id)
        ON DELETE RESTRICT,
    request_ordinal INTEGER NOT NULL CHECK (request_ordinal > 0),
    quota_day TEXT NOT NULL,
    quota_units INTEGER NOT NULL DEFAULT 0 CHECK (quota_units >= 0),
    status TEXT NOT NULL CHECK (status IN ('reserved', 'succeeded', 'failed')),
    reserved_at TEXT NOT NULL,
    completed_at TEXT,
    error_category TEXT,
    error_detail TEXT,
    UNIQUE (source_collection_attempt_id, request_ordinal)
);

CREATE INDEX ix_source_request_executions_quota
    ON source_request_executions(source_instance_id, quota_day, quota_units);

CREATE TABLE source_health (
    source_health_id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_instance_id INTEGER NOT NULL
        REFERENCES detection_source_instances(detection_source_instance_id)
        ON DELETE RESTRICT,
    source_collection_attempt_id INTEGER NOT NULL UNIQUE
        REFERENCES source_collection_attempts(source_collection_attempt_id)
        ON DELETE RESTRICT,
    window_start TEXT,
    window_end TEXT,
    item_count INTEGER NOT NULL CHECK (item_count >= 0),
    complete INTEGER NOT NULL CHECK (complete IN (0, 1)),
    classification TEXT NOT NULL
        CHECK (classification IN ('healthy', 'degraded', 'unavailable', 'quota_limited', 'failed')),
    reason TEXT NOT NULL,
    fallback_mode TEXT,
    latency_ms INTEGER CHECK (latency_ms IS NULL OR latency_ms >= 0),
    error_category TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX ix_source_health_source_time
    ON source_health(source_instance_id, created_at);

CREATE TABLE trends (
    trend_id INTEGER PRIMARY KEY AUTOINCREMENT,
    canonical_key TEXT NOT NULL,
    canonicalization_version TEXT NOT NULL,
    canonical_subject TEXT NOT NULL,
    first_observed_at TEXT NOT NULL,
    last_observed_at TEXT NOT NULL,
    current_metadata_json TEXT NOT NULL CHECK (json_valid(current_metadata_json)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (canonical_key, canonicalization_version)
);

CREATE TABLE trend_observations (
    trend_observation_id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_collection_attempt_id INTEGER NOT NULL
        REFERENCES source_collection_attempts(source_collection_attempt_id)
        ON DELETE RESTRICT,
    source_instance_id INTEGER NOT NULL
        REFERENCES detection_source_instances(detection_source_instance_id)
        ON DELETE RESTRICT,
    trend_id INTEGER NOT NULL REFERENCES trends(trend_id) ON DELETE RESTRICT,
    source_item_id TEXT,
    source_item_key TEXT NOT NULL,
    canonical_url TEXT,
    provider_time TEXT,
    effective_observed_at TEXT NOT NULL,
    collected_at TEXT NOT NULL,
    window_start TEXT NOT NULL,
    window_end TEXT NOT NULL,
    activity REAL NOT NULL CHECK (activity >= 0),
    rank INTEGER CHECK (rank IS NULL OR rank > 0),
    title TEXT NOT NULL CHECK (length(title) BETWEEN 1 AND 512),
    payload_json TEXT NOT NULL CHECK (json_valid(payload_json)),
    activity_contributor INTEGER NOT NULL CHECK (activity_contributor IN (0, 1)),
    created_at TEXT NOT NULL,
    UNIQUE (source_collection_attempt_id, source_item_key)
);

CREATE INDEX ix_trend_observations_window
    ON trend_observations(source_instance_id, window_start, window_end);
CREATE INDEX ix_trend_observations_trend_time
    ON trend_observations(trend_id, effective_observed_at);

CREATE TABLE source_item_events (
    source_item_event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_collection_attempt_id INTEGER NOT NULL
        REFERENCES source_collection_attempts(source_collection_attempt_id)
        ON DELETE RESTRICT,
    source_instance_id INTEGER NOT NULL
        REFERENCES detection_source_instances(detection_source_instance_id)
        ON DELETE RESTRICT,
    source_ordinal INTEGER CHECK (source_ordinal IS NULL OR source_ordinal > 0),
    source_item_key TEXT,
    disposition TEXT NOT NULL
        CHECK (disposition IN (
            'rejected_invalid', 'rejected_oversized', 'excluded_dead',
            'excluded_deleted', 'excluded_non_story',
            'excluded_out_of_scope', 'duplicate_suppressed'
        )),
    reason TEXT NOT NULL,
    payload_hash TEXT CHECK (payload_hash IS NULL OR length(payload_hash) = 64),
    created_at TEXT NOT NULL
);

CREATE INDEX ix_source_item_events_attempt
    ON source_item_events(source_collection_attempt_id, source_ordinal);

CREATE TABLE scout_evaluation_runs (
    scout_evaluation_run_id INTEGER PRIMARY KEY AUTOINCREMENT,
    evaluation_slot_start TEXT NOT NULL,
    configuration_release_id INTEGER NOT NULL
        REFERENCES configuration_releases(configuration_release_id)
        ON DELETE RESTRICT,
    input_frozen_at TEXT,
    input_hash TEXT CHECK (input_hash IS NULL OR length(input_hash) = 64),
    aggregate_counts_json TEXT NOT NULL DEFAULT '{}'
        CHECK (json_valid(aggregate_counts_json)),
    status TEXT NOT NULL
        CHECK (status IN ('pending', 'claimed', 'running', 'completed', 'retry_wait', 'failed', 'cancelled')),
    claim_owner TEXT,
    claimed_at TEXT,
    lease_expires_at TEXT,
    claim_version INTEGER NOT NULL DEFAULT 0 CHECK (claim_version >= 0),
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    attempt_limit INTEGER NOT NULL CHECK (attempt_limit > 0),
    next_attempt_at TEXT,
    failure_category TEXT,
    failure_detail TEXT,
    created_at TEXT NOT NULL,
    completed_at TEXT,
    UNIQUE (evaluation_slot_start, configuration_release_id)
);

CREATE INDEX ix_scout_evaluation_runs_pickup
    ON scout_evaluation_runs(status, evaluation_slot_start, next_attempt_at);

CREATE TABLE scout_evaluation_inputs (
    scout_evaluation_input_id INTEGER PRIMARY KEY AUTOINCREMENT,
    scout_evaluation_run_id INTEGER NOT NULL
        REFERENCES scout_evaluation_runs(scout_evaluation_run_id)
        ON DELETE RESTRICT,
    source_instance_id INTEGER NOT NULL
        REFERENCES detection_source_instances(detection_source_instance_id)
        ON DELETE RESTRICT,
    source_collection_attempt_id INTEGER
        REFERENCES source_collection_attempts(source_collection_attempt_id)
        ON DELETE RESTRICT,
    source_health_id INTEGER REFERENCES source_health(source_health_id) ON DELETE RESTRICT,
    input_state TEXT NOT NULL
        CHECK (input_state IN ('current', 'reused', 'degraded', 'unavailable', 'failed', 'quota_limited')),
    reason TEXT NOT NULL,
    ordinal INTEGER NOT NULL CHECK (ordinal > 0),
    created_at TEXT NOT NULL,
    UNIQUE (scout_evaluation_run_id, source_instance_id),
    UNIQUE (scout_evaluation_run_id, ordinal)
);

CREATE TABLE scout_evaluation_attempts (
    scout_evaluation_attempt_id INTEGER PRIMARY KEY AUTOINCREMENT,
    scout_evaluation_run_id INTEGER NOT NULL
        REFERENCES scout_evaluation_runs(scout_evaluation_run_id)
        ON DELETE RESTRICT,
    source_instance_id INTEGER NOT NULL
        REFERENCES detection_source_instances(detection_source_instance_id)
        ON DELETE RESTRICT,
    source_collection_attempt_id INTEGER NOT NULL
        REFERENCES source_collection_attempts(source_collection_attempt_id)
        ON DELETE RESTRICT,
    measurement_role TEXT NOT NULL
        CHECK (measurement_role IN ('current_window', 'baseline_window')),
    ordinal INTEGER NOT NULL CHECK (ordinal > 0),
    created_at TEXT NOT NULL,
    UNIQUE (scout_evaluation_run_id, source_collection_attempt_id),
    UNIQUE (scout_evaluation_run_id, source_instance_id, measurement_role, ordinal)
);

CREATE INDEX ix_scout_evaluation_attempts_run_source
    ON scout_evaluation_attempts(scout_evaluation_run_id, source_instance_id, measurement_role);

CREATE TABLE topic_snapshots (
    topic_snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT,
    scout_evaluation_run_id INTEGER NOT NULL
        REFERENCES scout_evaluation_runs(scout_evaluation_run_id)
        ON DELETE RESTRICT,
    cluster_key TEXT NOT NULL,
    opportunity_identity TEXT NOT NULL,
    canonical_subject TEXT NOT NULL,
    score REAL NOT NULL CHECK (score >= 0 AND score <= 1),
    score_breakdown_json TEXT NOT NULL CHECK (json_valid(score_breakdown_json)),
    evidence_snapshot_json TEXT NOT NULL CHECK (json_valid(evidence_snapshot_json)),
    evidence_fingerprint TEXT NOT NULL CHECK (length(evidence_fingerprint) = 64),
    score_formula_version TEXT NOT NULL,
    canonicalization_version TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (scout_evaluation_run_id, cluster_key)
);

CREATE TABLE trend_candidates (
    trend_candidate_id INTEGER PRIMARY KEY AUTOINCREMENT,
    opportunity_identity TEXT NOT NULL UNIQUE,
    cluster_key TEXT NOT NULL,
    canonical_subject TEXT NOT NULL,
    latest_topic_snapshot_id INTEGER NOT NULL
        REFERENCES topic_snapshots(topic_snapshot_id)
        ON DELETE RESTRICT,
    latest_evidence_fingerprint TEXT NOT NULL
        CHECK (length(latest_evidence_fingerprint) = 64),
    score REAL NOT NULL CHECK (score >= 0 AND score <= 1),
    score_breakdown_json TEXT NOT NULL CHECK (json_valid(score_breakdown_json)),
    score_formula_version TEXT NOT NULL,
    canonicalization_version TEXT NOT NULL,
    eligibility_status TEXT NOT NULL
        CHECK (eligibility_status IN (
            'observed', 'eligible', 'selected', 'deferred_by_budget',
            'deferred_stale', 'rejected_cooldown', 'reconsiderable',
            'consumed', 'migration_hold'
        )),
    eligibility_reason TEXT NOT NULL,
    rank INTEGER CHECK (rank IS NULL OR rank > 0),
    cooldown_until TEXT,
    selected_at TEXT,
    selected_thread_id INTEGER
        REFERENCES content_threads(thread_id)
        ON DELETE RESTRICT,
    last_determination_outcome TEXT,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX ix_trend_candidates_feed
    ON trend_candidates(eligibility_status, score DESC, updated_at DESC);

CREATE TABLE candidate_observation_memberships (
    candidate_observation_membership_id INTEGER PRIMARY KEY AUTOINCREMENT,
    trend_candidate_id INTEGER NOT NULL
        REFERENCES trend_candidates(trend_candidate_id)
        ON DELETE RESTRICT,
    topic_snapshot_id INTEGER NOT NULL
        REFERENCES topic_snapshots(topic_snapshot_id)
        ON DELETE RESTRICT,
    trend_observation_id INTEGER NOT NULL
        REFERENCES trend_observations(trend_observation_id)
        ON DELETE RESTRICT,
    ordinal INTEGER NOT NULL CHECK (ordinal > 0),
    contribution REAL NOT NULL CHECK (contribution >= 0),
    snapshot_json TEXT NOT NULL CHECK (json_valid(snapshot_json)),
    created_at TEXT NOT NULL,
    UNIQUE (topic_snapshot_id, trend_observation_id),
    UNIQUE (topic_snapshot_id, ordinal)
);

CREATE TABLE content_threads (
    thread_id INTEGER PRIMARY KEY AUTOINCREMENT,
    origin TEXT NOT NULL CHECK (origin IN ('trend', 'human', 'legacy')),
    seed_candidate_id INTEGER
        REFERENCES trend_candidates(trend_candidate_id)
        ON DELETE RESTRICT,
    coverage_identity TEXT UNIQUE,
    status TEXT NOT NULL CHECK (status IN ('open', 'closed', 'cancelled')),
    closure_actor TEXT,
    closure_reason TEXT,
    closed_at TEXT,
    cancelled_at TEXT,
    row_version INTEGER NOT NULL DEFAULT 1 CHECK (row_version > 0),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    CHECK (origin <> 'trend' OR seed_candidate_id IS NOT NULL),
    UNIQUE (seed_candidate_id)
);

CREATE TABLE intake_requests (
    intake_request_id INTEGER PRIMARY KEY AUTOINCREMENT,
    thread_id INTEGER NOT NULL REFERENCES content_threads(thread_id) ON DELETE RESTRICT,
    source_candidate_id INTEGER
        REFERENCES trend_candidates(trend_candidate_id)
        ON DELETE RESTRICT,
    source_evidence_event_id INTEGER
        REFERENCES thread_evidence_events(thread_evidence_event_id)
        ON DELETE RESTRICT,
    context_json TEXT NOT NULL CHECK (json_valid(context_json)),
    context_version TEXT NOT NULL,
    status TEXT NOT NULL
        CHECK (status IN ('pending', 'claimed', 'retry_wait', 'needs_clarification', 'completed', 'failed', 'cancelled')),
    claim_owner TEXT,
    claimed_at TEXT,
    lease_expires_at TEXT,
    claim_version INTEGER NOT NULL DEFAULT 0 CHECK (claim_version >= 0),
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    attempt_limit INTEGER NOT NULL CHECK (attempt_limit > 0),
    next_attempt_at TEXT,
    failure_category TEXT,
    failure_detail TEXT,
    created_at TEXT NOT NULL,
    completed_at TEXT
);

CREATE UNIQUE INDEX uq_intake_requests_active_thread
    ON intake_requests(thread_id)
    WHERE status IN ('pending', 'claimed', 'retry_wait');
CREATE INDEX ix_intake_requests_pickup
    ON intake_requests(status, next_attempt_at, created_at);

CREATE TABLE thread_evidence_events (
    thread_evidence_event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    thread_id INTEGER NOT NULL REFERENCES content_threads(thread_id) ON DELETE RESTRICT,
    candidate_id INTEGER NOT NULL
        REFERENCES trend_candidates(trend_candidate_id)
        ON DELETE RESTRICT,
    prior_evidence_fingerprint TEXT NOT NULL CHECK (length(prior_evidence_fingerprint) = 64),
    current_evidence_fingerprint TEXT NOT NULL CHECK (length(current_evidence_fingerprint) = 64),
    comparator_version TEXT NOT NULL,
    material INTEGER NOT NULL CHECK (material IN (0, 1)),
    materiality_reason TEXT NOT NULL,
    evidence_snapshot_json TEXT NOT NULL CHECK (json_valid(evidence_snapshot_json)),
    result_intake_request_id INTEGER
        REFERENCES intake_requests(intake_request_id)
        ON DELETE RESTRICT,
    created_at TEXT NOT NULL
);

CREATE TABLE worker_heartbeats (
    worker_heartbeat_id INTEGER PRIMARY KEY AUTOINCREMENT,
    worker_type TEXT NOT NULL,
    instance_id TEXT NOT NULL,
    started_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    state TEXT NOT NULL,
    claim_type TEXT,
    claim_id INTEGER,
    build_version TEXT NOT NULL,
    safe_summary TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (worker_type, instance_id)
);

CREATE TABLE worker_runs (
    worker_run_id INTEGER PRIMARY KEY AUTOINCREMENT,
    worker_type TEXT NOT NULL,
    instance_id TEXT NOT NULL,
    claim_type TEXT,
    claim_id INTEGER,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    status TEXT NOT NULL,
    safe_summary TEXT,
    safe_error TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX ix_worker_runs_type_time
    ON worker_runs(worker_type, created_at DESC);

PRAGMA user_version = 1;
