-- Phase 3B1: append-only delivery revisions; source package/render IDs remain lineage.
CREATE TABLE delivery_revisions (
    delivery_revision_id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_review_request_id INTEGER NOT NULL REFERENCES review_requests(review_request_id) ON DELETE RESTRICT,
    package_json TEXT NOT NULL CHECK(json_valid(package_json)),
    package_hash TEXT NOT NULL CHECK(length(package_hash)=64),
    manifest_json TEXT NOT NULL CHECK(json_valid(manifest_json)),
    manifest_hash TEXT NOT NULL CHECK(length(manifest_hash)=64),
    lineage_json TEXT NOT NULL CHECK(json_valid(lineage_json)),
    artifact_root TEXT NOT NULL,
    fingerprint TEXT NOT NULL UNIQUE CHECK(length(fingerprint)=64),
    created_at TEXT NOT NULL
);
ALTER TABLE review_requests ADD COLUMN delivery_revision_id INTEGER
    REFERENCES delivery_revisions(delivery_revision_id) ON DELETE RESTRICT;
CREATE UNIQUE INDEX uq_delivery_revision_review ON review_requests(delivery_revision_id)
    WHERE delivery_revision_id IS NOT NULL;
CREATE TRIGGER delivery_revision_immutable_update BEFORE UPDATE ON delivery_revisions
BEGIN SELECT RAISE(ABORT,'delivery revision is immutable'); END;
CREATE TRIGGER delivery_revision_immutable_delete BEFORE DELETE ON delivery_revisions
BEGIN SELECT RAISE(ABORT,'delivery revision is immutable'); END;
CREATE TRIGGER delivery_revision_source_guard BEFORE INSERT ON delivery_revisions
WHEN NOT EXISTS (SELECT 1 FROM review_requests WHERE review_request_id=NEW.source_review_request_id
    AND delivery_revision_id IS NULL)
BEGIN SELECT RAISE(ABORT,'delivery revision requires an original source review'); END;
CREATE TRIGGER delivery_review_lineage_guard BEFORE INSERT ON review_requests
WHEN NEW.delivery_revision_id IS NOT NULL AND NOT EXISTS (
    SELECT 1 FROM delivery_revisions d JOIN review_requests s
    ON s.review_request_id=d.source_review_request_id
    WHERE d.delivery_revision_id=NEW.delivery_revision_id
    AND s.content_package_id=NEW.content_package_id AND s.render_run_id=NEW.render_run_id
    AND s.destination_key=NEW.destination_key AND d.package_hash=NEW.package_hash
    AND d.manifest_hash=NEW.manifest_hash AND NEW.status='awaiting_review'
    AND NEW.actor_id IS NULL AND NEW.decided_at IS NULL)
BEGIN SELECT RAISE(ABORT,'delivery review must start unapproved with exact lineage'); END;
CREATE TRIGGER delivery_review_immutable BEFORE UPDATE OF delivery_revision_id,content_package_id,
    render_run_id,package_hash,manifest_hash,destination_key,expires_at,review_cycle_number ON review_requests
WHEN OLD.delivery_revision_id IS NOT NULL OR NEW.delivery_revision_id IS NOT NULL
BEGIN SELECT RAISE(ABORT,'delivery review binding is immutable'); END;
CREATE TRIGGER delivery_review_no_delete BEFORE DELETE ON review_requests
WHEN OLD.delivery_revision_id IS NOT NULL
BEGIN SELECT RAISE(ABORT,'delivery review evidence is immutable'); END;
CREATE TRIGGER delivery_post_guard BEFORE INSERT ON post_requests
WHEN EXISTS (SELECT 1 FROM review_requests WHERE review_request_id=NEW.review_request_id
    AND delivery_revision_id IS NOT NULL) AND NOT EXISTS (
    SELECT 1 FROM review_requests v WHERE v.review_request_id=NEW.review_request_id
    AND v.status='approved' AND v.actor_id='local_owner'
    AND v.content_package_id=NEW.content_package_id AND v.render_run_id=NEW.render_run_id
    AND v.package_hash=NEW.package_hash AND v.manifest_hash=NEW.manifest_hash
    AND v.destination_key=NEW.destination_key)
BEGIN SELECT RAISE(ABORT,'delivery Post now requires a separately approved exact review'); END;
CREATE TRIGGER delivery_post_immutable BEFORE UPDATE OF review_request_id,content_package_id,
    render_run_id,package_hash,manifest_hash,destination_key,publication_identity ON post_requests
WHEN EXISTS (SELECT 1 FROM review_requests WHERE review_request_id=OLD.review_request_id
    AND delivery_revision_id IS NOT NULL)
BEGIN SELECT RAISE(ABORT,'delivery authorization binding is immutable'); END;
PRAGMA user_version = 19;
