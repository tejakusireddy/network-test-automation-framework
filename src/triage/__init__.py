"""AI-powered failure triage and structured defect reporting.

Uses LLM analysis (Claude API) to examine test failures and device
logs, producing structured defect reports with root cause analysis
and remediation recommendations.
"""

from .defect_report import DefectReport, DefectSeverity
from .log_analyzer import LogAnalyzer

__all__ = ["DefectReport", "DefectSeverity", "LogAnalyzer"]
