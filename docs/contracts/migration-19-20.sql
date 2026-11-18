-- Phase 4A: immutable observations; no changes to existing evidence.
CREATE TABLE measurement_observations (
    measurement_observation_id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_key TEXT NOT NULL UNIQUE,
    social_destination_id INTEGER NOT NULL REFERENCES social_destinations(social_destination_id) ON DELETE RESTRICT,
    post_record_id INTEGER REFERENCES post_records(post_record_id) ON DELETE RESTRICT,
    definition_version TEXT NOT NULL,
    metric TEXT NOT NULL,
    unit TEXT NOT NULL,
    scope TEXT NOT NULL CHECK(scope IN ('post','account')),
    provenance TEXT NOT NULL CHECK(provenance IN ('synthetic','authenticated_platform','human_estimate','not_collected')),
    value_status TEXT NOT NULL CHECK(value_status IN ('known','unknown','unavailable','not_authorized','not_collected')),
    value INTEGER CHECK(value IS NULL OR (typeof(value)='integer' AND value>=0)),
    window_start TEXT NOT NULL,
    window_end TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    evidence_json TEXT NOT NULL CHECK(json_valid(evidence_json)),
    stream_hash TEXT NOT NULL CHECK(length(stream_hash)=64),
    payload_hash TEXT NOT NULL CHECK(length(payload_hash)=64),
    supersedes_id INTEGER UNIQUE REFERENCES measurement_observations(measurement_observation_id) ON DELETE RESTRICT,
    created_at TEXT NOT NULL,
    CHECK((scope='post' AND post_record_id IS NOT NULL) OR (scope='account' AND post_record_id IS NULL)),
    CHECK((value_status='known' AND value IS NOT NULL) OR (value_status!='known' AND value IS NULL)),
    CHECK(provenance!='not_collected' OR value_status='not_collected'),
    CHECK(window_start<window_end AND window_end<=observed_at AND observed_at<=fetched_at)
);
CREATE INDEX ix_measurement_destination ON measurement_observations(social_destination_id,window_start,window_end);
CREATE INDEX ix_measurement_stream ON measurement_observations(stream_hash,observed_at,fetched_at);
CREATE TRIGGER measurement_no_update BEFORE UPDATE ON measurement_observations
BEGIN SELECT RAISE(ABORT,'measurement observations are immutable'); END;
CREATE TRIGGER measurement_no_delete BEFORE DELETE ON measurement_observations
BEGIN SELECT RAISE(ABORT,'measurement observations are immutable'); END;
CREATE TRIGGER measurement_correction BEFORE INSERT ON measurement_observations
WHEN NEW.supersedes_id IS NOT NULL AND NOT EXISTS (
    SELECT 1 FROM measurement_observations p WHERE p.measurement_observation_id=NEW.supersedes_id
    AND p.stream_hash=NEW.stream_hash AND p.observed_at<=NEW.observed_at AND p.fetched_at<=NEW.fetched_at
)
BEGIN SELECT RAISE(ABORT,'measurement correction must preserve stream and advance time'); END;
PRAGMA user_version = 20;
