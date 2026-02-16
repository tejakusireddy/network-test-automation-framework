"""Unit tests for the StateValidator assertion methods."""

from __future__ import annotations

from typing import Any

import pytest

from src.core.validator import (
    Severity,
    StateValidator,
    ValidationReport,
    ValidationResult,
)


class TestAssertBgpNeighborEstablished:
    """Tests for assert_bgp_neighbor_established."""

    def test_established_peer_passes(
        self, validator: StateValidator, sample_bgp_data: dict[str, Any]
    ) -> None:
        result = validator.assert_bgp_neighbor_established(sample_bgp_data, "10.0.0.1")
        assert result.passed is True
        assert result.severity == Severity.INFO

    def test_active_peer_fails(
        self, validator: StateValidator, sample_bgp_data: dict[str, Any]
    ) -> None:
        result = validator.assert_bgp_neighbor_established(sample_bgp_data, "10.0.0.3")
        assert result.passed is False
        assert result.severity == Severity.CRITICAL
        assert "active" in result.message

    def test_missing_peer_fails(
        self, validator: StateValidator, sample_bgp_data: dict[str, Any]
    ) -> None:
        result = validator.assert_bgp_neighbor_established(sample_bgp_data, "10.99.99.99")
        assert result.passed is False
        assert "not found" in result.message


class TestAssertAllBgpEstablished:
    """Tests for assert_all_bgp_established."""

    def test_returns_result_per_peer(
        self, validator: StateValidator, sample_bgp_data: dict[str, Any]
    ) -> None:
        results = validator.assert_all_bgp_established(sample_bgp_data)
        assert len(results) == 3

    def test_detects_non_established(
        self, validator: StateValidator, sample_bgp_data: dict[str, Any]
    ) -> None:
        results = validator.assert_all_bgp_established(sample_bgp_data)
        failures = [r for r in results if not r.passed]
        assert len(failures) == 1
        assert failures[0].actual == "active"


class TestAssertInterfaceUp:
    """Tests for assert_interface_up."""

    def test_up_interface_passes(
        self, validator: StateValidator, sample_interface_data: dict[str, Any]
    ) -> None:
        result = validator.assert_interface_up(sample_interface_data, "et-0/0/0")
        assert result.passed is True

    def test_down_interface_fails(
        self, validator: StateValidator, sample_interface_data: dict[str, Any]
    ) -> None:
        result = validator.assert_interface_up(sample_interface_data, "et-0/0/2")
        assert result.passed is False
        assert result.severity == Severity.HIGH

    def test_missing_interface_fails(
        self, validator: StateValidator, sample_interface_data: dict[str, Any]
    ) -> None:
        result = validator.assert_interface_up(sample_interface_data, "et-0/0/99")
        assert result.passed is False


class TestAssertNoInterfaceErrors:
    """Tests for assert_no_interface_errors."""

    def test_clean_interface_passes(
        self, validator: StateValidator, sample_interface_data: dict[str, Any]
    ) -> None:
        result = validator.assert_no_interface_errors(sample_interface_data, "et-0/0/0")
        assert result.passed is True

    def test_errored_interface_fails(
        self, validator: StateValidator, sample_interface_data: dict[str, Any]
    ) -> None:
        result = validator.assert_no_interface_errors(sample_interface_data, "et-0/0/2")
        assert result.passed is False
        assert result.details["input_errors"] == 5

    def test_threshold_allows_some_errors(
        self, validator: StateValidator, sample_interface_data: dict[str, Any]
    ) -> None:
        result = validator.assert_no_interface_errors(
            sample_interface_data, "et-0/0/2", threshold=10
        )
        assert result.passed is True


class TestAssertRouteExists:
    """Tests for assert_route_exists."""

    def test_existing_route_passes(
        self, validator: StateValidator, sample_routing_data: dict[str, Any]
    ) -> None:
        result = validator.assert_route_exists(sample_routing_data, "10.0.0.0/24")
        assert result.passed is True

    def test_missing_route_fails(
        self, validator: StateValidator, sample_routing_data: dict[str, Any]
    ) -> None:
        result = validator.assert_route_exists(sample_routing_data, "172.16.0.0/16")
        assert result.passed is False
        assert result.severity == Severity.CRITICAL

    def test_wrong_next_hop_fails(
        self, validator: StateValidator, sample_routing_data: dict[str, Any]
    ) -> None:
        result = validator.assert_route_exists(
            sample_routing_data, "10.0.0.0/24", expected_next_hop="1.2.3.4"
        )
        assert result.passed is False
        assert "next-hop" in result.message

    def test_correct_protocol_passes(
        self, validator: StateValidator, sample_routing_data: dict[str, Any]
    ) -> None:
        result = validator.assert_route_exists(
            sample_routing_data, "10.0.0.0/24", expected_protocol="ospf"
        )
        assert result.passed is True


class TestAssertEvpnRouteType:
    """Tests for assert_evpn_route_type."""

    def test_type2_routes_found(
        self, validator: StateValidator, sample_evpn_data: dict[str, Any]
    ) -> None:
        result = validator.assert_evpn_route_type(sample_evpn_data, route_type=2)
        assert result.passed is True

    def test_type5_routes_found(
        self, validator: StateValidator, sample_evpn_data: dict[str, Any]
    ) -> None:
        result = validator.assert_evpn_route_type(sample_evpn_data, route_type=5)
        assert result.passed is True

    def test_missing_type_fails(
        self, validator: StateValidator, sample_evpn_data: dict[str, Any]
    ) -> None:
        result = validator.assert_evpn_route_type(sample_evpn_data, route_type=3)
        assert result.passed is False

    def test_exact_count_match(
        self, validator: StateValidator, sample_evpn_data: dict[str, Any]
    ) -> None:
        result = validator.assert_evpn_route_type(sample_evpn_data, route_type=2, expected_count=1)
        assert result.passed is True


class TestAssertLldpNeighbor:
    """Tests for assert_lldp_neighbor."""

    def test_existing_neighbor_passes(
        self, validator: StateValidator, sample_lldp_data: dict[str, Any]
    ) -> None:
        result = validator.assert_lldp_neighbor(sample_lldp_data, "et-0/0/0")
        assert result.passed is True

    def test_expected_neighbor_matches(
        self, validator: StateValidator, sample_lldp_data: dict[str, Any]
    ) -> None:
        result = validator.assert_lldp_neighbor(
            sample_lldp_data, "et-0/0/0", expected_neighbor="spine2"
        )
        assert result.passed is True

    def test_wrong_neighbor_fails(
        self, validator: StateValidator, sample_lldp_data: dict[str, Any]
    ) -> None:
        result = validator.assert_lldp_neighbor(
            sample_lldp_data, "et-0/0/0", expected_neighbor="wrong-device"
        )
        assert result.passed is False

    def test_missing_interface_fails(
        self, validator: StateValidator, sample_lldp_data: dict[str, Any]
    ) -> None:
        result = validator.assert_lldp_neighbor(sample_lldp_data, "et-0/0/99")
        assert result.passed is False


class TestValidationReport:
    """Tests for the ValidationReport aggregation."""

    def test_all_pass(self) -> None:
        report = ValidationReport(device="test")
        report.add(ValidationResult(name="a", passed=True, message="ok"))
        report.add(ValidationResult(name="b", passed=True, message="ok"))
        assert report.passed is True
        assert report.pass_count == 2
        assert report.fail_count == 0

    def test_mixed_results(self) -> None:
        report = ValidationReport(device="test")
        report.add(ValidationResult(name="a", passed=True, message="ok"))
        report.add(ValidationResult(name="b", passed=False, message="fail"))
        assert report.passed is False
        assert report.pass_count == 1
        assert report.fail_count == 1

    def test_summary_format(self) -> None:
        report = ValidationReport(device="spine1")
        report.add(ValidationResult(name="a", passed=True, message="ok"))
        report.add(ValidationResult(name="b", passed=False, message="fail"))
        summary = report.summary()
        assert "spine1" in summary
        assert "1/2 passed" in summary


class TestRunFullValidation:
    """Tests for the run_full_validation method."""

    def test_produces_comprehensive_report(
        self,
        validator: StateValidator,
        sample_bgp_data: dict[str, Any],
        sample_interface_data: dict[str, Any],
        sample_routing_data: dict[str, Any],
        sample_lldp_data: dict[str, Any],
        sample_evpn_data: dict[str, Any],
    ) -> None:
        report = validator.run_full_validation(
            bgp_data=sample_bgp_data,
            interface_data=sample_interface_data,
            routing_data=sample_routing_data,
            lldp_data=sample_lldp_data,
            evpn_data=sample_evpn_data,
        )
        assert isinstance(report, ValidationReport)
        assert report.device == "spine1"
        assert len(report.results) > 0
        assert report.fail_count > 0  # BGP active peer + interface down
