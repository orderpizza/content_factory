-- Forward-only extension; v1 and v2 checksums remain unchanged.
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
CREATE TRIGGER scout_prominence_populations_immutable BEFORE UPDATE ON scout_prominence_populations
BEGIN SELECT RAISE(ABORT, 'Scout prominence population is immutable'); END;
CREATE TRIGGER scout_frozen_evidence_immutable BEFORE UPDATE ON scout_frozen_evidence
BEGIN SELECT RAISE(ABORT, 'frozen Scout evidence is immutable'); END;
CREATE TRIGGER source_execution_evidence_immutable BEFORE UPDATE ON source_execution_evidence
BEGIN SELECT RAISE(ABORT, 'source execution evidence is immutable'); END;
CREATE TRIGGER observations_immutable BEFORE UPDATE ON trend_observations
BEGIN SELECT RAISE(ABORT, 'completed observation evidence is immutable'); END;
PRAGMA user_version = 3;
