"""Assertion-style validators for network state verification.

Each validator function compares captured device state against expected
conditions and returns a ``ValidationResult``.  The validators are
designed to be composable and produce machine-readable output suitable
for both CI pipelines and human-readable reports.

Usage::

    validator = StateValidator()
    result = validator.assert_bgp_neighbor_established(
        bgp_data, peer="10.0.0.1"
    )
    if not result.passed:
        print(result.message)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from .base_driver import BgpState, InterfaceState

logger = logging.getLogger(__name__)


class Severity(StrEnum):
    """Severity level for validation results."""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


@dataclass
class ValidationResult:
    """Outcome of a single validation assertion.

    Attributes:
        name: Short identifier for the assertion.
        passed: Whether the assertion succeeded.
        message: Human-readable description of the outcome.
        severity: Impact level if the assertion failed.
        expected: The expected value or condition.
        actual: The observed value.
        device: Hostname of the target device.
        details: Additional context for troubleshooting.

    """

    name: str
    passed: bool
    message: str
    severity: Severity = Severity.MEDIUM
    expected: Any = None
    actual: Any = None
    device: str = ""
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class ValidationReport:
    """Aggregated collection of validation results.

    Attributes:
        device: Hostname of the target device.
        results: Ordered list of individual validation outcomes.

    """

    device: str
    results: list[ValidationResult] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        """Return ``True`` only if every result passed."""
        return all(r.passed for r in self.results)

    @property
    def pass_count(self) -> int:
        """Number of passing assertions."""
        return sum(1 for r in self.results if r.passed)

    @property
    def fail_count(self) -> int:
        """Number of failing assertions."""
        return sum(1 for r in self.results if not r.passed)

    def add(self, result: ValidationResult) -> None:
        """Append a validation result to the report."""
        self.results.append(result)

    def summary(self) -> str:
        """Return a one-line summary string."""
        total = len(self.results)
        return f"[{self.device}] {self.pass_count}/{total} passed, {self.fail_count}/{total} failed"


class StateValidator:
    """Collection of assertion methods for network state validation.

    All ``assert_*`` methods return a ``ValidationResult`` rather than
    raising on failure, allowing callers to accumulate results into a
    ``ValidationReport``.

    Args:
        device: Default device hostname attached to results.

    """

    def __init__(self, device: str = "") -> None:
        """Initialize the validator with an optional device hostname."""
        self._device = device
        self._logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

    def assert_bgp_neighbor_established(
        self,
        bgp_data: dict[str, Any],
        peer: str,
    ) -> ValidationResult:
        """Assert a specific BGP peer is in ESTABLISHED state.

        Args:
            bgp_data: BGP neighbor table from ``get_bgp_neighbors()``.
            peer: The peer address to validate.

        Returns:
            A ``ValidationResult`` indicating pass or fail.

        """
        neighbor = bgp_data.get(peer)
        if neighbor is None:
            return ValidationResult(
                name="bgp_neighbor_established",
                passed=False,
                message=f"BGP peer {peer} not found in neighbor table",
                severity=Severity.CRITICAL,
                expected=BgpState.ESTABLISHED.value,
                actual="not_found",
                device=self._device,
            )

        state = str(neighbor.get("state", "unknown")).lower()
        passed = state == BgpState.ESTABLISHED.value
        return ValidationResult(
            name="bgp_neighbor_established",
            passed=passed,
            message=(
                f"BGP peer {peer} is {state}"
                if passed
                else f"BGP peer {peer} expected ESTABLISHED, got {state}"
            ),
            severity=Severity.CRITICAL if not passed else Severity.INFO,
            expected=BgpState.ESTABLISHED.value,
            actual=state,
            device=self._device,
            details=neighbor,
        )

    def assert_all_bgp_established(
        self,
        bgp_data: dict[str, Any],
    ) -> list[ValidationResult]:
        """Assert every BGP peer is in ESTABLISHED state.

        Args:
            bgp_data: BGP neighbor table from ``get_bgp_neighbors()``.

        Returns:
            List of ``ValidationResult`` objects, one per peer.

        """
        results: list[ValidationResult] = []
        for peer in sorted(bgp_data.keys()):
            results.append(self.assert_bgp_neighbor_established(bgp_data, peer))
        return results

    def assert_interface_up(
        self,
        interface_data: dict[str, Any],
        interface_name: str,
    ) -> ValidationResult:
        """Assert a specific interface is operationally up.

        Args:
            interface_data: Interface table from ``get_interfaces()``.
            interface_name: Name of the interface to validate.

        Returns:
            A ``ValidationResult`` indicating pass or fail.

        """
        iface = interface_data.get(interface_name)
        if iface is None:
            return ValidationResult(
                name="interface_up",
                passed=False,
                message=f"Interface {interface_name} not found",
                severity=Severity.HIGH,
                expected=InterfaceState.UP.value,
                actual="not_found",
                device=self._device,
            )

        oper_status = str(iface.get("oper_status", "unknown")).lower()
        passed = oper_status == InterfaceState.UP.value
        return ValidationResult(
            name="interface_up",
            passed=passed,
            message=(
                f"Interface {interface_name} is {oper_status}"
                if passed
                else f"Interface {interface_name} expected UP, got {oper_status}"
            ),
            severity=Severity.HIGH if not passed else Severity.INFO,
            expected=InterfaceState.UP.value,
            actual=oper_status,
            device=self._device,
        )

    def assert_no_interface_errors(
        self,
        interface_data: dict[str, Any],
        interface_name: str,
        threshold: int = 0,
    ) -> ValidationResult:
        """Assert an interface has no (or below-threshold) error counters.

        Args:
            interface_data: Interface table from ``get_interfaces()``.
            interface_name: Name of the interface to validate.
            threshold: Maximum acceptable combined error count.

        Returns:
            A ``ValidationResult`` indicating pass or fail.

        """
        iface = interface_data.get(interface_name)
        if iface is None:
            return ValidationResult(
                name="no_interface_errors",
                passed=False,
                message=f"Interface {interface_name} not found",
                severity=Severity.HIGH,
                expected=f"errors <= {threshold}",
                actual="not_found",
                device=self._device,
            )

        input_errors = int(iface.get("input_errors", 0))
        output_errors = int(iface.get("output_errors", 0))
        total_errors = input_errors + output_errors
        passed = total_errors <= threshold

        return ValidationResult(
            name="no_interface_errors",
            passed=passed,
            message=(
                f"Interface {interface_name} has {total_errors} errors (threshold: {threshold})"
            ),
            severity=Severity.MEDIUM if not passed else Severity.INFO,
            expected=f"errors <= {threshold}",
            actual=total_errors,
            device=self._device,
            details={
                "input_errors": input_errors,
                "output_errors": output_errors,
            },
        )

    def assert_route_exists(
        self,
        routing_data: dict[str, Any],
        prefix: str,
        expected_next_hop: str | None = None,
        expected_protocol: str | None = None,
    ) -> ValidationResult:
        """Assert a route exists in the RIB with optional attribute checks.

        Args:
            routing_data: Routing table from ``get_routing_table()``.
            prefix: The IP prefix to look up (e.g., ``10.0.0.0/24``).
            expected_next_hop: If given, assert the next-hop matches.
            expected_protocol: If given, assert the protocol matches.

        Returns:
            A ``ValidationResult`` indicating pass or fail.

        """
        route = routing_data.get(prefix)
        if route is None:
            return ValidationResult(
                name="route_exists",
                passed=False,
                message=f"Route {prefix} not found in routing table",
                severity=Severity.CRITICAL,
                expected=prefix,
                actual="not_found",
                device=self._device,
            )

        issues: list[str] = []
        if expected_next_hop and route.get("next_hop") != expected_next_hop:
            issues.append(f"next-hop expected {expected_next_hop}, got {route.get('next_hop')}")
        if expected_protocol and route.get("protocol") != expected_protocol:
            issues.append(f"protocol expected {expected_protocol}, got {route.get('protocol')}")

        passed = len(issues) == 0
        return ValidationResult(
            name="route_exists",
            passed=passed,
            message=(
                f"Route {prefix} present and valid"
                if passed
                else f"Route {prefix}: {'; '.join(issues)}"
            ),
            severity=Severity.CRITICAL if not passed else Severity.INFO,
            expected=prefix,
            actual=route,
            device=self._device,
        )

    def assert_evpn_route_type(
        self,
        evpn_data: dict[str, Any],
        route_type: int,
        expected_count: int | None = None,
    ) -> ValidationResult:
        """Assert EVPN routes of a specific type exist.

        Args:
            evpn_data: EVPN route table from ``get_evpn_routes()``.
            route_type: EVPN route type (2 = MAC/IP, 5 = IP prefix).
            expected_count: If given, assert exactly this many routes.

        Returns:
            A ``ValidationResult`` indicating pass or fail.

        """
        matching = {
            rd: entry for rd, entry in evpn_data.items() if entry.get("route_type") == route_type
        }
        count = len(matching)

        if expected_count is not None:
            passed = count == expected_count
            message = f"EVPN type-{route_type}: found {count} routes (expected {expected_count})"
        else:
            passed = count > 0
            message = (
                f"EVPN type-{route_type}: found {count} routes"
                if passed
                else f"No EVPN type-{route_type} routes found"
            )

        return ValidationResult(
            name="evpn_route_type",
            passed=passed,
            message=message,
            severity=Severity.HIGH if not passed else Severity.INFO,
            expected=expected_count if expected_count is not None else ">0",
            actual=count,
            device=self._device,
            details={"matching_routes": matching},
        )

    def assert_lldp_neighbor(
        self,
        lldp_data: dict[str, Any],
        local_interface: str,
        expected_neighbor: str | None = None,
    ) -> ValidationResult:
        """Assert an LLDP neighbor exists on a given interface.

        Args:
            lldp_data: LLDP neighbor table from ``get_lldp_neighbors()``.
            local_interface: Local interface name to check.
            expected_neighbor: If given, assert the neighbor system name.

        Returns:
            A ``ValidationResult`` indicating pass or fail.

        """
        neighbor = lldp_data.get(local_interface)
        if neighbor is None:
            return ValidationResult(
                name="lldp_neighbor",
                passed=False,
                message=f"No LLDP neighbor on {local_interface}",
                severity=Severity.HIGH,
                expected=expected_neighbor or "any",
                actual="not_found",
                device=self._device,
            )

        remote_system = neighbor.get("remote_system", "")
        if expected_neighbor and remote_system != expected_neighbor:
            return ValidationResult(
                name="lldp_neighbor",
                passed=False,
                message=(
                    f"LLDP on {local_interface}: expected {expected_neighbor}, got {remote_system}"
                ),
                severity=Severity.HIGH,
                expected=expected_neighbor,
                actual=remote_system,
                device=self._device,
            )

        return ValidationResult(
            name="lldp_neighbor",
            passed=True,
            message=f"LLDP neighbor {remote_system} present on {local_interface}",
            severity=Severity.INFO,
            expected=expected_neighbor or "any",
            actual=remote_system,
            device=self._device,
        )

    def run_full_validation(
        self,
        bgp_data: dict[str, Any],
        interface_data: dict[str, Any],
        routing_data: dict[str, Any],
        lldp_data: dict[str, Any],
        evpn_data: dict[str, Any],
    ) -> ValidationReport:
        """Run a comprehensive validation suite and return a report.

        Args:
            bgp_data: BGP neighbor table.
            interface_data: Interface table.
            routing_data: Routing table.
            lldp_data: LLDP neighbor table.
            evpn_data: EVPN route table.

        Returns:
            A ``ValidationReport`` with all individual results.

        """
        report = ValidationReport(device=self._device)

        for peer in bgp_data:
            report.add(self.assert_bgp_neighbor_established(bgp_data, peer))

        for iface_name in interface_data:
            report.add(self.assert_interface_up(interface_data, iface_name))
            report.add(self.assert_no_interface_errors(interface_data, iface_name))

        for prefix in routing_data:
            report.add(self.assert_route_exists(routing_data, prefix))

        for local_iface in lldp_data:
            report.add(self.assert_lldp_neighbor(lldp_data, local_iface))

        if evpn_data:
            report.add(self.assert_evpn_route_type(evpn_data, route_type=2))
            report.add(self.assert_evpn_route_type(evpn_data, route_type=5))

        self._logger.info("Validation report: %s", report.summary())
        return report
