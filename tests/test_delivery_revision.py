"""Real worker/store path with injected offline model responses; never an importer fixture."""
from datetime import timedelta
from hashlib import sha256
from pathlib import Path
from unittest.mock import patch
import json
import runpy
import sqlite3

import pytest
import test_gemini_workflow as text_fixtures
import test_gemini_image_renderer as image_fixtures
from database.current import initialize_database, connect, validate_database, SCHEMA_NAME, V18_CHECKSUM, SchemaError
from database.migrate_delivery import migrate, _legacy_sql
from detection.configuration import load_manifest
from detection.store import DetectionStore
from workflow import WorkflowStore, GeminiAdaptationWorker
from workflow.delivery import CredentialedPostingAgent
from workflow.delivery_fixtures import production_configuration
from workflow.delivery_revision import prepare, approve, command_row, command_fingerprint
from workflow.gemini_image_renderer import DispatchVisualRenderer
from workflow.offline import offline_only
from workflow.storyboard_planner import StoryboardPlanner
from workflow.store import canonical, now

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def no_network():
    with offline_only():
        yield


def legacy_db(path):
    with sqlite3.connect(path) as db:
        db.executescript(_legacy_sql())
        db.execute("INSERT INTO schema_migrations VALUES (1,18,?,?,?)", (SCHEMA_NAME, V18_CHECKSUM, now()))


@pytest.fixture(params=[False, True], ids=["fresh", "migrated"])
def source(tmp_path, request):
    return make_source(tmp_path, migrated=request.param)


def make_source(tmp_path, *, migrated=False, configuration=None, readiness=None, count=6):
    path = tmp_path / "operator.db"
    initialize_database(path)
    with DetectionStore(path) as detection:
        detection.apply_manifest(load_manifest(ROOT / "config/releases/detection.json"))
    artifacts = tmp_path / "artifacts"
    with WorkflowStore(path, catalog_kind="production") as store:
        store.register_production_configuration(configuration or production_configuration())
        if readiness:
            readiness(store)
        else:
            for row in store.connection.execute("SELECT social_destination_id FROM social_destinations"):
                store.record_destination_readiness(row[0], status="ready", reasons=[], facts={"offline_fixture": True},
                                                   valid_for=timedelta(days=1))
        review = render_source(store, artifacts, count=count)
    if migrated:
        # Preserve a real populated pre-revision database, not only an empty schema.
        legacy = tmp_path / "populated-v18.db"
        legacy_db(legacy)
        with connect(path) as current, sqlite3.connect(legacy) as old:
            triggers = old.execute("SELECT name,sql FROM sqlite_master WHERE type='trigger'").fetchall()
            for name, _ in triggers:
                old.execute(f"DROP TRIGGER {name}")
            tables = [r[0] for r in old.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' "
                "AND name!='schema_migrations'")]
            for table in tables:
                columns = ",".join(r[1] for r in old.execute(f"PRAGMA table_info({table})"))
                rows = current.execute(f"SELECT {columns} FROM {table}").fetchall()
                if rows:
                    placeholders = ",".join("?" for _ in rows[0])
                    old.executemany(f"INSERT INTO {table}({columns}) VALUES ({placeholders})", rows)
            for _, sql in triggers:
                old.execute(sql)
        with WorkflowStore(path) as store:
            before = original_evidence(store, review)
        assert migrate(legacy) == "dry_run_ok"
        assert migrate(legacy, apply=True, backup=tmp_path / "v18-backup.db") == "migrated"
        path = legacy
        with WorkflowStore(path) as store:
            assert original_evidence(store, review) == before
    return path, artifacts, review


def render_source(store, artifacts, *, count=6, command_id="production"):
    fixture = text_fixtures.GeminiWorkflowTests()
    fixture.register_catalog = lambda store: None  # use the frozen production binding above
    if count != 6:
        canonical = fixture.canonical_response("english")
        canonical["domain_payload"]["usage_notes"] = canonical["domain_payload"]["usage_notes"][:1]
        canonical["examples"] = canonical["examples"][:1] if count == 4 else canonical["examples"] * 2
        # Fixture responses enter through real generation/adaptation workers.
        fixture.canonical_response = lambda pipeline: canonical
    fixture.prepare_english_canonical(store, command_id=command_id)
    response = fixture.adaptation_response("instagram")
    from workflow.content_contract import english_positions
    response["visual_units"] = [response["visual_units"][i] for i in english_positions(count)]
    assert GeminiAdaptationWorker(store, text_fixtures.FakeGeminiClient(response)).run_once()
    assert StoryboardPlanner(store).run_once()
    worker = DispatchVisualRenderer(store, artifacts, image_client=image_fixtures.FakeImageClient())
    review = worker.run_once()
    assert review, getattr(worker, "last_operation", None)
    return review


def prepared(store, root, source, **extra):
    values = dict(account="brand", destination="instagram:brand", artifact_root=root,
                  output=root / "delivery", image_alt_text=[f"Slide {i}: complete lesson description" for i in range(1, 7)],
                  command_id="prepare-jpeg")
    values.update(extra)
    return prepare(store, source, **values)


def command(store, review):
    row = command_row(store, review)
    return dict(row_version=row["row_version"], fingerprint=command_fingerprint(row), account="brand",
                destination="instagram:brand")


def accept(store, review, **extra):
    values = command(store, review)
    values.update(reviewed_images=[a["sha256"] for a in json.loads(command_row(store, review)["manifest_json"])["assets"]],
                  command_id="approve-jpeg")
    values.update(extra)
    return approve(store, review, **values)


def original_evidence(store, source):
    tables = ["content_packages", "render_runs", "render_assets", "canonical_contents", "visual_recipes",
              "brief_revisions", "output_requests", "storyboard_plans", "model_invocations"]
    return {**{t: [tuple(r) for r in store.connection.execute(f"SELECT * FROM {t}")] for t in tables},
            "source_review": tuple(store.connection.execute("SELECT * FROM review_requests WHERE review_request_id=?", (source,)).fetchone())}


def test_real_worker_journey_retains_source_and_separates_approval_from_post_now(source):
    path, root, png = source
    with WorkflowStore(path) as store:
        store.approve_review(png, row_version=1, command_id="png-editorial-approval")
        before = original_evidence(store, png)
        jpeg = prepared(store, root, png)
        assert jpeg != png
        assert prepared(store, root, png) == jpeg
        row = command_row(store, jpeg)
        assert row["status"] == "awaiting_review" and row["actor_id"] is None
        with pytest.raises(ValueError):
            store.authorize_post_now(jpeg, command_id="too-soon", **command(store, jpeg))
        with pytest.raises(ValueError, match="exact delivery"):
            store.approve_review(jpeg, row_version=1, command_id="dashboard-cannot-approve")
        accept(store, jpeg)
        assert store.connection.execute("SELECT COUNT(*) FROM post_requests").fetchone()[0] == 0
        post_args = command(store, jpeg)
        post = store.authorize_post_now(jpeg, command_id="explicit-post", **post_args)
        assert original_evidence(store, png) == before
        assert store.connection.execute("SELECT status FROM post_records").fetchone()[0] == "pending"
    with WorkflowStore(path) as store:
        assert store.authorize_post_now(jpeg, command_id="explicit-post", **post_args) == post
        context = store._post_delivery_context(post, moment=now())
        assert context["package"]["caption"] == json.loads(before["content_packages"][0][4])["caption"]
        assert context["assets"][0]["alt_text"].startswith("Slide 1:")
        assert context["lineage"]["account"] == "brand"  # domain != account
        # Empty registry fails before staging/final-send; no fake adapter in operator composition.
        CredentialedPostingAgent(store).run_once()
        assert store.connection.execute("SELECT status FROM post_records").fetchone()[0] == "failed"
        assert store.connection.execute("SELECT final_publication_request_sent_at FROM post_attempts").fetchone()[0] is None
        assert store.connection.execute("SELECT COUNT(*) FROM publication_resources").fetchone()[0] == 0
        assert original_evidence(store, png) == before


@pytest.mark.parametrize("fault", ["fingerprint", "row_version", "account", "destination", "missing_ack", "reorder_ack", "empty_command"])
def test_approval_rejects_unauthorized_stale_or_incomplete_commands(source, fault):
    path, root, png = source
    with WorkflowStore(path) as store:
        jpeg = prepared(store, root, png)
        values = command(store, jpeg)
        hashes = [a["sha256"] for a in json.loads(command_row(store, jpeg)["manifest_json"])["assets"]]
        values.update(reviewed_images=hashes, command_id="approve")
        if fault in {"fingerprint", "account", "destination"}: values[fault] = "wrong"
        elif fault == "row_version": values[fault] = 99
        elif fault == "missing_ack": values["reviewed_images"] = hashes[:-1]
        elif fault == "reorder_ack": values["reviewed_images"] = hashes[::-1]
        else: values["command_id"] = ""
        with pytest.raises(ValueError): approve(store, jpeg, **values)
        assert command_row(store, jpeg)["status"] == "awaiting_review"
        assert not store.connection.execute("SELECT * FROM post_requests").fetchall()


@pytest.mark.parametrize("fault", ["jpeg", "missing", "outside", "readiness", "rejected", "expired", "source_hash", "source_rejected"])
@pytest.mark.parametrize("after_approval", [False, True])
def test_changed_evidence_and_revocation_fail_closed(source, fault, after_approval):
    path, root, png = source
    with WorkflowStore(path) as store:
        jpeg = prepared(store, root, png)
        if after_approval: accept(store, jpeg)
        asset = root / "delivery/slide-01.jpg"
        if fault == "jpeg": asset.write_bytes(b"changed")
        elif fault == "missing": asset.unlink()
        elif fault == "outside":
            outside = root.parent / "outside.jpg"
            outside.write_bytes(asset.read_bytes()); asset.unlink(); asset.symlink_to(outside)
        elif fault == "readiness": store.connection.execute("UPDATE capability_readiness SET status='blocked'")
        elif fault == "rejected": store.connection.execute("UPDATE review_requests SET status='rejected' WHERE review_request_id=?", (jpeg,))
        elif fault == "expired":
            # Time travel rather than altering immutable expiry.
            pass
        elif fault == "source_hash":
            store.connection.execute("UPDATE review_requests SET package_hash=? WHERE review_request_id=?", ("0"*64, png))
        else: store.connection.execute("UPDATE review_requests SET status='rejected' WHERE review_request_id=?", (png,))
        store.connection.commit()
        with patch("workflow.store.now", return_value="2099-01-01T00:00:00" if fault == "expired" else now()), \
                patch("workflow.delivery_revision.now", return_value="2099-01-01T00:00:00" if fault == "expired" else now()):
            with pytest.raises((ValueError, FileNotFoundError)):
                if after_approval: store.authorize_post_now(jpeg, command_id="post", **command(store, jpeg))
                else: accept(store, jpeg)
        assert not store.connection.execute("SELECT * FROM post_requests").fetchall()


def test_immutable_copy_provenance_order_and_independent_revision_duplicate(source):
    path, root, png = source
    with WorkflowStore(path) as store:
        jpeg = prepared(store, root, png)
        for field, value in [("package_json", '{"caption":"changed","alt_text":"changed"}'),
                             ("manifest_json", '{"assets":[]}'), ("lineage_json", '{}')]:
            with pytest.raises(sqlite3.IntegrityError, match="immutable"):
                store.connection.execute(f"UPDATE delivery_revisions SET {field}=?", (value,))
            store.connection.rollback()
        with pytest.raises(sqlite3.IntegrityError):
            store.connection.execute("UPDATE review_requests SET delivery_revision_id=NULL WHERE review_request_id=?", (jpeg,))
        store.connection.rollback()
        with pytest.raises(ValueError): prepared(store, root, jpeg, output=root / "forged", command_id="forged")
        with pytest.raises(ValueError): prepared(store, root, png, account="english", output=root / "wrong", command_id="wrong")
        with pytest.raises(ValueError): prepared(store, root, png, image_alt_text=["one"], command_id="partial")
        accept(store, jpeg)
        store.authorize_post_now(jpeg, command_id="first", **command(store, jpeg))
        second = prepared(store, root, png, output=root / "second", command_id="second")
        accept(store, second, command_id="approve-second")
        with pytest.raises(ValueError, match="already has"):
            store.authorize_post_now(second, command_id="duplicate", **command(store, second))
        assert store.connection.execute("SELECT COUNT(*) FROM post_requests").fetchone()[0] == 1


def test_report_is_read_only_self_contained_and_dashboard_cannot_approve(source, tmp_path):
    path, root, png = source
    with WorkflowStore(path) as store:
        jpeg = prepared(store, root, png)
        before = list(store.connection.iterdump())
    report = runpy.run_path(str(ROOT / "scripts/review_delivery.py"))["report"]
    with WorkflowStore(path, read_only=True) as store:
        evidence = report(store, jpeg, tmp_path / "review.html")
        assert before == list(store.connection.iterdump())
        assert evidence["is_ai_generated"] is True
        assert evidence["fingerprint"] == command_fingerprint(command_row(store, jpeg))
        from dashboard.workflow import _review_preview
        html = _review_preview(store.connection, jpeg, interactive=True, csrf_token="token")
        assert "<form" not in html and "JPEG delivery" in html
    html = (tmp_path / "review.html").read_text()
    assert "Required on the carousel parent" in html
    assert html.count("data:image/jpeg;base64,") == 6 and "default-src 'none'" in html


def test_migration_retains_rows_backup_ledger_and_atomic_failure(tmp_path, monkeypatch):
    import database.migrate_delivery as migration
    path = tmp_path / "legacy.db"
    legacy_db(path)
    with sqlite3.connect(path) as db:
        db.execute("INSERT INTO content_threads(origin,status,created_at,updated_at) VALUES ('human','open',?,?)", (now(),now()))
        before = list(db.iterdump())
    with pytest.raises(SchemaError): initialize_database(path)
    assert migrate(path) == "dry_run_ok"
    with sqlite3.connect(path) as db: assert before == list(db.iterdump())
    real_apply = migration._apply
    def failed(db):
        real_apply(db)
        raise RuntimeError("interrupted before commit")
    monkeypatch.setattr(migration, "_apply", failed)
    with pytest.raises(RuntimeError): migrate(path, apply=True, backup=tmp_path / "failed-backup.db")
    with sqlite3.connect(path) as db: assert before == list(db.iterdump())
    monkeypatch.setattr(migration, "_apply", real_apply)
    backup = tmp_path / "v18.db"
    assert migrate(path, apply=True, backup=backup) == "migrated"
    with sqlite3.connect(backup) as db: assert before == list(db.iterdump())
    with connect(path) as db:
        validate_database(db)
        assert db.execute("SELECT COUNT(*) FROM content_threads").fetchone()[0] == 1
        assert [r[0] for r in db.execute("SELECT version FROM schema_migrations ORDER BY version")] == [18,19]
    assert migrate(path, apply=True, backup=backup) == "already_current"
    assert initialize_database(path) is False
    # Restore means copy the verified pre-migration DB, then migrate that copy.
    restored = tmp_path / "restored.db"
    restored.write_bytes(backup.read_bytes())
    assert migrate(restored) == "dry_run_ok"


def test_migration_rejects_tampered_schema_and_existing_backup(tmp_path):
    path = tmp_path / "legacy.db"
    legacy_db(path)
    with pytest.raises(FileExistsError): migrate(path, apply=True, backup=path)
    with sqlite3.connect(path) as db: db.execute("DROP TRIGGER package_visual_lineage_immutable")
    with pytest.raises(SchemaError, match="executable schema"): migrate(path)


def test_cli_inspection_approval_and_post_now_are_separate_processes(source, tmp_path):
    import subprocess
    import sys
    path, root, png = source
    script = ROOT / "scripts/review_delivery.py"
    def cli(*args, success=True):
        result = subprocess.run([sys.executable, str(script), "--database", str(path), *map(str, args)],
                                capture_output=True, text=True)
        if success:
            assert result.returncode == 0, result.stderr
            return json.loads(result.stdout)["result"]
        assert result.returncode != 0
        return result.stderr
    alt = tmp_path / "alt.json"
    alt.write_text(json.dumps([f"Description {i} <script>not code</script>" for i in range(6)]))
    jpeg = cli("prepare", "--source-review-id", png, "--account", "brand", "--destination", "instagram:brand",
               "--artifacts", root, "--output", root / "cli-delivery", "--image-alt-text", alt,
               "--command-id", "cli-prepare")
    report = cli("report", "--review-id", jpeg, "--output", tmp_path / "first.html")
    assert "&lt;script&gt;" in (tmp_path / "first.html").read_text()
    def arguments(report):
        return ["--review-id", jpeg, "--account", "brand", "--destination", "instagram:brand",
                "--row-version", report["row_version"], "--fingerprint", report["fingerprint"]]
    assert "confirm-reviewed-all" in cli("approve", *arguments(report), "--reviewed-images",
                                          *report["reviewed_images"], "--command-id", "cli-approve", success=False)
    cli("approve", *arguments(report), "--reviewed-images", *report["reviewed_images"],
        "--confirm-reviewed-all", "--command-id", "cli-approve")
    # Exact approval replay is idempotent; it cannot become Post now implicitly.
    cli("approve", *arguments(report), "--reviewed-images", *report["reviewed_images"],
        "--confirm-reviewed-all", "--command-id", "cli-approve")
    with WorkflowStore(path) as store:
        assert not store.connection.execute("SELECT * FROM post_requests").fetchall()
        with store.transaction():
            store.connection.execute(
                "INSERT INTO storage_samples(state,free_bytes,total_bytes,database_bytes,wal_bytes,"
                "artifact_bytes,backup_bytes,summary_json,sampled_at) "
                "VALUES ('normal',100000000000,200000000000,1,0,0,0,'{}',?)", (now(),))
    cli("post-now", *arguments(report), "--command-id", "stale-post", success=False)
    after = cli("report", "--review-id", jpeg, "--output", tmp_path / "second.html")
    post = cli("post-now", *arguments(after), "--command-id", "cli-post")
    assert cli("post-now", *arguments(after), "--command-id", "cli-post") == post
    with WorkflowStore(path, read_only=True) as store:
        assert store.connection.execute("SELECT COUNT(*) FROM post_requests").fetchone()[0] == 1
        assert store.connection.execute("SELECT status FROM post_records").fetchone()[0] == "pending"
        assert not store.connection.execute("SELECT * FROM post_attempts").fetchall()


@pytest.mark.parametrize("fault", ["readiness", "bytes", "cancel", "claim", "review"])
def test_revision_final_marker_revalidates_without_calling_a_provider(source, fault):
    path, root, png = source
    with WorkflowStore(path) as store:
        jpeg = prepared(store, root, png)
        accept(store, jpeg)
        post = store.authorize_post_now(jpeg, command_id="post", **command(store, jpeg))
        claim = store.claim("post_records", "post_record_id", "test-owner")
        context = store.prepare_post_attempt(claim)
        store.mark_attempt_ready(context["post_attempt_id"])
        if fault == "bytes": (root / "delivery/slide-01.jpg").write_bytes(b"changed")
        elif fault == "readiness": store.connection.execute("UPDATE capability_readiness SET status='blocked'")
        elif fault == "review": store.connection.execute("UPDATE review_requests SET status='invalidated' WHERE review_request_id=?", (jpeg,))
        elif fault == "claim": store.connection.execute("UPDATE post_records SET claim_version=claim_version+1")
        else: store.connection.execute("UPDATE post_requests SET status='cancelled'")
        store.connection.commit()
        with pytest.raises(RuntimeError): store.mark_final_publication_request(context)
        assert store.connection.execute("SELECT final_publication_request_sent_at FROM post_attempts").fetchone()[0] is None


def test_unimplemented_revision_never_reaches_an_injected_transport(source):
    path, root, png = source
    with WorkflowStore(path) as store:
        jpeg = prepared(store, root, png)
        accept(store, jpeg)
        store.authorize_post_now(jpeg, command_id="post", **command(store, jpeg))
        class ForbiddenAdapter:
            def stage(self, *args):
                pytest.fail("an unimplemented production revision reached a transport")
            def publish(self, *args):
                pytest.fail("a production revision reached a fake publisher")
        CredentialedPostingAgent(store, adapters={"instagram": ForbiddenAdapter()}).run_once()
        assert store.connection.execute("SELECT failure_category FROM post_attempts").fetchone()[0] == "configuration"
        assert store.connection.execute("SELECT final_publication_request_sent_at FROM post_attempts").fetchone()[0] is None
        assert store.connection.execute("SELECT status FROM post_records").fetchone()[0] == "failed"


def test_legacy_revision_is_reportable_and_requires_new_disclosure_review(source):
    from scripts.review_delivery import report
    from workflow.delivery_revision import revision_fingerprint
    from workflow.store import digest

    path, root, png = source
    with WorkflowStore(path) as store:
        current = prepared(store, root, png)
        row = command_row(store, current)
        package = json.loads(row['package_json'])
        manifest = json.loads(row['manifest_json'])
        del package['is_ai_generated']
        manifest['content_hash'] = digest(package)
        # Insert the historic immutable format as a separate review cycle.
        fingerprint = revision_fingerprint(package, manifest, json.loads(row['lineage_json']), root)
        with store.transaction():
            legacy_revision = store.connection.execute(
                "INSERT INTO delivery_revisions(source_review_request_id,package_json,package_hash,manifest_json,"
                "manifest_hash,lineage_json,artifact_root,fingerprint,created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (png, canonical(package), digest(package), canonical(manifest), digest(manifest),
                 row['lineage_json'], str(root), fingerprint, now())).lastrowid
            legacy = store.connection.execute(
                "INSERT INTO review_requests(content_package_id,render_run_id,review_cycle_number,package_hash,"
                "manifest_hash,status,expires_at,created_at,destination_key,delivery_revision_id) "
                "VALUES (?,?,?,?,?,'awaiting_review',?,?,?,?)",
                (row['content_package_id'], row['render_run_id'], row['review_cycle_number'] + 1,
                 digest(package), digest(manifest), row['expires_at'], now(), row['destination_key'],
                 legacy_revision)).lastrowid
        assert report(store, legacy, root / 'legacy.html')['is_ai_generated'] is None
        with pytest.raises(ValueError, match='new JPEG review'):
            accept(store, legacy)
        assert command_row(store, legacy)['status'] == 'awaiting_review'
        assert fingerprint != row['fingerprint']
