"""HTML/PDF test report generation using Jinja2 templates.

Collects test results, validation reports, snapshot diffs, and AI triage
output, then renders them into a comprehensive HTML report.  Optionally
converts to PDF via weasyprint.

Usage::

    gen = ReportGenerator()
    gen.add_validation_report(report)
    gen.add_triage_report(defect)
    gen.generate("output/report.html")
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..core.base_driver import SnapshotDiff
    from ..core.validator import ValidationReport
    from ..triage.defect_report import DefectReport

logger = logging.getLogger(__name__)

TEMPLATE_DIR = Path(__file__).parent / "templates"
DEFAULT_TEMPLATE = "report_template.html"


@dataclass
class TestResult:
    """Individual test result for report inclusion.

    Attributes:
        name: Test name/identifier.
        status: ``passed``, ``failed``, ``skipped``, or ``error``.
        duration_seconds: Execution time.
        device: Device under test.
        message: Short result message.
        details: Extended output or traceback.

    """

    name: str
    status: str
    duration_seconds: float = 0.0
    device: str = ""
    message: str = ""
    details: str = ""


@dataclass
class ReportData:
    """Aggregated data model passed to the Jinja2 template.

    Attributes:
        title: Report title.
        timestamp: ISO-8601 generation timestamp.
        environment: Environment metadata (testbed, software versions).
        test_results: Individual test outcomes.
        validation_reports: Per-device validation reports.
        snapshot_diffs: Pre/post change diffs.
        triage_reports: AI-generated defect reports.
        topology_mermaid: Mermaid diagram source for topology.

    """

    title: str = "Network Test Automation Report"
    timestamp: str = field(
        default_factory=lambda: datetime.now(UTC).isoformat()
    )
    environment: dict[str, str] = field(default_factory=dict)
    test_results: list[TestResult] = field(default_factory=list)
    validation_reports: list[dict[str, Any]] = field(default_factory=list)
    snapshot_diffs: list[dict[str, Any]] = field(default_factory=list)
    triage_reports: list[dict[str, Any]] = field(default_factory=list)
    topology_mermaid: str = ""

    @property
    def total_tests(self) -> int:
        """Total number of tests."""
        return len(self.test_results)

    @property
    def passed_tests(self) -> int:
        """Number of passing tests."""
        return sum(1 for t in self.test_results if t.status == "passed")

    @property
    def failed_tests(self) -> int:
        """Number of failing tests."""
        return sum(1 for t in self.test_results if t.status == "failed")

    @property
    def pass_rate(self) -> float:
        """Pass rate as a percentage."""
        if self.total_tests == 0:
            return 0.0
        return (self.passed_tests / self.total_tests) * 100


class ReportGenerator:
    """Generate HTML test reports from Jinja2 templates.

    Collects test results, validation reports, snapshot diffs, and
    triage output, then renders everything into a single HTML file.

    Args:
        template_dir: Directory containing Jinja2 templates.
        template_name: Name of the main report template.

    """

    def __init__(
        self,
        template_dir: Path = TEMPLATE_DIR,
        template_name: str = DEFAULT_TEMPLATE,
    ) -> None:
        """Initialize the report generator with template settings."""
        self._template_dir = template_dir
        self._template_name = template_name
        self._data = ReportData()
        self._logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

    def set_title(self, title: str) -> None:
        """Set the report title."""
        self._data.title = title

    def set_environment(self, env: dict[str, str]) -> None:
        """Set environment metadata (testbed name, versions, etc.)."""
        self._data.environment = env

    def set_topology_diagram(self, mermaid_src: str) -> None:
        """Set the Mermaid topology diagram source."""
        self._data.topology_mermaid = mermaid_src

    def add_test_result(self, result: TestResult) -> None:
        """Add an individual test result."""
        self._data.test_results.append(result)

    def add_validation_report(self, report: ValidationReport) -> None:
        """Add a per-device validation report."""
        self._data.validation_reports.append({
            "device": report.device,
            "passed": report.passed,
            "pass_count": report.pass_count,
            "fail_count": report.fail_count,
            "summary": report.summary(),
            "results": [
                {
                    "name": r.name,
                    "passed": r.passed,
                    "message": r.message,
                    "severity": r.severity.value,
                    "expected": str(r.expected),
                    "actual": str(r.actual),
                }
                for r in report.results
            ],
        })

    def add_snapshot_diff(self, diff: SnapshotDiff) -> None:
        """Add a snapshot comparison result."""
        self._data.snapshot_diffs.append({
            "device": diff.device,
            "pre_id": diff.pre_id,
            "post_id": diff.post_id,
            "has_changes": diff.has_changes,
            "added_count": len(diff.added),
            "removed_count": len(diff.removed),
            "changed_count": len(diff.changed),
            "diffs": [
                {
                    "category": d.category,
                    "key": d.key,
                    "action": d.action,
                    "before": str(d.before) if d.before else "",
                    "after": str(d.after) if d.after else "",
                }
                for d in diff.diffs
            ],
        })

    def add_triage_report(self, defect: DefectReport) -> None:
        """Add an AI-generated defect triage report."""
        self._data.triage_reports.append(defect.to_dict())

    def generate(self, output_path: str | Path) -> Path:
        """Render the HTML report and write to disk.

        Args:
            output_path: Destination file path.

        Returns:
            Path to the generated report file.

        """
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)

        html = self._render()
        output.write_text(html, encoding="utf-8")
        self._logger.info("Report generated: %s", output)
        return output

    def generate_pdf(self, output_path: str | Path) -> Path:
        """Render the report as PDF via weasyprint.

        Args:
            output_path: Destination PDF file path.

        Returns:
            Path to the generated PDF file.

        """
        try:
            from weasyprint import HTML  # type: ignore[import-untyped]
        except ImportError:
            raise RuntimeError(
                "weasyprint is not installed. Install with: pip install weasyprint"
            ) from None

        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)

        html = self._render()
        HTML(string=html).write_pdf(str(output))
        self._logger.info("PDF report generated: %s", output)
        return output

    def _render(self) -> str:
        """Render the Jinja2 template with report data."""
        try:
            from jinja2 import Environment, FileSystemLoader  # type: ignore[import-untyped]
        except ImportError:
            raise RuntimeError(
                "jinja2 is not installed. Install with: pip install Jinja2"
            ) from None

        env = Environment(
            loader=FileSystemLoader(str(self._template_dir)),
            autoescape=True,
        )
        template = env.get_template(self._template_name)
        return template.render(
            data=self._data,
            title=self._data.title,
            timestamp=self._data.timestamp,
            environment=self._data.environment,
            test_results=self._data.test_results,
            validation_reports=self._data.validation_reports,
            snapshot_diffs=self._data.snapshot_diffs,
            triage_reports=self._data.triage_reports,
            topology_mermaid=self._data.topology_mermaid,
            total_tests=self._data.total_tests,
            passed_tests=self._data.passed_tests,
            failed_tests=self._data.failed_tests,
            pass_rate=self._data.pass_rate,
        )
