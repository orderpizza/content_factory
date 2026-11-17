"""Delivery fixtures; offline tests use temporary databases and fake providers."""

from __future__ import annotations
from database.current import initialize_database
from datetime import timedelta
from detection.configuration import load_manifest
from detection.store import DetectionStore
from pathlib import Path
from workflow.delivery_fixtures import production_configuration, seed_review
import tempfile


ROOT = Path(__file__).resolve().parents[1]


MANIFEST = ROOT / "config" / "releases" / "detection.json"


class DeliveryFixture:
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "development.db"
        initialize_database(self.path)
        with DetectionStore(self.path) as store:
            store.apply_manifest(load_manifest(MANIFEST))

    def configuration(self, **kwargs):
        return production_configuration(**kwargs)

    def configure(self, store, *, platforms=("instagram",), max_posts_per_day=1,
                  min_post_interval_minutes=1200):
        store.register_production_configuration(self.configuration(
            platforms=platforms, max_posts_per_day=max_posts_per_day,
            min_post_interval_minutes=min_post_interval_minutes,
        ))
        for row in store.connection.execute("SELECT social_destination_id FROM social_destinations"):
            store.record_destination_readiness(
                row[0], status="ready", reasons=[], facts={"fixture": True},
                valid_for=timedelta(days=1),
            )

    def create_review(self, store, platform="instagram", *, stop_at_adaptation=False):
        return seed_review(store, self.temporary.name, platform,
                           stop_at_adaptation=stop_at_adaptation)
