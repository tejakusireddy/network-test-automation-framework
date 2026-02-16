"""Integration tests for driver connectivity with real or containerlab devices.

These tests require a running containerlab topology and are excluded
from the default test run.  Enable with: ``pytest -m integration``.
"""

from __future__ import annotations

import os
from typing import Any

import pytest

from src.core.base_driver import DeviceInfo
from src.core.snapshot_engine import SnapshotEngine
from src.core.validator import StateValidator
from src.drivers.driver_factory import DriverFactory

pytestmark = pytest.mark.integration

TOPOLOGY_HOSTS: list[dict[str, Any]] = [
    {
        "hostname": os.environ.get("SPINE1_HOST", "172.20.20.2"),
        "vendor": "juniper",
        "platform": "junos",
        "username": os.environ.get("DEVICE_USER", "admin"),
        "password": os.environ.get("DEVICE_PASS", "admin123"),
        "port": 830,
    },
    {
        "hostname": os.environ.get("LEAF1_HOST", "172.20.20.4"),
        "vendor": "juniper",
        "platform": "junos",
        "username": os.environ.get("DEVICE_USER", "admin"),
        "password": os.environ.get("DEVICE_PASS", "admin123"),
        "port": 830,
    },
]


@pytest.fixture
def factory() -> DriverFactory:
    """DriverFactory instance."""
    return DriverFactory()


@pytest.fixture(params=TOPOLOGY_HOSTS, ids=lambda h: h["hostname"])
def device_host(request: pytest.FixtureRequest) -> dict[str, Any]:
    """Parametrized fixture yielding each topology host."""
    return request.param


class TestDriverConnectivity:
    """Verify basic driver operations against live devices."""

    def test_connect_and_disconnect(
        self, factory: DriverFactory, device_host: dict[str, Any]
    ) -> None:
        driver = factory.create_from_dict(device_host)
        driver.connect()
        assert driver.is_connected
        driver.disconnect()
        assert not driver.is_connected

    def test_show_version(self, factory: DriverFactory, device_host: dict[str, Any]) -> None:
        driver = factory.create_from_dict(device_host)
        with driver:
            output = driver.execute_command("show version")
            assert len(output) > 0

    def test_get_bgp_neighbors(self, factory: DriverFactory, device_host: dict[str, Any]) -> None:
        driver = factory.create_from_dict(device_host)
        with driver:
            bgp = driver.get_bgp_neighbors()
            assert isinstance(bgp, dict)

    def test_get_interfaces(self, factory: DriverFactory, device_host: dict[str, Any]) -> None:
        driver = factory.create_from_dict(device_host)
        with driver:
            ifaces = driver.get_interfaces()
            assert isinstance(ifaces, dict)
            assert len(ifaces) > 0

    def test_take_snapshot(self, factory: DriverFactory, device_host: dict[str, Any]) -> None:
        driver = factory.create_from_dict(device_host)
        with driver:
            snapshot = driver.take_snapshot("integration-test")
            assert snapshot.device == device_host["hostname"]
            assert snapshot.snapshot_id == "integration-test"

    def test_health_check(self, factory: DriverFactory, device_host: dict[str, Any]) -> None:
        driver = factory.create_from_dict(device_host)
        with driver:
            report = driver.run_health_check()
            assert "overall_healthy" in report


class TestSnapshotWorkflow:
    """End-to-end snapshot capture and comparison."""

    def test_snapshot_diff_workflow(self, factory: DriverFactory) -> None:
        host = TOPOLOGY_HOSTS[0]
        driver = factory.create_from_dict(host)
        engine = SnapshotEngine()

        with driver:
            pre = engine.capture(driver, "pre-integration")
            post = engine.capture(driver, "post-integration")
            diff = engine.diff(pre, post)
            assert not diff.has_changes  # No change between snapshots


class TestValidationWorkflow:
    """End-to-end validation against live device state."""

    def test_full_validation(self, factory: DriverFactory) -> None:
        host = TOPOLOGY_HOSTS[0]
        driver = factory.create_from_dict(host)

        with driver:
            validator = StateValidator(device=host["hostname"])
            report = validator.run_full_validation(
                bgp_data=driver.get_bgp_neighbors(),
                interface_data=driver.get_interfaces(),
                routing_data=driver.get_routing_table(),
                lldp_data=driver.get_lldp_neighbors(),
                evpn_data=driver.get_evpn_routes(),
            )
            assert report.device == host["hostname"]
