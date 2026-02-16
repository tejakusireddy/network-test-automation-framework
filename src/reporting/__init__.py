"""Test report generation in HTML and PDF formats.

Uses Jinja2 templates to produce rich HTML reports with test summaries,
per-device results, topology diagrams, and AI triage output.
"""

from .report_generator import ReportGenerator

__all__ = ["ReportGenerator"]
