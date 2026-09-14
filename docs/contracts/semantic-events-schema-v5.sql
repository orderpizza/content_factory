CREATE TABLE scout_event_resolutions (
    scout_event_resolution_id INTEGER PRIMARY KEY AUTOINCREMENT,
    scout_evaluation_run_id INTEGER NOT NULL UNIQUE REFERENCES scout_evaluation_runs(scout_evaluation_run_id) ON DELETE RESTRICT,
    source_snapshot_hash TEXT NOT NULL CHECK(length(source_snapshot_hash)=64),
    resolution_json TEXT NOT NULL CHECK(json_valid(resolution_json)),
    resolution_hash TEXT NOT NULL CHECK(length(resolution_hash)=64),
    created_at TEXT NOT NULL
);
CREATE TRIGGER scout_event_resolutions_immutable BEFORE UPDATE ON scout_event_resolutions
BEGIN SELECT RAISE(ABORT, 'event resolution is immutable'); END;
CREATE TRIGGER scout_event_resolutions_no_delete BEFORE DELETE ON scout_event_resolutions
BEGIN SELECT RAISE(ABORT, 'event resolution is immutable'); END;
PRAGMA user_version = 5;
