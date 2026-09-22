"""System-level observability dashboard."""

from dashboard.detection import render_detection_dashboard
from dashboard.planning import render_threads as render_workflow_trace

__all__ = ["render_detection_dashboard", "render_workflow_trace"]
