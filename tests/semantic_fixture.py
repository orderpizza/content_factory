"""Explicit schema preparation for offline DetectionScout integration fixtures."""

from database.migrations import migrate_production_workflow, migrate_semantic_events


def upgrade_semantic_fixture(path):
    migrate_production_workflow(path)
    migrate_semantic_events(path)
