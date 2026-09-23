"""Production visual approval and binding contracts; legacy data is rejected explicitly."""
from copy import deepcopy
from datetime import timedelta
import json
from pathlib import Path
import unittest

from database.current import connect, initialize_database, SchemaError
import delivery_fixtures
from workflow import WorkflowStore
from workflow.store import now

ROOT = Path(__file__).resolve().parents[1]

# Rejection fixtures only: these identifiers must never enter runtime configuration.
LEGACY_RENDERER_PROFILE = {
    'profile_version': 'static_social_delivery_profiles_v1',
    'template_version': 'static_social_template_v1',
    'font_path': '/fixture/font.ttf', 'font_sha256': 'f' * 64,
}
LEGACY_COMPATIBILITY = 'html_playwright_v1'


class VisualConfigurationTests(delivery_fixtures.DeliveryFixture, unittest.TestCase):
    def ready_provider(self, store):
        for row in store.connection.execute('SELECT social_destination_id FROM social_destinations'):
            store.record_destination_readiness(row[0], status='ready', reasons=[],
                facts={'fixture': True}, valid_for=timedelta(days=1))

    def test_binding_schema_and_fixture_catalog_have_only_routing_fields(self):
        with WorkflowStore(self.path) as store:
            columns = {r['name'] for r in store.connection.execute('PRAGMA table_info(output_bindings)')}
            self.assertNotIn('renderer_compatibility', columns)
            self.assertNotIn('profile_approved', columns)
            self.assertIn('visual_configuration_approved', columns)
            output = {'platform': 'instagram', 'account': 'fixture_english',
                      'content_format': 'instagram_static_carousel_v2', 'ready': True}
            id = store.register_capability('english', enabled=True, generation_ready=True, outputs=[output])
            self.assertEqual(id, store.register_capability('english', enabled=True, generation_ready=True, outputs=[output]))
            catalog = store.catalog()
            self.assertEqual(len(catalog), 1)
            self.assertEqual(set(catalog[0]['outputs'][0]), {'output_binding_id', 'platform', 'account',
                'content_format', 'output_contract_version', 'ready', 'safe_reason'})
            self.assertTrue(catalog[0]['outputs'][0]['ready'])
            self.assertEqual(catalog[0]['pipeline_id'], 'english')
            self.assertTrue(catalog[0]['remit'])
            # Retired binding metadata is rejected, not silently defaulted or ignored.
            with self.assertRaisesRegex(ValueError, 'unsupported fields'):
                store.register_capability('english', enabled=True, generation_ready=True,
                    outputs=[{**output, 'renderer_compatibility': LEGACY_COMPATIBILITY}])

    def test_production_v2_is_closed_immutable_and_needs_no_unused_font_metadata(self):
        config = self.configuration()
        self.assertEqual(set(config), {'policy_version', 'approved_by', 'approved_at',
            'visual_configuration_approved', 'destinations', 'bindings'})
        self.assertEqual(config['policy_version'], 'production_configuration_v2')
        with WorkflowStore(self.path, catalog_kind='production') as store:
            id = store.register_production_configuration(config)
            self.assertEqual(id, store.register_production_configuration(config))
            row = store.connection.execute('SELECT configuration_json FROM production_configurations').fetchone()
            self.assertEqual(json.loads(row[0]), config)
            self.assertEqual([r[0] for r in store.connection.execute('SELECT visual_configuration_approved FROM output_bindings')], [1, 1, 1])
            with self.assertRaisesRegex(ValueError, 'different immutable'):
                store.register_production_configuration({**config, 'visual_configuration_approved': False})

    def test_legacy_production_renderer_configuration_is_rejected(self):
        config = self.configuration()
        old = deepcopy(config)
        old['policy_version'] = 'production_configuration_v1'
        old['profile_approved'] = old.pop('visual_configuration_approved')
        old['renderer_profile'] = LEGACY_RENDERER_PROFILE
        invalid = [old, {**config, 'renderer_profile': LEGACY_RENDERER_PROFILE},
                   {**config, 'policy_version': 'production_configuration_v1'},
                   {**config, 'profile_approved': True},
                   {**config, 'visual_configuration_approved': 1}]
        with WorkflowStore(self.path, catalog_kind='production') as store:
            for value in invalid:
                with self.subTest(keys=list(value)), self.assertRaises(ValueError):
                    store.register_production_configuration(value)
            self.assertEqual(store.connection.execute('SELECT COUNT(*) FROM production_configurations').fetchone()[0], 0)
            self.assertEqual(store.connection.execute('SELECT COUNT(*) FROM output_bindings').fetchone()[0], 0)

    def test_visual_approval_is_distinct_from_provider_readiness_and_post_review(self):
        with WorkflowStore(self.path, catalog_kind='production') as store:
            store.register_production_configuration({**self.configuration(), 'visual_configuration_approved': False})
            self.ready_provider(store)
            outputs = [o for c in store.catalog() for o in c['outputs']]
            self.assertEqual(len(outputs), 3)
            self.assertTrue(all(not o['ready'] for o in outputs))
            self.assertTrue(all('visual configuration approval' in o['safe_reason'] for o in outputs))
            review_id = self.create_review(store)
            with self.assertRaisesRegex(ValueError, 'visual configuration is not approved'):
                store.authorize_post_now(review_id, row_version=1, command_id='unapproved-visuals')
            self.assertEqual(store.connection.execute('SELECT COUNT(*) FROM post_requests').fetchone()[0], 0)

    def test_delivery_preparation_and_final_send_keep_visual_approval_gate(self):
        with WorkflowStore(self.path, catalog_kind='production') as store:
            self.configure(store, min_post_interval_minutes=0)
            review_id = self.create_review(store)
            record_id = store.authorize_post_now(review_id, row_version=1, command_id='approved-visuals')
            with store.transaction():
                store.connection.execute('UPDATE output_bindings SET visual_configuration_approved=0')
            with self.assertRaisesRegex(ValueError, 'visual configuration is not approved'):
                store._post_delivery_context(record_id, moment=now())
            with store.transaction():
                store.connection.execute('UPDATE output_bindings SET visual_configuration_approved=1')
            run = store.claim('post_records', 'post_record_id', 'test-visual-approval')
            context = store.prepare_post_attempt(run)
            store.mark_attempt_ready(context['post_attempt_id'])
            with store.transaction():
                store.connection.execute('UPDATE output_bindings SET visual_configuration_approved=0')
            with self.assertRaisesRegex(RuntimeError, 'readiness expired'):
                store.mark_final_publication_request(context)
            self.assertIsNone(store.connection.execute('SELECT final_publication_request_sent_at FROM post_attempts').fetchone()[0])

    def test_schema_ten_database_is_refused_without_migration(self):
        with connect(self.path) as connection:
            connection.execute('PRAGMA user_version=10')
            connection.commit()
            before = [tuple(r) for r in connection.execute('SELECT * FROM schema_migrations')]
        with self.assertRaises(SchemaError):
            initialize_database(self.path)
        with self.assertRaises(SchemaError):
            WorkflowStore(self.path)
        with connect(self.path) as connection:
            self.assertEqual(connection.execute('PRAGMA user_version').fetchone()[0], 10)
            self.assertEqual([tuple(r) for r in connection.execute('SELECT * FROM schema_migrations')], before)

    def test_rejected_legacy_renderer_identifiers_are_absent_from_runtime_sources(self):
        retired = (LEGACY_COMPATIBILITY, LEGACY_RENDERER_PROFILE['profile_version'],
                   LEGACY_RENDERER_PROFILE['template_version'])
        for directory in ('src', 'scripts', 'config', 'docs'):
            for path in (ROOT / directory).rglob('*'):
                if not path.is_file() or path.suffix not in {'.py', '.sql', '.json', '.md'}:
                    continue
                content = path.read_text()
                for token in retired:
                    self.assertNotIn(token, content, f'{path.relative_to(ROOT)} contains rejected renderer identifier')
