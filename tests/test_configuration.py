"""Configuration; offline tests use temporary databases and fake providers."""

from common.environment import EnvironmentFileError, load_environment_file
from copy import deepcopy
from database.current import SchemaError, connect, initialize_database, validate_database
from datetime import datetime, timezone
from detection.configuration import ConfigurationError, load_manifest, validate_manifest
from detection.store import DetectionStore
from pathlib import Path
from unittest.mock import MagicMock, patch
from workflow import WorkflowStore
from workflow.development import prepare_development_database
import importlib
import json
import os
import runpy
import sqlite3
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class DatabaseAndEntrypointTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "fixture.db"
        initialize_database(self.path)
        with DetectionStore(self.path) as store:
            store.apply_manifest(load_manifest(ROOT / "config/releases/detection.json"))

        self.start = datetime(2026, 9, 8, 12, tzinfo=timezone.utc)

    def test_read_only_connection_encodes_hash_and_unicode_in_paths(self):
        directory = Path(self.temporary.name) / "fixture # 한글 %"
        path = directory / "development.db"
        initialize_database(path)
        connection = connect(path, read_only=True)
        try:
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 17)
            with self.assertRaises(sqlite3.OperationalError):
                connection.execute("CREATE TABLE forbidden(id INTEGER)")
        finally:
            connection.close()

    def test_failed_store_validation_closes_its_connection(self):
        for module_name, class_name, validator in (
            ("detection.store", "DetectionStore", "validate_database"),
            ("workflow.store", "WorkflowStore", "validate_database"),
        ):
            with self.subTest(module=module_name):
                module = importlib.import_module(module_name)
                connection = MagicMock()
                with patch.object(module, "connect", return_value=connection), patch.object(
                    module, validator, side_effect=SchemaError("synthetic invalid schema")
                ):
                    with self.assertRaises(SchemaError):
                        getattr(module, class_name)(self.path)
                connection.close.assert_called_once_with()

    def test_utility_imports_do_not_open_databases_or_load_environment(self):
        with patch("database.current.connect") as connection, patch("common.environment.load_environment_file") as environment:
            for name in ("serve_dashboard.py", "run_detection.py", "run_workflow.py", "run_storage_monitor.py", "run_maintenance.py", "install_review_baseline.py", "create_local_idea.py", "setup_development.py", "check_smoke_readiness.py"):
                runpy.run_path(str(ROOT / "scripts" / name), run_name="import_check")
            connection.assert_not_called()
            environment.assert_not_called()

    def test_entrypoints_load_environment_before_resolving_settings(self):
        import os
        for name, arguments in (
            ("create_local_idea.py", ["A local fixture idea"]),
            ("run_workflow.py", []),
        ):
            with self.subTest(script=name), patch.dict(os.environ, {}, clear=True):
                module = runpy.run_path(str(ROOT / "scripts" / name), run_name="import_check")
                worker_store = MagicMock()
                def load(_path):
                    os.environ["CONTENT_FACTORY_ARTIFACT_ROOT"] = str(Path(self.temporary.name) / "configured")
                def resolve(_parser, _directory, _override=None):
                    self.assertEqual(os.environ["CONTENT_FACTORY_ARTIFACT_ROOT"], str(Path(self.temporary.name) / "configured"))
                    return self.path
                with patch.dict(module["main"].__globals__, {
                    "load_environment_file": load, "WorkflowStore": worker_store,
                    "resolve_primary_database_argument": resolve,
                }), patch("sys.argv", [name, *arguments]), patch("builtins.print"):
                    if name == "run_workflow.py":
                        factories = {key: MagicMock() for key in (
                            "IdeaIntakeWorker", "DeterminationWorker", "EditorialPlanningWorker", "GeminiPipelineRunner",
                            "GeminiAdaptationWorker", "VisualPlanner", "StoryboardPlanner", "DispatchVisualRenderer", "StorageMonitor",
                        )}
                        with patch.dict(module["main"].__globals__, factories):
                            module["main"]()
                        self.assertEqual(factories["StorageMonitor"].call_args.args[1], os.environ["CONTENT_FACTORY_ARTIFACT_ROOT"])
                        factories["DispatchVisualRenderer"].assert_not_called()
                    else:
                        module["main"]()
                self.assertEqual(Path(worker_store.call_args.args[0]).resolve(), self.path.resolve())

    def test_review_baseline_plists_have_one_shared_runtime_and_safe_roles(self):
        module = runpy.run_path(str(ROOT / "scripts" / "install_review_baseline.py"))
        root = Path(self.temporary.name)
        agents = module["build_agents"](
            artifacts=root / "artifacts",
            backups=root / "backups",
            log_root=root / "logs",
            port=8788,
            backup_hour=3,
            backup_minute=15,
        )
        self.assertEqual(set(agents), {"detection", "workflow", "dashboard", "storage", "backup"})
        self.assertTrue(all("--database" not in agent["ProgramArguments"] for agent in agents.values()))
        self.assertTrue(all(agent["WorkingDirectory"] == str(ROOT) for agent in agents.values()))
        self.assertTrue(all(agent["EnvironmentVariables"]["CONTENT_FACTORY_LOG_ROOT"] == str(root / "logs") for agent in agents.values()))
        self.assertTrue(all(str(ROOT / "src") in agent["EnvironmentVariables"]["PYTHONPATH"] for agent in agents.values()))
        self.assertTrue(all("site-packages" in agent["EnvironmentVariables"]["PYTHONPATH"] for agent in agents.values()))
        self.assertTrue(all(agents[name]["KeepAlive"] for name in ("detection", "workflow", "dashboard", "storage")))
        self.assertNotIn("KeepAlive", agents["backup"])
        self.assertEqual(agents["backup"]["StartCalendarInterval"], {"Hour": 3, "Minute": 15})
        workflow = agents["workflow"]["ProgramArguments"]
        self.assertEqual(workflow[0], str(Path(sys.executable).absolute()))
        self.assertIn("--gemini", workflow)
        self.assertIn("--review-preview", workflow)
        self.assertNotIn("--planning-only", workflow)
        dashboard = agents["dashboard"]["ProgramArguments"]
        self.assertEqual(dashboard[dashboard.index("--host") + 1], "127.0.0.1")

    def test_review_baseline_write_is_atomic_and_serializes_launchd_plists(self):
        module = runpy.run_path(str(ROOT / "scripts" / "install_review_baseline.py"))
        destination = Path(self.temporary.name) / "LaunchAgents"
        agents = module["build_agents"](
            artifacts=Path(self.temporary.name) / "artifacts",
            backups=Path(self.temporary.name) / "backups",
            log_root=Path(self.temporary.name) / "logs",
            port=8787,
            backup_hour=3,
            backup_minute=15,
        )
        paths = module["write_agents"](agents, destination)
        self.assertEqual(len(paths), 5)
        self.assertFalse(list(destination.glob("*.tmp")))
        with (destination / "com.contentfactory.review.workflow.plist").open("rb") as source:
            payload = __import__("plistlib").load(source)
        self.assertEqual(payload["Label"], "com.contentfactory.review.workflow")
        self.assertTrue(payload["KeepAlive"])

    def test_review_baseline_stop_targets_only_owned_agents_and_is_idempotent(self):
        module = runpy.run_path(str(ROOT / "scripts" / "install_review_baseline.py"))
        destination = Path(self.temporary.name) / "LaunchAgents"
        destination.mkdir()
        for path in module["baseline_paths"](destination):
            path.touch()
        with patch.object(module["subprocess"], "run") as run:
            module["stop_agents"](destination)
            module["stop_agents"](destination)
        self.assertEqual(run.call_count, 10)
        commands = [call.args[0] for call in run.call_args_list]
        expected = {str(path) for path in module["baseline_paths"](destination)}
        self.assertEqual({command[-1] for command in commands}, expected)
        self.assertTrue(all(command[:3] == ["launchctl", "bootout", module["_domain"]()] for command in commands))

    def test_review_baseline_uninstall_stops_and_removes_only_owned_plists(self):
        module = runpy.run_path(str(ROOT / "scripts" / "install_review_baseline.py"))
        destination = Path(self.temporary.name) / "LaunchAgents"
        destination.mkdir()
        owned = module["baseline_paths"](destination)
        for path in owned:
            path.touch()
        unrelated = destination / "com.example.unrelated.plist"
        unrelated.touch()
        with patch.object(module["subprocess"], "run") as run:
            module["uninstall_agents"](destination)
            module["uninstall_agents"](destination)
        self.assertEqual(run.call_count, 10)
        self.assertFalse(any(path.exists() for path in owned))
        self.assertTrue(unrelated.exists())


class DatabaseInitializationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "fixture.db"
        initialize_database(self.path)
        self.manifest = load_manifest(ROOT / "config/releases/detection.json")
        with DetectionStore(self.path) as store:
            store.apply_manifest(self.manifest)

    def test_setup_cli_does_not_ask_for_a_database_name(self):
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts/setup_development.py"), "--help"],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("--database", result.stdout)

    def test_primary_database_selection_uses_newest_timestamp_not_mtime(self):
        from database.paths import latest_primary_database_path
        directory = Path(self.temporary.name) / "primary"
        directory.mkdir()
        older = directory / "db_20260924010203.db"
        newer = directory / "db_20260925010203.db"
        ignored = directory / "db_20260926010203.sqlite"
        for path in (older, newer, ignored):
            path.touch()
        older.touch()
        self.assertEqual(latest_primary_database_path(directory), newer.resolve())

    def test_http_snapshot_validation_does_not_scan_foreign_keys(self):
        with DetectionStore(self.path, read_only=True) as store:
            statements = []
            store.connection.set_trace_callback(statements.append)
            validate_database(store.connection, check_foreign_keys=False)
            self.assertFalse(any("foreign_key_check" in sql for sql in statements))
            validate_database(store.connection)
            self.assertTrue(any("foreign_key_check" in sql for sql in statements))


class CatalogAndManifestTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "fixture.db"
        self.manifest = load_manifest(ROOT / "config/releases/detection.json")
        initialize_database(self.path)
        with DetectionStore(self.path) as store:
            store.apply_manifest(self.manifest)

    def route(self, store):
        return store.register_capability("english", enabled=True, generation_ready=True, outputs=[{
            "platform": "instagram", "account": "fixture", "content_format": "placeholder", "ready": True,
        }])

    def test_fixture_registration_is_idempotent_and_catalog_is_release_scoped(self):
        with WorkflowStore(self.path) as store:
            first = self.route(store)
            self.assertEqual(self.route(store), first)
            with self.assertRaisesRegex(ValueError, "different input"):
                store.register_capability("english", enabled=False, generation_ready=False, outputs=[])
            with DetectionStore(self.path) as detection:
                newer = deepcopy(self.manifest)
                newer["release_name"] = "new-fixture-release"
                detection.apply_manifest(newer)
            self.assertEqual(store.catalog(), [])

    def test_numeric_booleans_and_obsolete_cluster_configuration_are_rejected(self):
        for key in ("trust_weight", "quota_limit"):
            value = deepcopy(self.manifest)
            value["components"]["detection"]["sources"][0][key] = True
            with self.assertRaises(ConfigurationError):
                validate_manifest(value)
        value = deepcopy(self.manifest)
        value["schema_version"] = True
        with self.assertRaises(ConfigurationError):
            validate_manifest(value)
        value = deepcopy(self.manifest)
        value["components"]["detection"]["cluster_aliases"] = []
        with self.assertRaises(ConfigurationError):
            validate_manifest(value)


class ActiveRuntimeTests(unittest.TestCase):
    def test_workflow_registry_and_public_api_exclude_inactive_workers(self):
        import workflow
        runtime = runpy.run_path(str(ROOT / "scripts/run_workflow.py"))
        self.assertEqual(set(runtime["_RUNTIME_TYPES"]), {
            "IdeaIntakeWorker", "GeminiIntakeWorker", "DeterminationWorker",
            "GeminiDeterminationWorker", "EditorialPlanningWorker", "GeminiEditorialPlanningWorker", "GeminiPipelineRunner", "GeminiAdaptationWorker",
            "VisualPlanner", "StoryboardPlanner", "DispatchVisualRenderer", "StorageMonitor",
        })
        for name in ("StaticVisualRenderer", "CredentialedPostingAgent", "R2TransientRelay", "PublicationReconciliationWorker", "VisualRenderer", "PostingAgent"):
            self.assertNotIn(name, workflow.__all__)
            self.assertFalse(hasattr(workflow, name))

    def test_setup_generates_timestamped_databases_without_overwriting_existing_files(self):
        main = runpy.run_path(str(ROOT / "scripts/setup_development.py"))["main"]
        with tempfile.TemporaryDirectory() as directory:
            data_directory = Path(directory) / "data"
            with patch.dict(main.__globals__, {"DATA_DIRECTORY": data_directory, "load_environment_file": lambda path: None}), patch("sys.argv", ["setup_development.py"]):
                main()
                first = next(data_directory.glob("db_*.db"))
                self.assertRegex(first.name, r"^db_\d{14}\.db$")
                before = first.read_bytes()
                main()
                self.assertEqual(first.read_bytes(), before)
                self.assertEqual(len(list(data_directory.glob("db_*.db"))), 2)


MANIFEST = ROOT / "config" / "releases" / "detection.json"

class SchemaAndEnvironmentTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.database_path = Path(self.directory.name) / "development.db"
        initialize_database(self.database_path)
        with DetectionStore(self.database_path) as store:
            store.apply_manifest(load_manifest(MANIFEST))

    def test_initialization_is_idempotent_and_dashboard_connection_is_read_only(self):
        self.assertFalse(initialize_database(self.database_path))
        connection = connect(self.database_path, read_only=True)
        try:
            validate_database(connection)
            with self.assertRaises(Exception):
                connection.execute("CREATE TABLE forbidden(id INTEGER)")
        finally:
            connection.close()

    def test_worker_startup_does_not_create_an_absent_database(self):
        missing = Path(self.directory.name) / "missing.db"
        with self.assertRaises(SchemaError):
            DetectionStore(missing)
        self.assertFalse(missing.exists())

    def test_local_environment_loader_never_overrides_process_values(self):
        environment_file = Path(self.directory.name) / ".env"
        environment_file.write_text(
            "CONTENT_FACTORY_TEST_EXISTING=file-value\n"
            "CONTENT_FACTORY_TEST_NEW='loaded value'\n",
            encoding="utf-8",
        )
        with patch.dict(
            os.environ, {"CONTENT_FACTORY_TEST_EXISTING": "process-value"}, clear=False
        ):
            os.environ.pop("CONTENT_FACTORY_TEST_NEW", None)
            self.assertTrue(load_environment_file(environment_file))
            self.assertEqual(os.environ["CONTENT_FACTORY_TEST_EXISTING"], "process-value")
            self.assertEqual(os.environ["CONTENT_FACTORY_TEST_NEW"], "loaded value")
            os.environ.pop("CONTENT_FACTORY_TEST_NEW", None)

    def test_local_environment_loader_rejects_malformed_lines_without_values(self):
        environment_file = Path(self.directory.name) / ".env"
        environment_file.write_text("not-an-assignment", encoding="utf-8")
        with self.assertRaises(EnvironmentFileError) as raised:
            load_environment_file(environment_file)
        self.assertNotIn("not-an-assignment", str(raised.exception))

    def test_schema_checksum_mismatch_is_rejected(self):
        connection = connect(self.database_path)
        try:
            connection.execute(
                "UPDATE schema_migrations SET checksum=? WHERE version=17", ("0" * 64,)
            )
            connection.commit()
            with self.assertRaises(SchemaError):
                validate_database(connection)
        finally:
            connection.close()


DOMAINS = ('english', 'ai_tech', 'psychology')

class DevelopmentCatalogTests(unittest.TestCase):
    def test_exact_catalog_and_no_incidental_database_upgrade(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = prepare_development_database(Path(tmp)/'baseline.db')
            with WorkflowStore(path) as store:
                catalog = store.catalog()
                self.assertEqual(tuple(c['pipeline_id'] for c in catalog), DOMAINS)
                self.assertEqual([[(o['platform'], o['account']) for o in c['outputs']] for c in catalog],
                                 [[('instagram', f'fixture_{domain}')] for domain in DOMAINS])
                with self.assertRaises(ValueError):
                    store.register_capability('english', enabled=True, generation_ready=True,
                                              outputs=[{'platform': 'x', 'account': 'fixture', 'content_format': 'removed'}])
            with connect(path) as connection:
                connection.execute('PRAGMA user_version=8')
            before = path.read_bytes()
            with self.assertRaises(SchemaError):
                initialize_database(path)
            self.assertEqual(path.read_bytes(), before)
