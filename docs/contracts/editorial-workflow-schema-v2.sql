-- Forward migration: editorial, production, review, and delivery workflow.
-- Applied only after detection_dashboard_schema_v1; do not edit v1.

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
    revision_reason TEXT NOT NULL CHECK (revision_reason IN ('initial','human_rework','evidence_refresh','capability_recheck','migration')),
    created_by TEXT NOT NULL CHECK (created_by IN ('intake_agent','system','system_migration')),
    source_intake_request_id INTEGER UNIQUE REFERENCES intake_requests(intake_request_id) ON DELETE RESTRICT,
    source_evidence_event_id INTEGER REFERENCES thread_evidence_events(thread_evidence_event_id) ON DELETE RESTRICT,
    source_blocked_decision_id INTEGER,
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
    platform TEXT NOT NULL CHECK (platform IN ('instagram','x')),
    account TEXT NOT NULL,
    content_format TEXT NOT NULL,
    output_contract_version TEXT NOT NULL,
    renderer_compatibility TEXT NOT NULL,
    ready INTEGER NOT NULL CHECK (ready IN (0,1)),
    safe_reason TEXT NOT NULL,
    created_at TEXT NOT NULL,
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
CREATE INDEX ix_determination_requests_pickup ON determination_requests(status,next_attempt_at,created_at);

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
    disposition TEXT NOT NULL CHECK (disposition IN ('selected','skipped','blocked','reused')),
    fit TEXT NOT NULL, reason TEXT NOT NULL,
    angle_json TEXT CHECK (angle_json IS NULL OR json_valid(angle_json)),
    evidence_json TEXT NOT NULL CHECK (json_valid(evidence_json)),
    output_assessments_json TEXT NOT NULL CHECK (json_valid(output_assessments_json)),
    reuse_canonical_content_id INTEGER, created_at TEXT NOT NULL,
    UNIQUE(determination_decision_id,pipeline_id)
);

CREATE TABLE content_jobs (
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
CREATE UNIQUE INDEX uq_generation_active_job ON generation_runs(content_job_id) WHERE status IN ('waiting_capacity','pending','claimed','running','retry_wait');

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
    output_request_id INTEGER NOT NULL REFERENCES output_requests(output_request_id) ON DELETE RESTRICT,
    run_number INTEGER NOT NULL CHECK(run_number>0),
    status TEXT NOT NULL CHECK(status IN ('waiting_capacity','pending','claimed','running','retry_wait','succeeded','failed','cancelled')),
    claim_owner TEXT, claimed_at TEXT, lease_expires_at TEXT, claim_version INTEGER NOT NULL DEFAULT 0,
    attempt_count INTEGER NOT NULL DEFAULT 0, attempt_limit INTEGER NOT NULL, next_attempt_at TEXT,
    failure_reason TEXT, created_at TEXT NOT NULL, completed_at TEXT,
    UNIQUE(output_request_id,run_number)
);
CREATE UNIQUE INDEX uq_adaptation_active_output ON adaptation_runs(output_request_id) WHERE status IN ('waiting_capacity','pending','claimed','running','retry_wait');

CREATE TABLE content_packages (
    content_package_id INTEGER PRIMARY KEY AUTOINCREMENT,
    output_request_id INTEGER NOT NULL UNIQUE REFERENCES output_requests(output_request_id) ON DELETE RESTRICT,
    adaptation_run_id INTEGER NOT NULL UNIQUE REFERENCES adaptation_runs(adaptation_run_id) ON DELETE RESTRICT,
    package_json TEXT NOT NULL CHECK(json_valid(package_json)), content_hash TEXT NOT NULL CHECK(length(content_hash)=64),
    visual_spec_json TEXT NOT NULL CHECK(json_valid(visual_spec_json)), created_at TEXT NOT NULL
);

CREATE TABLE render_runs (
    render_run_id INTEGER PRIMARY KEY AUTOINCREMENT,
    content_package_id INTEGER NOT NULL REFERENCES content_packages(content_package_id) ON DELETE RESTRICT,
    run_number INTEGER NOT NULL CHECK(run_number>0),
    status TEXT NOT NULL CHECK(status IN ('pending','claimed','running','retry_wait','succeeded','failed','cancelled')),
    claim_owner TEXT, claimed_at TEXT, lease_expires_at TEXT, claim_version INTEGER NOT NULL DEFAULT 0,
    attempt_count INTEGER NOT NULL DEFAULT 0, attempt_limit INTEGER NOT NULL, next_attempt_at TEXT,
    manifest_json TEXT CHECK(manifest_json IS NULL OR json_valid(manifest_json)), failure_reason TEXT, created_at TEXT NOT NULL, completed_at TEXT,
    UNIQUE(content_package_id,run_number)
);

CREATE TABLE render_assets (
    render_asset_id INTEGER PRIMARY KEY AUTOINCREMENT,
    render_run_id INTEGER NOT NULL REFERENCES render_runs(render_run_id) ON DELETE RESTRICT,
    asset_role TEXT NOT NULL, ordinal INTEGER NOT NULL CHECK(ordinal>0), local_path TEXT NOT NULL,
    mime_type TEXT NOT NULL, width INTEGER NOT NULL, height INTEGER NOT NULL, bytes INTEGER NOT NULL,
    sha256 TEXT NOT NULL CHECK(length(sha256)=64), created_at TEXT NOT NULL, UNIQUE(render_run_id,asset_role,ordinal)
);

CREATE TABLE review_requests (
    review_request_id INTEGER PRIMARY KEY AUTOINCREMENT,
    content_package_id INTEGER NOT NULL REFERENCES content_packages(content_package_id) ON DELETE RESTRICT,
    render_run_id INTEGER NOT NULL REFERENCES render_runs(render_run_id) ON DELETE RESTRICT,
    review_cycle_number INTEGER NOT NULL, package_hash TEXT NOT NULL CHECK(length(package_hash)=64), manifest_hash TEXT NOT NULL CHECK(length(manifest_hash)=64),
    status TEXT NOT NULL CHECK(status IN ('awaiting_review','approved','changes_requested','rejected','invalidated','expired','cancelled')),
    expires_at TEXT NOT NULL, row_version INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL, decided_at TEXT, decision_note TEXT, actor_id TEXT,
    UNIQUE(content_package_id,render_run_id,review_cycle_number)
);

CREATE TABLE post_requests (
    post_request_id INTEGER PRIMARY KEY AUTOINCREMENT,
    review_request_id INTEGER NOT NULL UNIQUE REFERENCES review_requests(review_request_id) ON DELETE RESTRICT,
    content_package_id INTEGER NOT NULL REFERENCES content_packages(content_package_id) ON DELETE RESTRICT,
    status TEXT NOT NULL CHECK(status IN ('approved','cancelled','expired','fulfilled')), delivery_mode TEXT NOT NULL CHECK(delivery_mode='immediate'),
    publication_identity TEXT NOT NULL UNIQUE, row_version INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL, expires_at TEXT NOT NULL
);
CREATE TABLE post_records (
    post_record_id INTEGER PRIMARY KEY AUTOINCREMENT,
    post_request_id INTEGER NOT NULL UNIQUE REFERENCES post_requests(post_request_id) ON DELETE RESTRICT,
    status TEXT NOT NULL CHECK(status IN ('pending','claimed','publishing','retry_wait','failed','published','publication_unknown','cancelled','expired')),
    eligible_at TEXT NOT NULL, claim_owner TEXT, claimed_at TEXT, lease_expires_at TEXT, claim_version INTEGER NOT NULL DEFAULT 0,
    attempt_count INTEGER NOT NULL DEFAULT 0, attempt_limit INTEGER NOT NULL, next_attempt_at TEXT, failure_reason TEXT,
    row_version INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL, completed_at TEXT
);

CREATE TABLE model_invocations (
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
);

PRAGMA user_version = 2;
