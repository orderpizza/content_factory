"""System-level observability dashboard."""

from dashboard.renderer import render_dashboard
from dashboard.detection import render_detection_dashboard
from dashboard.workflow import render_workflow_trace

__all__ = ["render_dashboard", "render_detection_dashboard", "render_workflow_trace"]
