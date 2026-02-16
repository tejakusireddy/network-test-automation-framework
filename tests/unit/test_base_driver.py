"""Unit tests for the BaseDriver abstract class and data models."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from src.core.base_driver import (
    BaseDriver,
    BgpState,
    DeviceInfo,
    DiffEntry,
    InterfaceState,
    Snapshot,
    SnapshotDiff,
)
from src.core.exceptions import ConnectionError, SnapshotError


# ---------------------------------------------------------------------------
# Concrete test implementation of BaseDriver
# ---------------------------------------------------------------------------


class StubDriver(BaseDriver):
    """Minimal concrete driver for testing abstract base class behavior."""

    def __init__(self, device_info: DeviceInfo) -> None:
        super().__init__(device_info)
        self._bgp: dict[str, Any] = {}
        self._interfaces: dict[str, Any] = {}
        self._routes: dict[str, Any] = {}
        self._lldp: dict[str, Any] = {}
        self._evpn: dict[str, Any] = {}

    def connect(self) -> None:
        self._connected = True

    def disconnect(self) -> None:
        self._connected = False

    def get_bgp_neighbors(self) -> dict[str, Any]:
        return self._bgp

    def get_interfaces(self) -> dict[str, Any]:
        return self._interfaces

    def get_routing_table(self) -> dict[str, Any]:
        return self._routes

    def get_lldp_neighbors(self) -> dict[str, Any]:
        return self._lldp

    def get_evpn_routes(self) -> dict[str, Any]:
        return self._evpn

    def push_config(self, config: str) -> bool:
        return True

    def execute_command(self, command: str) -> str:
        return f"output of: {command}"


# ---------------------------------------------------------------------------
# Tests: Data models
# ---------------------------------------------------------------------------


class TestDeviceInfo:
    """Tests for the DeviceInfo dataclass."""

    def test_creation(self, juniper_device_info: DeviceInfo) -> None:
        assert juniper_device_info.hostname == "spine1"
        assert juniper_device_info.vendor == "juniper"
        assert juniper_device_info.port == 830

    def test_immutability(self, juniper_device_info: DeviceInfo) -> None:
        with pytest.raises(AttributeError):
            juniper_device_info.hostname = "other"  # type: ignore[misc]


class TestSnapshot:
    """Tests for the Snapshot dataclass."""

    def test_json_roundtrip(self, pre_snapshot: Snapshot) -> None:
        json_str = pre_snapshot.to_json()
        restored = Snapshot.from_json(json_str)
        assert restored.snapshot_id == pre_snapshot.snapshot_id
        assert restored.device == pre_snapshot.device
        assert restored.bgp_neighbors == pre_snapshot.bgp_neighbors

    def test_json_contains_all_fields(self, pre_snapshot: Snapshot) -> None:
        data = json.loads(pre_snapshot.to_json())
        assert "snapshot_id" in data
        assert "device" in data
        assert "bgp_neighbors" in data
        assert "interfaces" in data
        assert "routing_table" in data
        assert "lldp_neighbors" in data
        assert "evpn_routes" in data


class TestSnapshotDiff:
    """Tests for the SnapshotDiff dataclass."""

    def test_has_changes_empty(self) -> None:
        diff = SnapshotDiff(pre_id="a", post_id="b", device="test")
        assert not diff.has_changes

    def test_has_changes_with_diffs(self) -> None:
        diff = SnapshotDiff(
            pre_id="a",
            post_id="b",
            device="test",
            diffs=[DiffEntry(category="bgp", key="10.0.0.1", action="changed")],
        )
        assert diff.has_changes

    def test_categorized_accessors(self) -> None:
        diff = SnapshotDiff(
            pre_id="a",
            post_id="b",
            device="test",
            diffs=[
                DiffEntry(category="bgp", key="10.0.0.1", action="added"),
                DiffEntry(category="bgp", key="10.0.0.2", action="removed"),
                DiffEntry(category="routes", key="10.0.0.0/24", action="changed"),
            ],
        )
        assert len(diff.added) == 1
        assert len(diff.removed) == 1
        assert len(diff.changed) == 1


# ---------------------------------------------------------------------------
# Tests: BaseDriver behavior
# ---------------------------------------------------------------------------


class TestBaseDriver:
    """Tests for concrete methods on the BaseDriver."""

    @pytest.fixture
    def driver(self, juniper_device_info: DeviceInfo) -> StubDriver:
        return StubDriver(juniper_device_info)

    def test_context_manager(self, driver: StubDriver) -> None:
        assert not driver.is_connected
        with driver:
            assert driver.is_connected
        assert not driver.is_connected

    def test_properties(self, driver: StubDriver) -> None:
        assert driver.hostname == "spine1"
        assert driver.vendor == "juniper"

    def test_take_snapshot(self, driver: StubDriver) -> None:
        driver._bgp = {"10.0.0.1": {"state": "established"}}
        driver._interfaces = {"et-0/0/0": {"oper_status": "up"}}
        driver.connect()
        snapshot = driver.take_snapshot("test-snap")
        assert snapshot.snapshot_id == "test-snap"
        assert snapshot.device == "spine1"
        assert "10.0.0.1" in snapshot.bgp_neighbors

    def test_compare_snapshots_no_changes(self, driver: StubDriver) -> None:
        snap = Snapshot(snapshot_id="a", device="spine1")
        diff = driver.compare_snapshots(snap, snap)
        assert not diff.has_changes

    def test_compare_snapshots_detects_changes(
        self, driver: StubDriver, pre_snapshot: Snapshot, post_snapshot: Snapshot
    ) -> None:
        diff = driver.compare_snapshots(pre_snapshot, post_snapshot)
        assert diff.has_changes
        assert any(d.key == "10.0.0.3" for d in diff.diffs)

    def test_validate_connectivity(self, driver: StubDriver) -> None:
        result = driver.validate_connectivity()
        assert result is True

    def test_run_health_check_healthy(self, driver: StubDriver) -> None:
        driver._bgp = {"10.0.0.1": {"state": "established"}}
        driver._interfaces = {"et-0/0/0": {"oper_status": "up"}}
        driver._lldp = {"et-0/0/0": {"remote_system": "spine2"}}
        driver.connect()
        report = driver.run_health_check()
        assert report["overall_healthy"] is True

    def test_run_health_check_unhealthy_bgp(self, driver: StubDriver) -> None:
        driver._bgp = {"10.0.0.1": {"state": "active"}}
        driver._interfaces = {"et-0/0/0": {"oper_status": "up"}}
        driver._lldp = {"et-0/0/0": {"remote_system": "spine2"}}
        driver.connect()
        report = driver.run_health_check()
        assert report["bgp"]["healthy"] is False


class TestBgpState:
    """Tests for the BgpState enum."""

    def test_values(self) -> None:
        assert BgpState.ESTABLISHED.value == "established"
        assert BgpState.IDLE.value == "idle"

    def test_membership(self) -> None:
        assert "established" in [s.value for s in BgpState]


class TestInterfaceState:
    """Tests for the InterfaceState enum."""

    def test_values(self) -> None:
        assert InterfaceState.UP.value == "up"
        assert InterfaceState.ADMIN_DOWN.value == "admin-down"
