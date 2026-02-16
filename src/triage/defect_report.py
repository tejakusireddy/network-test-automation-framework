"""Structured defect report data model and serialization.

Defines the ``DefectReport`` dataclass used by the log analyzer and
reporting modules.  Supports JSON and Markdown export for integration
with ticketing systems (Jira, GitHub Issues, etc.).

Usage::

    report = DefectReport(
        title="BGP session flap on spine1",
        summary="Peer 10.0.0.1 oscillating between Established and Active",
        severity=DefectSeverity.HIGH,
        ...
    )
    print(report.to_markdown())
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

logger = logging.getLogger(__name__)


class DefectSeverity(StrEnum):
    """Severity classification for defects."""

    BLOCKER = "blocker"
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


@dataclass
class DefectReport:
    """Structured defect report generated from failure analysis.

    Attributes:
        title: One-line defect summary.
        summary: Multi-sentence description of the failure.
        probable_root_cause: AI-inferred most likely cause.
        affected_components: List of devices, protocols, or subsystems.
        severity: Defect severity classification.
        recommended_actions: Ordered remediation steps.
        test_name: Name of the test that failed.
        device: Device hostname where the failure was observed.
        error_output: Raw test failure output.
        device_logs: Relevant device log excerpts.
        timestamp: ISO-8601 timestamp of report creation.
        metadata: Arbitrary additional context.

    """

    title: str
    summary: str
    probable_root_cause: str
    affected_components: list[str] = field(default_factory=list)
    severity: DefectSeverity = DefectSeverity.MEDIUM
    recommended_actions: list[str] = field(default_factory=list)
    test_name: str = ""
    device: str = ""
    error_output: str = ""
    device_logs: str = ""
    timestamp: str = field(
        default_factory=lambda: datetime.now(UTC).isoformat()
    )
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> str:
        """Serialize the report to a JSON string."""
        data = asdict(self)
        data["severity"] = self.severity.value
        return json.dumps(data, indent=2, default=str)

    @classmethod
    def from_json(cls, data: str) -> DefectReport:
        """Deserialize a report from a JSON string."""
        payload: dict[str, Any] = json.loads(data)
        payload["severity"] = DefectSeverity(payload.get("severity", "medium"))
        return cls(**payload)

    def to_markdown(self) -> str:
        """Render the report as a Markdown document.

        Returns:
            Formatted Markdown string suitable for Jira or GitHub.

        """
        actions = "\n".join(
            f"{i}. {action}" for i, action in enumerate(self.recommended_actions, 1)
        )
        components = ", ".join(self.affected_components) if self.affected_components else "N/A"

        return f"""# {self.title}

**Severity:** {self.severity.value.upper()}
**Device:** {self.device or 'N/A'}
**Test:** {self.test_name or 'N/A'}
**Timestamp:** {self.timestamp}

## Summary

{self.summary}

## Probable Root Cause

{self.probable_root_cause}

## Affected Components

{components}

## Recommended Actions

{actions if actions else 'No specific actions recommended.'}

## Error Output

```
{self.error_output[:2000] if self.error_output else 'No error output captured.'}
```

## Device Logs

```
{self.device_logs[:2000] if self.device_logs else 'No device logs captured.'}
```
"""

    def to_dict(self) -> dict[str, Any]:
        """Convert to a plain dictionary for template rendering."""
        data = asdict(self)
        data["severity"] = self.severity.value
        return data
