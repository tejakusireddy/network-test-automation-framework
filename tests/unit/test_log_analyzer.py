"""Unit tests for the LogAnalyzer and DefectReport."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from src.core.exceptions import TriageError
from src.triage.defect_report import DefectReport, DefectSeverity
from src.triage.log_analyzer import LogAnalyzer


class TestDefectReport:
    """Tests for DefectReport data model."""

    @pytest.fixture
    def sample_report(self) -> DefectReport:
        return DefectReport(
            title="BGP session flap on spine1",
            summary="Peer 10.0.0.1 oscillating between Established and Active",
            probable_root_cause="MTU mismatch on p2p link",
            affected_components=["spine1", "leaf1", "BGP"],
            severity=DefectSeverity.HIGH,
            recommended_actions=[
                "Check MTU on et-0/0/0",
                "Verify BGP timers",
                "Review interface error counters",
            ],
            test_name="test_bgp_established",
            device="spine1",
        )

    def test_json_roundtrip(self, sample_report: DefectReport) -> None:
        json_str = sample_report.to_json()
        restored = DefectReport.from_json(json_str)
        assert restored.title == sample_report.title
        assert restored.severity == DefectSeverity.HIGH
        assert len(restored.recommended_actions) == 3

    def test_to_markdown(self, sample_report: DefectReport) -> None:
        md = sample_report.to_markdown()
        assert "# BGP session flap" in md
        assert "HIGH" in md
        assert "MTU mismatch" in md
        assert "spine1" in md

    def test_to_dict(self, sample_report: DefectReport) -> None:
        data = sample_report.to_dict()
        assert data["severity"] == "high"
        assert isinstance(data["affected_components"], list)


class TestLogAnalyzer:
    """Tests for the LogAnalyzer Claude API integration."""

    @pytest.fixture
    def analyzer(self) -> LogAnalyzer:
        return LogAnalyzer(api_key="test-key")

    def test_missing_api_key_raises(self) -> None:
        analyzer = LogAnalyzer(api_key="")
        with pytest.raises(TriageError, match="ANTHROPIC_API_KEY"):
            analyzer.analyze_failure(
                test_name="test",
                error_output="error",
            )

    @patch("src.triage.log_analyzer.LogAnalyzer._call_claude")
    def test_successful_analysis(self, mock_claude: MagicMock, analyzer: LogAnalyzer) -> None:
        mock_claude.return_value = json.dumps(
            {
                "title": "BGP peer down",
                "summary": "Peer is not establishing",
                "probable_root_cause": "Authentication mismatch",
                "affected_components": ["BGP", "spine1"],
                "severity": "high",
                "recommended_actions": ["Check MD5 keys"],
            }
        )

        report = analyzer.analyze_failure(
            test_name="test_bgp",
            error_output="BGP peer 10.0.0.1 not established",
            device="spine1",
        )

        assert report.title == "BGP peer down"
        assert report.severity == DefectSeverity.HIGH
        assert len(report.recommended_actions) == 1
        assert report.device == "spine1"

    @patch("src.triage.log_analyzer.LogAnalyzer._call_claude")
    def test_malformed_json_fallback(self, mock_claude: MagicMock, analyzer: LogAnalyzer) -> None:
        mock_claude.return_value = "This is not JSON but a useful analysis"

        report = analyzer.analyze_failure(
            test_name="test_routes",
            error_output="Route missing",
        )

        assert "test_routes" in report.title
        assert "Unable to parse" in report.probable_root_cause

    @patch("src.triage.log_analyzer.LogAnalyzer._call_claude")
    def test_batch_analysis(self, mock_claude: MagicMock, analyzer: LogAnalyzer) -> None:
        mock_claude.return_value = json.dumps(
            {
                "title": "Test failure",
                "summary": "Something failed",
                "probable_root_cause": "Unknown",
                "affected_components": [],
                "severity": "medium",
                "recommended_actions": [],
            }
        )

        failures = [
            {"test_name": "test_a", "error_output": "error_a", "device": "d1"},
            {"test_name": "test_b", "error_output": "error_b", "device": "d2"},
        ]
        reports = analyzer.analyze_batch(failures)
        assert len(reports) == 2

    def test_build_prompt_structure(self, analyzer: LogAnalyzer) -> None:
        prompt = analyzer._build_prompt(
            test_name="test_bgp",
            error_output="Error text here",
            device_logs="syslog lines",
            device="spine1",
            context={"topology": "leaf-spine"},
        )
        assert "test_bgp" in prompt
        assert "Error text here" in prompt
        assert "syslog lines" in prompt
        assert "topology" in prompt


class TestDefectSeverity:
    """Tests for DefectSeverity enum."""

    def test_values(self) -> None:
        assert DefectSeverity.BLOCKER.value == "blocker"
        assert DefectSeverity.LOW.value == "low"

    def test_from_string(self) -> None:
        assert DefectSeverity("critical") == DefectSeverity.CRITICAL
