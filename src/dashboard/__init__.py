"""System-level observability dashboard."""

from dashboard.renderer import render_dashboard
from dashboard.detection import render_detection_dashboard

__all__ = ["render_dashboard", "render_detection_dashboard"]
