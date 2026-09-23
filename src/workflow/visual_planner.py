"""Deterministic canonical-to-archetype handoff, before adaptation."""
from .store import WorkflowStore
from .workers import local_operation


class VisualPlanner:
    def __init__(self, store: WorkflowStore, *, instance_id='visual-planner-archetypes', production=False):
        self.store, self.instance_id, self.production = store, instance_id, production

    def run_once(self):
        run = self.store.claim('visual_plan_runs', 'visual_plan_run_id', self.instance_id, lease_seconds=600)
        return None if run is None else self._process(run)

    @local_operation('visual_plan_runs', 'visual_plan_run_id')
    def _process(self, run):
        return self.store.create_visual_recipe(run)
