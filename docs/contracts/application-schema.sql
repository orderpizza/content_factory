-- Current application schema for explicit fresh-database initialization.

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
            'consumed'
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
    origin TEXT NOT NULL CHECK (origin IN ('trend', 'human')),
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

CREATE TABLE thread_messages (
    message_id INTEGER PRIMARY KEY AUTOINCREMENT,
    thread_id INTEGER NOT NULL REFERENCES content_threads(thread_id) ON DELETE RESTRICT,
    sequence_number INTEGER NOT NULL CHECK (sequence_number > 0),
    author_kind TEXT NOT NULL CHECK (author_kind IN ('human','intake_agent','system')),
    body TEXT NOT NULL CHECK (length(body) > 0 AND length(body) <= 8000),
    in_reply_to_message_id INTEGER REFERENCES thread_messages(message_id) ON DELETE RESTRICT,
    created_at TEXT NOT NULL,
    UNIQUE(thread_id, sequence_number)
);

CREATE TABLE human_command_receipts (
    human_command_receipt_id INTEGER PRIMARY KEY AUTOINCREMENT,
    command_id TEXT NOT NULL UNIQUE,
    command_kind TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    payload_hash TEXT NOT NULL CHECK(length(payload_hash)=64),
    result_record_id INTEGER NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE brief_revisions (
    revision_id INTEGER PRIMARY KEY AUTOINCREMENT,
    thread_id INTEGER NOT NULL REFERENCES content_threads(thread_id) ON DELETE RESTRICT,
    revision_number INTEGER NOT NULL CHECK (revision_number > 0),
    parent_revision_id INTEGER REFERENCES brief_revisions(revision_id) ON DELETE RESTRICT,
    input_through_message_id INTEGER REFERENCES thread_messages(message_id) ON DELETE RESTRICT,
    brief_json TEXT NOT NULL CHECK (json_valid(brief_json)),
    source_snapshot_json TEXT NOT NULL CHECK (json_valid(source_snapshot_json)),
    revision_reason TEXT NOT NULL CHECK (revision_reason IN ('initial','human_rework','evidence_refresh','capability_recheck')),
    created_by TEXT NOT NULL CHECK (created_by IN ('intake_agent','system')),
    source_intake_request_id INTEGER UNIQUE REFERENCES intake_requests(intake_request_id) ON DELETE RESTRICT,
    created_at TEXT NOT NULL,
    UNIQUE(thread_id, revision_number)
);

CREATE TABLE pipeline_capabilities (
    pipeline_capability_id INTEGER PRIMARY KEY AUTOINCREMENT,
    pipeline_id TEXT NOT NULL,
    pipeline_version TEXT NOT NULL,
    enabled INTEGER NOT NULL CHECK (enabled IN (0,1)),
    remit_json TEXT NOT NULL CHECK (json_valid(remit_json)),
    generation_ready INTEGER NOT NULL CHECK (generation_ready IN (0,1)),
    configuration_release_id INTEGER REFERENCES configuration_releases(configuration_release_id) ON DELETE RESTRICT,
    created_at TEXT NOT NULL,
    UNIQUE(pipeline_id, pipeline_version, configuration_release_id)
);

CREATE TABLE output_bindings (
    output_binding_id INTEGER PRIMARY KEY AUTOINCREMENT,
    pipeline_capability_id INTEGER NOT NULL REFERENCES pipeline_capabilities(pipeline_capability_id) ON DELETE RESTRICT,
    platform TEXT NOT NULL CHECK (platform IN ('instagram')),
    account TEXT NOT NULL,
    content_format TEXT NOT NULL,
    output_contract_version TEXT NOT NULL,
    ready INTEGER NOT NULL CHECK (ready IN (0,1)),
    safe_reason TEXT NOT NULL,
    created_at TEXT NOT NULL, social_destination_id INTEGER
    REFERENCES social_destinations(social_destination_id) ON DELETE RESTRICT, delivery_enabled INTEGER NOT NULL DEFAULT 0
    CHECK(delivery_enabled IN (0,1)), visual_configuration_approved INTEGER NOT NULL DEFAULT 0
    CHECK(visual_configuration_approved IN (0,1)),
    UNIQUE(pipeline_capability_id, platform, account, content_format)
);

CREATE TABLE determination_requests (
    determination_request_id INTEGER PRIMARY KEY AUTOINCREMENT,
    revision_id INTEGER NOT NULL UNIQUE REFERENCES brief_revisions(revision_id) ON DELETE RESTRICT,
    input_snapshot_json TEXT NOT NULL CHECK (json_valid(input_snapshot_json)),
    input_fingerprint TEXT NOT NULL CHECK (length(input_fingerprint)=64),
    status TEXT NOT NULL CHECK (status IN ('pending','claimed','retry_wait','completed','failed','cancelled')),
    claim_owner TEXT, claimed_at TEXT, lease_expires_at TEXT,
    claim_version INTEGER NOT NULL DEFAULT 0 CHECK (claim_version >= 0),
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    attempt_limit INTEGER NOT NULL CHECK (attempt_limit > 0),
    next_attempt_at TEXT, failure_reason TEXT,
    created_at TEXT NOT NULL, completed_at TEXT
);

CREATE TABLE determination_decisions (
    determination_decision_id INTEGER PRIMARY KEY AUTOINCREMENT,
    determination_request_id INTEGER NOT NULL UNIQUE REFERENCES determination_requests(determination_request_id) ON DELETE RESTRICT,
    outcome TEXT NOT NULL CHECK (outcome IN ('accepted','not_recommended','blocked')),
    opportunity_value TEXT NOT NULL, rationale TEXT NOT NULL, warnings_json TEXT NOT NULL CHECK(json_valid(warnings_json)),
    coverage_identity TEXT NOT NULL, catalog_fingerprint TEXT NOT NULL CHECK(length(catalog_fingerprint)=64),
    readiness_fingerprint TEXT NOT NULL CHECK(length(readiness_fingerprint)=64), routing_policy_version TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE determination_routes (
    determination_route_id INTEGER PRIMARY KEY AUTOINCREMENT,
    determination_decision_id INTEGER NOT NULL REFERENCES determination_decisions(determination_decision_id) ON DELETE RESTRICT,
    pipeline_id TEXT NOT NULL,
    disposition TEXT NOT NULL CHECK (disposition IN ('selected','skipped','blocked')),
    fit TEXT NOT NULL, reason TEXT NOT NULL,
    evidence_json TEXT NOT NULL CHECK (json_valid(evidence_json)),
    output_assessments_json TEXT NOT NULL CHECK (json_valid(output_assessments_json)),
    created_at TEXT NOT NULL,
    UNIQUE(determination_decision_id,pipeline_id)
);

CREATE TABLE editorial_plan_runs (
    editorial_plan_run_id INTEGER PRIMARY KEY AUTOINCREMENT,
    determination_route_id INTEGER NOT NULL UNIQUE REFERENCES determination_routes(determination_route_id),
    revision_id INTEGER NOT NULL REFERENCES brief_revisions(revision_id),
    pipeline_id TEXT NOT NULL CHECK(pipeline_id IN ('english','ai_tech','psychology')),
    input_snapshot_json TEXT NOT NULL CHECK(json_valid(input_snapshot_json)),
    input_fingerprint TEXT NOT NULL CHECK(length(input_fingerprint)=64),
    status TEXT NOT NULL CHECK(status IN ('pending','claimed','retry_wait','succeeded','failed','cancelled')),
    claim_owner TEXT, claimed_at TEXT, lease_expires_at TEXT,
    claim_version INTEGER NOT NULL DEFAULT 0, attempt_count INTEGER NOT NULL DEFAULT 0,
    attempt_limit INTEGER NOT NULL CHECK(attempt_limit>0), next_attempt_at TEXT,
    failure_reason TEXT, created_at TEXT NOT NULL, completed_at TEXT
);
CREATE INDEX ix_editorial_pickup ON editorial_plan_runs(status,next_attempt_at,created_at);
CREATE TABLE editorial_plans (
    editorial_plan_id INTEGER PRIMARY KEY AUTOINCREMENT,
    editorial_plan_run_id INTEGER NOT NULL UNIQUE REFERENCES editorial_plan_runs(editorial_plan_run_id),
    determination_route_id INTEGER NOT NULL UNIQUE REFERENCES determination_routes(determination_route_id),
    brief_revision_id INTEGER NOT NULL REFERENCES brief_revisions(revision_id),
    pipeline_id TEXT NOT NULL CHECK(pipeline_id IN ('english','ai_tech','psychology')),
    lane TEXT NOT NULL CHECK(lane IN ('trend','evergreen','series','experiment')),
    schema_version TEXT NOT NULL CHECK(schema_version='editorial_plan_v1'),
    planner_version TEXT NOT NULL,
    input_fingerprint TEXT NOT NULL CHECK(length(input_fingerprint)=64),
    plan_json TEXT NOT NULL CHECK(json_valid(plan_json)),
    created_at TEXT NOT NULL
);
CREATE INDEX ix_editorial_history ON editorial_plans(pipeline_id,editorial_plan_id DESC);
CREATE TRIGGER editorial_input_immutable BEFORE UPDATE OF determination_route_id,revision_id,pipeline_id,input_snapshot_json,input_fingerprint ON editorial_plan_runs
BEGIN SELECT RAISE(ABORT,'editorial input is immutable'); END;
CREATE TRIGGER editorial_plan_immutable BEFORE UPDATE ON editorial_plans
BEGIN SELECT RAISE(ABORT,'editorial plan is immutable'); END;
CREATE TRIGGER editorial_plan_no_delete BEFORE DELETE ON editorial_plans
BEGIN SELECT RAISE(ABORT,'editorial plan is immutable'); END;
CREATE TRIGGER editorial_plan_lineage BEFORE INSERT ON editorial_plans
WHEN NOT EXISTS (SELECT 1 FROM editorial_plan_runs r WHERE r.editorial_plan_run_id=NEW.editorial_plan_run_id AND r.determination_route_id=NEW.determination_route_id AND r.revision_id=NEW.brief_revision_id AND r.pipeline_id=NEW.pipeline_id AND r.input_fingerprint=NEW.input_fingerprint AND r.status='claimed')
BEGIN SELECT RAISE(ABORT,'editorial plan lineage mismatch'); END;

CREATE TABLE content_jobs (
    editorial_plan_id INTEGER NOT NULL UNIQUE REFERENCES editorial_plans(editorial_plan_id),
    content_job_id INTEGER PRIMARY KEY AUTOINCREMENT,
    determination_route_id INTEGER NOT NULL UNIQUE REFERENCES determination_routes(determination_route_id) ON DELETE RESTRICT,
    brief_revision_id INTEGER NOT NULL REFERENCES brief_revisions(revision_id) ON DELETE RESTRICT,
    pipeline_id TEXT NOT NULL, content_identity TEXT NOT NULL UNIQUE,
    recipe_json TEXT NOT NULL CHECK(json_valid(recipe_json)), output_plan_json TEXT NOT NULL CHECK(json_valid(output_plan_json)),
    priority INTEGER NOT NULL CHECK(priority BETWEEN 0 AND 100), created_at TEXT NOT NULL
);

CREATE TABLE generation_runs (
    generation_run_id INTEGER PRIMARY KEY AUTOINCREMENT,
    content_job_id INTEGER NOT NULL REFERENCES content_jobs(content_job_id) ON DELETE RESTRICT,
    run_number INTEGER NOT NULL CHECK(run_number>0),
    status TEXT NOT NULL CHECK(status IN ('waiting_capacity','pending','claimed','running','retry_wait','succeeded','failed','cancelled')),
    claim_owner TEXT, claimed_at TEXT, lease_expires_at TEXT, claim_version INTEGER NOT NULL DEFAULT 0,
    attempt_count INTEGER NOT NULL DEFAULT 0, attempt_limit INTEGER NOT NULL, next_attempt_at TEXT,
    failure_reason TEXT, created_at TEXT NOT NULL, completed_at TEXT,
    UNIQUE(content_job_id,run_number)
);

CREATE TABLE canonical_contents (
    canonical_content_id INTEGER PRIMARY KEY AUTOINCREMENT,
    content_job_id INTEGER NOT NULL UNIQUE REFERENCES content_jobs(content_job_id) ON DELETE RESTRICT,
    generation_run_id INTEGER NOT NULL UNIQUE REFERENCES generation_runs(generation_run_id) ON DELETE RESTRICT,
    canonical_identity TEXT NOT NULL UNIQUE, canonical_json TEXT NOT NULL CHECK(json_valid(canonical_json)),
    canonical_hash TEXT NOT NULL CHECK(length(canonical_hash)=64), schema_version TEXT NOT NULL, created_at TEXT NOT NULL
);

CREATE TABLE output_requests (
    output_request_id INTEGER PRIMARY KEY AUTOINCREMENT,
    canonical_content_id INTEGER NOT NULL REFERENCES canonical_contents(canonical_content_id) ON DELETE RESTRICT,
    output_binding_id INTEGER REFERENCES output_bindings(output_binding_id) ON DELETE RESTRICT,
    platform TEXT NOT NULL, account TEXT NOT NULL, content_format TEXT NOT NULL,
    output_identity TEXT NOT NULL UNIQUE, output_contract_version TEXT NOT NULL,
    input_json TEXT NOT NULL CHECK(json_valid(input_json)), created_at TEXT NOT NULL
);

CREATE TABLE adaptation_runs (
    adaptation_run_id INTEGER PRIMARY KEY AUTOINCREMENT,
    visual_recipe_id INTEGER NOT NULL REFERENCES visual_recipes(visual_recipe_id) ON DELETE RESTRICT,
    output_request_id INTEGER NOT NULL REFERENCES output_requests(output_request_id) ON DELETE RESTRICT,
    run_number INTEGER NOT NULL CHECK(run_number>0),
    status TEXT NOT NULL CHECK(status IN ('waiting_capacity','pending','claimed','running','retry_wait','succeeded','failed','cancelled')),
    claim_owner TEXT, claimed_at TEXT, lease_expires_at TEXT, claim_version INTEGER NOT NULL DEFAULT 0,
    attempt_count INTEGER NOT NULL DEFAULT 0, attempt_limit INTEGER NOT NULL, next_attempt_at TEXT,
    failure_reason TEXT, created_at TEXT NOT NULL, completed_at TEXT, adapted_body_json TEXT
    CHECK(adapted_body_json IS NULL OR json_valid(adapted_body_json)), adapted_body_hash TEXT
    CHECK(adapted_body_hash IS NULL OR length(adapted_body_hash)=64), metadata_json TEXT
    CHECK(metadata_json IS NULL OR json_valid(metadata_json)), metadata_hash TEXT
    CHECK(metadata_hash IS NULL OR length(metadata_hash)=64),
    UNIQUE(output_request_id,run_number)
);

CREATE TABLE content_packages (
    content_package_id INTEGER PRIMARY KEY AUTOINCREMENT,
    visual_recipe_id INTEGER NOT NULL REFERENCES visual_recipes(visual_recipe_id) ON DELETE RESTRICT,
    output_request_id INTEGER NOT NULL UNIQUE REFERENCES output_requests(output_request_id) ON DELETE RESTRICT,
    adaptation_run_id INTEGER NOT NULL UNIQUE REFERENCES adaptation_runs(adaptation_run_id) ON DELETE RESTRICT,
    package_json TEXT NOT NULL CHECK(json_valid(package_json)), content_hash TEXT NOT NULL CHECK(length(content_hash)=64),
    visual_cues_json TEXT NOT NULL CHECK(json_valid(visual_cues_json)), created_at TEXT NOT NULL
);

CREATE TABLE visual_plan_runs (
    visual_plan_run_id INTEGER PRIMARY KEY AUTOINCREMENT,
    output_request_id INTEGER NOT NULL REFERENCES output_requests(output_request_id) ON DELETE RESTRICT,
    run_number INTEGER NOT NULL CHECK(run_number>0),
    status TEXT NOT NULL CHECK(status IN ('pending','claimed','running','retry_wait','succeeded','failed','cancelled','blocked')),
    claim_owner TEXT, claimed_at TEXT, lease_expires_at TEXT, claim_version INTEGER NOT NULL DEFAULT 0,
    attempt_count INTEGER NOT NULL DEFAULT 0, attempt_limit INTEGER NOT NULL, next_attempt_at TEXT,
    failure_reason TEXT, created_at TEXT NOT NULL, completed_at TEXT,
    UNIQUE(output_request_id,run_number)
);

CREATE TABLE visual_recipes (
    visual_recipe_id INTEGER PRIMARY KEY AUTOINCREMENT,
    output_request_id INTEGER NOT NULL REFERENCES output_requests(output_request_id) ON DELETE RESTRICT,
    visual_plan_run_id INTEGER NOT NULL UNIQUE REFERENCES visual_plan_runs(visual_plan_run_id) ON DELETE RESTRICT,
    recipe_json TEXT NOT NULL CHECK(json_valid(recipe_json)), recipe_hash TEXT NOT NULL CHECK(length(recipe_hash)=64),
    selection_provenance_json TEXT NOT NULL CHECK(json_valid(selection_provenance_json)),
    created_at TEXT NOT NULL,
    UNIQUE(output_request_id)
);

CREATE TABLE storyboard_plan_runs (
    storyboard_plan_run_id INTEGER PRIMARY KEY AUTOINCREMENT,
    content_package_id INTEGER NOT NULL UNIQUE REFERENCES content_packages(content_package_id) ON DELETE RESTRICT,
    status TEXT NOT NULL CHECK(status IN ('pending','claimed','running','retry_wait','succeeded','failed','cancelled','blocked')),
    claim_owner TEXT, claimed_at TEXT, lease_expires_at TEXT, claim_version INTEGER NOT NULL DEFAULT 0,
    attempt_count INTEGER NOT NULL DEFAULT 0, attempt_limit INTEGER NOT NULL, next_attempt_at TEXT,
    failure_reason TEXT, created_at TEXT NOT NULL, completed_at TEXT
);

CREATE TABLE storyboard_plans (
    storyboard_plan_id INTEGER PRIMARY KEY AUTOINCREMENT,
    storyboard_plan_run_id INTEGER NOT NULL UNIQUE REFERENCES storyboard_plan_runs(storyboard_plan_run_id) ON DELETE RESTRICT,
    content_package_id INTEGER NOT NULL UNIQUE REFERENCES content_packages(content_package_id) ON DELETE RESTRICT,
    output_request_id INTEGER NOT NULL UNIQUE REFERENCES output_requests(output_request_id) ON DELETE RESTRICT,
    visual_recipe_id INTEGER NOT NULL REFERENCES visual_recipes(visual_recipe_id) ON DELETE RESTRICT,
    schema_version TEXT NOT NULL CHECK(schema_version='storyboard_plan_v1'),
    planner_version TEXT NOT NULL CHECK(planner_version='balanced_eight_largest_first_v1'),
    total_slides INTEGER NOT NULL CHECK(total_slides BETWEEN 4 AND 14),
    boards_json TEXT NOT NULL CHECK(json_valid(boards_json) AND json_type(boards_json)='array'),
    created_at TEXT NOT NULL
);

CREATE TABLE render_runs (
    storyboard_plan_id INTEGER NOT NULL UNIQUE REFERENCES storyboard_plans(storyboard_plan_id) ON DELETE RESTRICT,
    render_run_id INTEGER PRIMARY KEY AUTOINCREMENT,
    content_package_id INTEGER NOT NULL REFERENCES content_packages(content_package_id) ON DELETE RESTRICT,
    visual_recipe_id INTEGER NOT NULL REFERENCES visual_recipes(visual_recipe_id) ON DELETE RESTRICT,
    run_number INTEGER NOT NULL CHECK(run_number>0),
    status TEXT NOT NULL CHECK(status IN ('pending','claimed','running','retry_wait','succeeded','failed','cancelled','blocked')),
    claim_owner TEXT, claimed_at TEXT, lease_expires_at TEXT, claim_version INTEGER NOT NULL DEFAULT 0,
    attempt_count INTEGER NOT NULL DEFAULT 0, attempt_limit INTEGER NOT NULL, next_attempt_at TEXT,
    manifest_json TEXT CHECK(manifest_json IS NULL OR json_valid(manifest_json)), failure_reason TEXT, created_at TEXT NOT NULL, completed_at TEXT,
    UNIQUE(content_package_id,run_number), UNIQUE(visual_recipe_id)
);

CREATE TABLE render_assets (
    render_asset_id INTEGER PRIMARY KEY AUTOINCREMENT,
    render_run_id INTEGER NOT NULL REFERENCES render_runs(render_run_id) ON DELETE RESTRICT,
    asset_role TEXT NOT NULL, ordinal INTEGER NOT NULL CHECK(ordinal>0), local_path TEXT NOT NULL,
    mime_type TEXT NOT NULL, width INTEGER NOT NULL, height INTEGER NOT NULL, bytes INTEGER NOT NULL,
    sha256 TEXT NOT NULL CHECK(length(sha256)=64), created_at TEXT NOT NULL, encoder_version TEXT, deleted_at TEXT, deletion_reason TEXT, UNIQUE(render_run_id,asset_role,ordinal)
);

CREATE TABLE review_requests (
    review_request_id INTEGER PRIMARY KEY AUTOINCREMENT,
    content_package_id INTEGER NOT NULL REFERENCES content_packages(content_package_id) ON DELETE RESTRICT,
    render_run_id INTEGER NOT NULL REFERENCES render_runs(render_run_id) ON DELETE RESTRICT,
    review_cycle_number INTEGER NOT NULL, package_hash TEXT NOT NULL CHECK(length(package_hash)=64), manifest_hash TEXT NOT NULL CHECK(length(manifest_hash)=64),
    status TEXT NOT NULL CHECK(status IN ('awaiting_review','approved','changes_requested','rejected','invalidated','expired','cancelled')),
    expires_at TEXT NOT NULL, row_version INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL, decided_at TEXT, decision_note TEXT, actor_id TEXT, destination_key TEXT,
    UNIQUE(content_package_id,render_run_id,review_cycle_number)
);

CREATE TABLE post_requests (
    post_request_id INTEGER PRIMARY KEY AUTOINCREMENT,
    review_request_id INTEGER NOT NULL UNIQUE REFERENCES review_requests(review_request_id) ON DELETE RESTRICT,
    content_package_id INTEGER NOT NULL REFERENCES content_packages(content_package_id) ON DELETE RESTRICT,
    status TEXT NOT NULL CHECK(status IN ('approved','cancelled','expired','fulfilled')), delivery_mode TEXT NOT NULL CHECK(delivery_mode='immediate'),
    publication_identity TEXT NOT NULL UNIQUE, row_version INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL, expires_at TEXT NOT NULL
, render_run_id INTEGER
    REFERENCES render_runs(render_run_id) ON DELETE RESTRICT, package_hash TEXT
    CHECK(package_hash IS NULL OR length(package_hash)=64), manifest_hash TEXT
    CHECK(manifest_hash IS NULL OR length(manifest_hash)=64), destination_key TEXT);

CREATE TABLE post_records (
    post_record_id INTEGER PRIMARY KEY AUTOINCREMENT,
    post_request_id INTEGER NOT NULL UNIQUE REFERENCES post_requests(post_request_id) ON DELETE RESTRICT,
    status TEXT NOT NULL CHECK(status IN ('pending','claimed','publishing','retry_wait','failed','published','publication_unknown','cancelled','expired')),
    eligible_at TEXT NOT NULL, claim_owner TEXT, claimed_at TEXT, lease_expires_at TEXT, claim_version INTEGER NOT NULL DEFAULT 0,
    attempt_count INTEGER NOT NULL DEFAULT 0, attempt_limit INTEGER NOT NULL, next_attempt_at TEXT, failure_reason TEXT,
    row_version INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL, completed_at TEXT
, policy_snapshot_json TEXT
    CHECK(policy_snapshot_json IS NULL OR json_valid(policy_snapshot_json)), external_post_id TEXT, published_at TEXT, publication_unknown_at TEXT);

CREATE TABLE model_invocations (
    claim_version INTEGER NOT NULL DEFAULT 0,
    model_invocation_id INTEGER PRIMARY KEY AUTOINCREMENT, phase TEXT NOT NULL, entity_type TEXT NOT NULL, entity_id INTEGER NOT NULL,
    attempt_ordinal INTEGER NOT NULL, request_version TEXT NOT NULL, prompt_version TEXT NOT NULL, schema_version TEXT NOT NULL,
    request_hash TEXT NOT NULL CHECK(length(request_hash)=64), model_id TEXT, provider_request_id TEXT, response_hash TEXT,
    input_tokens INTEGER, output_tokens INTEGER, total_tokens INTEGER, estimated_cost_micro_usd INTEGER NOT NULL DEFAULT 0 CHECK(estimated_cost_micro_usd>=0),
    outcome TEXT NOT NULL CHECK(outcome IN ('started','succeeded','transport_failed','invalid_output','parse_failed','schema_failed','blocked')),
    safe_error TEXT, started_at TEXT NOT NULL, completed_at TEXT
);

CREATE TABLE gemini_budget_reservations (
    gemini_budget_reservation_id INTEGER PRIMARY KEY AUTOINCREMENT, accounting_day TEXT NOT NULL,
    model_invocation_id INTEGER UNIQUE REFERENCES model_invocations(model_invocation_id) ON DELETE RESTRICT,
    claim_type TEXT, claim_id INTEGER, worst_case_micro_usd INTEGER NOT NULL CHECK(worst_case_micro_usd>=0),
    settled_micro_usd INTEGER CHECK(settled_micro_usd IS NULL OR settled_micro_usd>=0),
    status TEXT NOT NULL CHECK(status IN ('reserved','settled','released','uncertain')), created_at TEXT NOT NULL, settled_at TEXT
, content_job_id INTEGER
    REFERENCES content_jobs(content_job_id) ON DELETE RESTRICT, phase TEXT, price_snapshot_hash TEXT
    CHECK(price_snapshot_hash IS NULL OR length(price_snapshot_hash)=64), max_input_tokens INTEGER
    CHECK(max_input_tokens IS NULL OR max_input_tokens>0), max_output_tokens INTEGER
    CHECK(max_output_tokens IS NULL OR max_output_tokens>0), daily_limit_micro_usd INTEGER
    CHECK(daily_limit_micro_usd IS NULL OR daily_limit_micro_usd>0), daily_warning_micro_usd INTEGER
    CHECK(daily_warning_micro_usd IS NULL OR daily_warning_micro_usd>0), job_limit_micro_usd INTEGER
    CHECK(job_limit_micro_usd IS NULL OR job_limit_micro_usd>0));

CREATE TABLE scout_frozen_evidence (
    scout_frozen_evidence_id INTEGER PRIMARY KEY AUTOINCREMENT,
    scout_evaluation_run_id INTEGER NOT NULL UNIQUE REFERENCES scout_evaluation_runs(scout_evaluation_run_id) ON DELETE RESTRICT,
    snapshot_version TEXT NOT NULL CHECK(snapshot_version='scout_input_v2'),
    snapshot_json TEXT NOT NULL CHECK(json_valid(snapshot_json)),
    snapshot_hash TEXT NOT NULL CHECK(length(snapshot_hash)=64),
    created_at TEXT NOT NULL
);

CREATE TABLE source_execution_evidence (
    source_execution_evidence_id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_request_execution_id INTEGER NOT NULL UNIQUE REFERENCES source_request_executions(source_request_execution_id) ON DELETE RESTRICT,
    complete INTEGER NOT NULL CHECK(complete IN (0,1)),
    response_hash TEXT NOT NULL CHECK(length(response_hash)=64),
    evidence_json TEXT NOT NULL CHECK(json_valid(evidence_json)),
    created_at TEXT NOT NULL
);

CREATE TABLE scout_prominence_populations (
    scout_prominence_population_id INTEGER PRIMARY KEY AUTOINCREMENT,
    scout_evaluation_run_id INTEGER NOT NULL REFERENCES scout_evaluation_runs(scout_evaluation_run_id) ON DELETE RESTRICT,
    source_kind TEXT NOT NULL,
    population_json TEXT NOT NULL CHECK(json_valid(population_json)),
    population_hash TEXT NOT NULL CHECK(length(population_hash)=64),
    created_at TEXT NOT NULL,
    UNIQUE(scout_evaluation_run_id, source_kind)
);

CREATE TABLE social_destinations (
    social_destination_id INTEGER PRIMARY KEY AUTOINCREMENT,
    configuration_release_id INTEGER NOT NULL
        REFERENCES configuration_releases(configuration_release_id) ON DELETE RESTRICT,
    destination_key TEXT NOT NULL,
    platform TEXT NOT NULL CHECK(platform IN ('instagram')),
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

CREATE TABLE scout_event_resolutions (
    scout_event_resolution_id INTEGER PRIMARY KEY AUTOINCREMENT,
    scout_evaluation_run_id INTEGER NOT NULL UNIQUE REFERENCES scout_evaluation_runs(scout_evaluation_run_id) ON DELETE RESTRICT,
    source_snapshot_hash TEXT NOT NULL CHECK(length(source_snapshot_hash)=64),
    resolution_json TEXT NOT NULL CHECK(json_valid(resolution_json)),
    resolution_hash TEXT NOT NULL CHECK(length(resolution_hash)=64),
    created_at TEXT NOT NULL
);

CREATE UNIQUE INDEX uq_configuration_activations_active_scope
    ON configuration_activations(scope_key)
    WHERE status = 'active';

CREATE INDEX ix_detection_source_instances_enabled
    ON detection_source_instances(configuration_release_id, enabled, source_kind, stable_id);

CREATE INDEX ix_source_collection_attempts_pickup
    ON source_collection_attempts(status, scheduled_for, next_attempt_at);

CREATE INDEX ix_source_request_executions_quota
    ON source_request_executions(source_instance_id, quota_day, quota_units);

CREATE INDEX ix_source_health_source_time
    ON source_health(source_instance_id, created_at);

CREATE INDEX ix_trend_observations_window
    ON trend_observations(source_instance_id, window_start, window_end);

CREATE INDEX ix_trend_observations_trend_time
    ON trend_observations(trend_id, effective_observed_at);

CREATE INDEX ix_source_item_events_attempt
    ON source_item_events(source_collection_attempt_id, source_ordinal);

CREATE INDEX ix_scout_evaluation_runs_pickup
    ON scout_evaluation_runs(status, evaluation_slot_start, next_attempt_at);

CREATE INDEX ix_scout_evaluation_attempts_run_source
    ON scout_evaluation_attempts(scout_evaluation_run_id, source_instance_id, measurement_role);

CREATE INDEX ix_trend_candidates_feed
    ON trend_candidates(eligibility_status, score DESC, updated_at DESC);

CREATE UNIQUE INDEX uq_intake_requests_active_thread
    ON intake_requests(thread_id)
    WHERE status IN ('pending', 'claimed', 'retry_wait');

CREATE INDEX ix_intake_requests_pickup
    ON intake_requests(status, next_attempt_at, created_at);

CREATE INDEX ix_worker_runs_type_time
    ON worker_runs(worker_type, created_at DESC);

CREATE INDEX ix_determination_requests_pickup ON determination_requests(status,next_attempt_at,created_at);

CREATE UNIQUE INDEX uq_generation_active_job ON generation_runs(content_job_id) WHERE status IN ('waiting_capacity','pending','claimed','running','retry_wait');

CREATE UNIQUE INDEX uq_adaptation_active_output ON adaptation_runs(output_request_id) WHERE status IN ('waiting_capacity','pending','claimed','running','retry_wait');
CREATE UNIQUE INDEX uq_visual_plan_active_output ON visual_plan_runs(output_request_id) WHERE status IN ('pending','claimed','running','retry_wait');

CREATE INDEX ix_delivery_cleanup_pickup
    ON delivery_cleanup_tasks(status,next_attempt_at,created_at);

CREATE UNIQUE INDEX uq_reconciliation_active_post
    ON reconciliation_requests(post_record_id)
    WHERE status IN ('pending','claimed','retry_wait','needs_human');

CREATE INDEX ix_post_records_pickup_v4 ON post_records(status,eligible_at,next_attempt_at);

CREATE INDEX ix_post_attempts_record ON post_attempts(post_record_id,attempt_number);

CREATE INDEX ix_publication_resources_attempt ON publication_resources(post_attempt_id,resource_type);

CREATE INDEX ix_budget_accounting_day ON gemini_budget_reservations(accounting_day,status);

CREATE INDEX ix_storage_samples_recent ON storage_samples(sampled_at DESC);

CREATE INDEX ix_maintenance_runs_kind ON maintenance_runs(kind,started_at DESC);

CREATE TRIGGER scout_prominence_populations_immutable BEFORE UPDATE ON scout_prominence_populations
BEGIN SELECT RAISE(ABORT, 'Scout prominence population is immutable'); END;

CREATE TRIGGER scout_frozen_evidence_immutable BEFORE UPDATE ON scout_frozen_evidence
BEGIN SELECT RAISE(ABORT, 'frozen Scout evidence is immutable'); END;

CREATE TRIGGER source_execution_evidence_immutable BEFORE UPDATE ON source_execution_evidence
BEGIN SELECT RAISE(ABORT, 'source execution evidence is immutable'); END;

CREATE TRIGGER observations_immutable BEFORE UPDATE ON trend_observations
BEGIN SELECT RAISE(ABORT, 'completed observation evidence is immutable'); END;

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

CREATE TRIGGER scout_event_resolutions_immutable BEFORE UPDATE ON scout_event_resolutions
BEGIN SELECT RAISE(ABORT, 'event resolution is immutable'); END;

CREATE TRIGGER scout_event_resolutions_no_delete BEFORE DELETE ON scout_event_resolutions
BEGIN SELECT RAISE(ABORT, 'event resolution is immutable'); END;

CREATE TRIGGER determination_input_immutable BEFORE UPDATE OF revision_id,input_snapshot_json,input_fingerprint ON determination_requests
BEGIN SELECT RAISE(ABORT, 'Determination input is immutable'); END;

CREATE TRIGGER visual_recipes_immutable_update BEFORE UPDATE ON visual_recipes
BEGIN SELECT RAISE(ABORT, 'visual recipe is immutable'); END;

CREATE TRIGGER visual_recipes_immutable_delete BEFORE DELETE ON visual_recipes
BEGIN SELECT RAISE(ABORT, 'visual recipe is immutable'); END;

PRAGMA user_version = 13;

CREATE TRIGGER adaptation_recipe_lineage BEFORE INSERT ON adaptation_runs
WHEN NOT EXISTS (SELECT 1 FROM visual_recipes v WHERE v.visual_recipe_id=NEW.visual_recipe_id AND v.output_request_id=NEW.output_request_id)
BEGIN SELECT RAISE(ABORT, 'adaptation recipe destination mismatch'); END;
CREATE TRIGGER package_recipe_lineage BEFORE INSERT ON content_packages
WHEN NOT EXISTS (SELECT 1 FROM adaptation_runs a WHERE a.adaptation_run_id=NEW.adaptation_run_id AND a.output_request_id=NEW.output_request_id AND a.visual_recipe_id=NEW.visual_recipe_id)
BEGIN SELECT RAISE(ABORT, 'package recipe lineage mismatch'); END;
CREATE TRIGGER render_recipe_lineage BEFORE INSERT ON render_runs
WHEN NOT EXISTS (SELECT 1 FROM content_packages p WHERE p.content_package_id=NEW.content_package_id AND p.visual_recipe_id=NEW.visual_recipe_id)
BEGIN SELECT RAISE(ABORT, 'render recipe lineage mismatch'); END;
CREATE TRIGGER recipe_plan_lineage BEFORE INSERT ON visual_recipes
WHEN NOT EXISTS (SELECT 1 FROM visual_plan_runs v WHERE v.visual_plan_run_id=NEW.visual_plan_run_id AND v.output_request_id=NEW.output_request_id)
BEGIN SELECT RAISE(ABORT, 'recipe plan destination mismatch'); END;
CREATE TRIGGER adaptation_recipe_immutable BEFORE UPDATE OF output_request_id,visual_recipe_id ON adaptation_runs
BEGIN SELECT RAISE(ABORT, 'adaptation recipe is immutable'); END;
CREATE TRIGGER visual_plan_input_immutable BEFORE UPDATE OF output_request_id ON visual_plan_runs
BEGIN SELECT RAISE(ABORT, 'visual plan input is immutable'); END;

CREATE TRIGGER package_visual_lineage_immutable BEFORE UPDATE OF output_request_id,adaptation_run_id,visual_recipe_id,package_json,content_hash,visual_cues_json ON content_packages
BEGIN SELECT RAISE(ABORT, 'content package is immutable'); END;
CREATE TRIGGER render_visual_lineage_immutable BEFORE UPDATE OF content_package_id,visual_recipe_id ON render_runs
BEGIN SELECT RAISE(ABORT, 'render lineage is immutable'); END;

CREATE TRIGGER content_job_editorial_lineage BEFORE INSERT ON content_jobs
WHEN NOT EXISTS (SELECT 1 FROM editorial_plans p WHERE p.editorial_plan_id=NEW.editorial_plan_id AND p.determination_route_id=NEW.determination_route_id AND p.brief_revision_id=NEW.brief_revision_id AND p.pipeline_id=NEW.pipeline_id)
BEGIN SELECT RAISE(ABORT,'ContentJob requires matching editorial plan'); END;
CREATE TRIGGER content_job_immutable BEFORE UPDATE ON content_jobs
BEGIN SELECT RAISE(ABORT,'ContentJob is immutable'); END;

CREATE TRIGGER editorial_run_lineage BEFORE INSERT ON editorial_plan_runs
WHEN NOT EXISTS (
    SELECT 1 FROM determination_routes r
    JOIN determination_decisions d USING(determination_decision_id)
    JOIN determination_requests q USING(determination_request_id)
    WHERE r.determination_route_id=NEW.determination_route_id
      AND r.pipeline_id=NEW.pipeline_id AND r.disposition='selected'
      AND q.revision_id=NEW.revision_id
)
BEGIN SELECT RAISE(ABORT,'editorial run requires selected route lineage'); END;

CREATE TRIGGER storyboard_run_input_immutable BEFORE UPDATE OF content_package_id ON storyboard_plan_runs
BEGIN SELECT RAISE(ABORT,'immutable storyboard input'); END;
CREATE TRIGGER storyboard_plan_immutable_update BEFORE UPDATE ON storyboard_plans
BEGIN SELECT RAISE(ABORT,'immutable storyboard plan'); END;
CREATE TRIGGER storyboard_plan_immutable_delete BEFORE DELETE ON storyboard_plans
BEGIN SELECT RAISE(ABORT,'immutable storyboard plan'); END;
CREATE TRIGGER storyboard_plan_lineage BEFORE INSERT ON storyboard_plans
WHEN NOT EXISTS (SELECT 1 FROM content_packages p JOIN storyboard_plan_runs r USING(content_package_id)
 WHERE p.content_package_id=NEW.content_package_id AND p.visual_recipe_id=NEW.visual_recipe_id
 AND p.output_request_id=NEW.output_request_id AND r.storyboard_plan_run_id=NEW.storyboard_plan_run_id)
BEGIN SELECT RAISE(ABORT,'storyboard lineage mismatch'); END;
CREATE TRIGGER render_storyboard_lineage BEFORE INSERT ON render_runs
WHEN NOT EXISTS (SELECT 1 FROM storyboard_plans s WHERE s.storyboard_plan_id=NEW.storyboard_plan_id
 AND s.content_package_id=NEW.content_package_id AND s.visual_recipe_id=NEW.visual_recipe_id)
BEGIN SELECT RAISE(ABORT,'render storyboard lineage mismatch'); END;
CREATE TRIGGER render_storyboard_immutable BEFORE UPDATE OF storyboard_plan_id ON render_runs
BEGIN SELECT RAISE(ABORT,'immutable render storyboard'); END;
