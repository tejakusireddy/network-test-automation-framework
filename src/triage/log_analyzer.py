"""LLM-powered failure analysis using the Anthropic Claude API.

Takes failed test output and device logs, constructs a structured
prompt, sends it to Claude, and parses the response into a
``DefectReport``.

Requires:
    - anthropic SDK
    - ANTHROPIC_API_KEY environment variable

Usage::

    analyzer = LogAnalyzer()
    report = analyzer.analyze_failure(
        test_name="test_bgp_established",
        error_output="AssertionError: BGP peer 10.0.0.1 state=active",
        device_logs="Jan 1 00:00:00 spine1 rpd: BGP peer 10.0.0.1 ...",
        device="spine1",
    )
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from ..core.exceptions import TriageError
from .defect_report import DefectReport, DefectSeverity

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-sonnet-4-20250514"
MAX_LOG_CHARS = 8000
MAX_OUTPUT_CHARS = 4000

SYSTEM_PROMPT = """You are a senior network engineer specializing in data center \
fabrics (BGP, OSPF, EVPN-VXLAN, LLDP). You are triaging automated test failures.

Analyze the provided test failure output and device logs, then produce a \
structured JSON response with exactly these fields:

{
  "title": "One-line defect summary",
  "summary": "2-3 sentence description of what happened",
  "probable_root_cause": "Most likely technical root cause",
  "affected_components": ["list", "of", "affected", "subsystems"],
  "severity": "blocker|critical|high|medium|low",
  "recommended_actions": ["Step 1...", "Step 2...", "Step 3..."]
}

Be specific and technical. Reference actual protocol states, timer values, \
and configuration parameters when relevant."""


class LogAnalyzer:
    """AI-powered failure triage using the Anthropic Claude API.

    Constructs structured prompts from test failures and device logs,
    sends them to Claude for analysis, and parses the response into
    a ``DefectReport``.

    Args:
        api_key: Anthropic API key.  Falls back to
            ``ANTHROPIC_API_KEY`` environment variable.
        model: Claude model identifier.

    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str = DEFAULT_MODEL,
    ) -> None:
        """Initialize the log analyzer with API credentials and model selection."""
        self._api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self._model = model
        self._logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

    def analyze_failure(
        self,
        test_name: str,
        error_output: str,
        device_logs: str = "",
        device: str = "",
        context: dict[str, Any] | None = None,
    ) -> DefectReport:
        """Analyze a test failure and produce a structured defect report.

        Args:
            test_name: Name of the failed test.
            error_output: Raw assertion/error output from the test.
            device_logs: Relevant syslog or journal entries.
            device: Hostname of the device under test.
            context: Optional extra context (topology, config snippets).

        Returns:
            A ``DefectReport`` with AI-generated triage information.

        Raises:
            TriageError: If the API call fails or the response cannot
                be parsed.

        """
        prompt = self._build_prompt(
            test_name=test_name,
            error_output=error_output,
            device_logs=device_logs,
            device=device,
            context=context,
        )

        self._logger.info("Analyzing failure for test '%s' on %s", test_name, device)

        try:
            response_text = self._call_claude(prompt)
            report = self._parse_response(
                response_text,
                test_name=test_name,
                error_output=error_output,
                device_logs=device_logs,
                device=device,
            )
            self._logger.info("Triage complete: %s", report.title)
            return report
        except TriageError:
            raise
        except Exception as exc:
            raise TriageError(
                f"Failure analysis failed: {exc}",
                device=device,
                details={"test_name": test_name},
            ) from exc

    def analyze_batch(
        self,
        failures: list[dict[str, Any]],
    ) -> list[DefectReport]:
        """Analyze multiple test failures.

        Args:
            failures: List of dicts with keys ``test_name``,
                ``error_output``, ``device_logs``, ``device``.

        Returns:
            List of ``DefectReport`` instances.

        """
        reports: list[DefectReport] = []
        for failure in failures:
            try:
                report = self.analyze_failure(
                    test_name=failure.get("test_name", "unknown"),
                    error_output=failure.get("error_output", ""),
                    device_logs=failure.get("device_logs", ""),
                    device=failure.get("device", ""),
                    context=failure.get("context"),
                )
                reports.append(report)
            except TriageError as exc:
                self._logger.warning("Skipping failure: %s", exc)
        return reports

    # -- Internal helpers ---------------------------------------------------

    def _build_prompt(
        self,
        test_name: str,
        error_output: str,
        device_logs: str,
        device: str,
        context: dict[str, Any] | None,
    ) -> str:
        """Construct the analysis prompt."""
        parts: list[str] = [
            f"## Test Failure: {test_name}",
            f"**Device:** {device or 'unknown'}",
            "",
            "### Error Output",
            "```",
            error_output[:MAX_OUTPUT_CHARS],
            "```",
        ]

        if device_logs:
            parts.extend(
                [
                    "",
                    "### Device Logs",
                    "```",
                    device_logs[:MAX_LOG_CHARS],
                    "```",
                ]
            )

        if context:
            parts.extend(
                [
                    "",
                    "### Additional Context",
                    "```json",
                    json.dumps(context, indent=2, default=str)[:MAX_LOG_CHARS],
                    "```",
                ]
            )

        parts.extend(
            [
                "",
                "Analyze this failure and respond with the JSON structure "
                "described in the system prompt.",
            ]
        )

        return "\n".join(parts)

    def _call_claude(self, prompt: str) -> str:
        """Send the prompt to the Claude API and return the response text.

        Raises:
            TriageError: If the API key is missing or the call fails.

        """
        if not self._api_key:
            raise TriageError(
                "ANTHROPIC_API_KEY not set — cannot perform AI triage",
            )

        try:
            import anthropic

            client = anthropic.Anthropic(api_key=self._api_key)
            message = client.messages.create(
                model=self._model,
                max_tokens=1024,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
            )
            return str(message.content[0].text)
        except ImportError:
            raise TriageError(
                "anthropic SDK not installed. Install with: pip install anthropic"
            ) from None
        except Exception as exc:
            raise TriageError(
                f"Claude API call failed: {exc}",
            ) from exc

    @staticmethod
    def _parse_response(
        response_text: str,
        test_name: str,
        error_output: str,
        device_logs: str,
        device: str,
    ) -> DefectReport:
        """Parse Claude's JSON response into a ``DefectReport``.

        Falls back to using the raw text as the summary if JSON parsing
        fails.
        """
        try:
            text = response_text.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1] if "\n" in text else text[3:]
                if text.endswith("```"):
                    text = text[:-3]

            data: dict[str, Any] = json.loads(text)

            severity_str = data.get("severity", "medium").lower()
            try:
                severity = DefectSeverity(severity_str)
            except ValueError:
                severity = DefectSeverity.MEDIUM

            return DefectReport(
                title=data.get("title", f"Failure in {test_name}"),
                summary=data.get("summary", response_text[:500]),
                probable_root_cause=data.get("probable_root_cause", "Unknown"),
                affected_components=data.get("affected_components", []),
                severity=severity,
                recommended_actions=data.get("recommended_actions", []),
                test_name=test_name,
                device=device,
                error_output=error_output,
                device_logs=device_logs,
            )
        except (json.JSONDecodeError, KeyError, TypeError):
            return DefectReport(
                title=f"Failure in {test_name}",
                summary=response_text[:500],
                probable_root_cause="Unable to parse AI response",
                severity=DefectSeverity.MEDIUM,
                test_name=test_name,
                device=device,
                error_output=error_output,
                device_logs=device_logs,
            )
