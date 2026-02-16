"""Shared pytest fixtures for the network test automation framework.

Provides reusable fixtures for device info, mock drivers, sample
snapshots, and BGP/interface/route data used across the test suite.
"""

from __future__ import annotations

from typing import Any

import pytest
from src.core.base_driver import (
    DeviceInfo,
    Snapshot,
)
from src.core.validator import StateValidator

# ---------------------------------------------------------------------------
# Device info fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def juniper_device_info() -> DeviceInfo:
    """DeviceInfo for a Juniper spine switch."""
    return DeviceInfo(
        hostname="spine1",
        vendor="juniper",
        platform="junos",
        username="admin",
        password="admin123",
        port=830,
        timeout=30,
    )


@pytest.fixture
def cisco_device_info() -> DeviceInfo:
    """DeviceInfo for a Cisco WAN router."""
    return DeviceInfo(
        hostname="wan-router",
        vendor="cisco",
        platform="iosxe",
        username="admin",
        password="admin123",
        port=22,
        timeout=30,
    )


@pytest.fixture
def arista_device_info() -> DeviceInfo:
    """DeviceInfo for an Arista leaf switch."""
    return DeviceInfo(
        hostname="leaf1",
        vendor="arista",
        platform="eos",
        username="admin",
        password="admin123",
        port=443,
        timeout=30,
    )


# ---------------------------------------------------------------------------
# Sample data fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_bgp_data() -> dict[str, Any]:
    """Sample BGP neighbor table with mixed states."""
    return {
        "10.0.0.1": {
            "peer_address": "10.0.0.1",
            "state": "established",
            "peer_as": "65000",
            "local_as": "65000",
            "input_messages": 1500,
            "output_messages": 1480,
            "flap_count": 0,
        },
        "10.0.0.2": {
            "peer_address": "10.0.0.2",
            "state": "established",
            "peer_as": "65000",
            "local_as": "65000",
            "input_messages": 1200,
            "output_messages": 1190,
            "flap_count": 0,
        },
        "10.0.0.3": {
            "peer_address": "10.0.0.3",
            "state": "active",
            "peer_as": "65001",
            "local_as": "65000",
            "input_messages": 0,
            "output_messages": 50,
            "flap_count": 3,
        },
    }


@pytest.fixture
def sample_interface_data() -> dict[str, Any]:
    """Sample interface table with various states."""
    return {
        "et-0/0/0": {
            "name": "et-0/0/0",
            "admin_status": "up",
            "oper_status": "up",
            "description": "to-spine2",
            "speed": "100G",
            "mtu": "9216",
            "input_errors": 0,
            "output_errors": 0,
        },
        "et-0/0/1": {
            "name": "et-0/0/1",
            "admin_status": "up",
            "oper_status": "up",
            "description": "to-leaf1",
            "speed": "100G",
            "mtu": "9216",
            "input_errors": 0,
            "output_errors": 0,
        },
        "et-0/0/2": {
            "name": "et-0/0/2",
            "admin_status": "up",
            "oper_status": "down",
            "description": "to-leaf2",
            "speed": "100G",
            "mtu": "9216",
            "input_errors": 5,
            "output_errors": 2,
        },
        "lo0": {
            "name": "lo0",
            "admin_status": "up",
            "oper_status": "up",
            "description": "Loopback",
            "speed": "0",
            "mtu": "65535",
            "input_errors": 0,
            "output_errors": 0,
        },
    }


@pytest.fixture
def sample_routing_data() -> dict[str, Any]:
    """Sample routing table."""
    return {
        "10.0.0.0/24": {
            "prefix": "10.0.0.0/24",
            "protocol": "ospf",
            "next_hop": "10.0.0.1",
            "preference": 10,
            "metric": 100,
        },
        "10.1.0.0/24": {
            "prefix": "10.1.0.0/24",
            "protocol": "bgp",
            "next_hop": "10.0.0.2",
            "preference": 170,
            "metric": 0,
        },
        "192.168.1.0/24": {
            "prefix": "192.168.1.0/24",
            "protocol": "static",
            "next_hop": "10.0.0.254",
            "preference": 5,
            "metric": 0,
        },
    }


@pytest.fixture
def sample_lldp_data() -> dict[str, Any]:
    """Sample LLDP neighbor table."""
    return {
        "et-0/0/0": {
            "local_interface": "et-0/0/0",
            "remote_system": "spine2",
            "remote_port": "et-0/0/0",
        },
        "et-0/0/1": {
            "local_interface": "et-0/0/1",
            "remote_system": "leaf1",
            "remote_port": "et-0/0/48",
        },
    }


@pytest.fixture
def sample_evpn_data() -> dict[str, Any]:
    """Sample EVPN route table."""
    return {
        "2:10.0.0.1:1::100::aa:bb:cc:dd:ee:ff": {
            "route_type": 2,
            "prefix": "2:10.0.0.1:1::100::aa:bb:cc:dd:ee:ff",
            "protocol": "bgp",
            "next_hop": "10.0.0.1",
        },
        "5:10.0.0.1:1::192.168.1.0/24": {
            "route_type": 5,
            "prefix": "5:10.0.0.1:1::192.168.1.0/24",
            "protocol": "bgp",
            "next_hop": "10.0.0.1",
        },
    }


# ---------------------------------------------------------------------------
# Snapshot fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def pre_snapshot(
    sample_bgp_data: dict[str, Any],
    sample_interface_data: dict[str, Any],
    sample_routing_data: dict[str, Any],
    sample_lldp_data: dict[str, Any],
    sample_evpn_data: dict[str, Any],
) -> Snapshot:
    """A pre-change snapshot with sample data."""
    return Snapshot(
        snapshot_id="pre-change",
        device="spine1",
        bgp_neighbors=sample_bgp_data,
        interfaces=sample_interface_data,
        routing_table=sample_routing_data,
        lldp_neighbors=sample_lldp_data,
        evpn_routes=sample_evpn_data,
    )


@pytest.fixture
def post_snapshot(
    sample_bgp_data: dict[str, Any],
    sample_interface_data: dict[str, Any],
    sample_routing_data: dict[str, Any],
    sample_lldp_data: dict[str, Any],
    sample_evpn_data: dict[str, Any],
) -> Snapshot:
    """A post-change snapshot with a modified BGP neighbor."""
    modified_bgp = dict(sample_bgp_data)
    modified_bgp["10.0.0.3"] = {
        **modified_bgp["10.0.0.3"],
        "state": "established",
        "flap_count": 3,
    }
    return Snapshot(
        snapshot_id="post-change",
        device="spine1",
        bgp_neighbors=modified_bgp,
        interfaces=sample_interface_data,
        routing_table=sample_routing_data,
        lldp_neighbors=sample_lldp_data,
        evpn_routes=sample_evpn_data,
    )


# ---------------------------------------------------------------------------
# Validator fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def validator() -> StateValidator:
    """A StateValidator instance for spine1."""
    return StateValidator(device="spine1")


# ---------------------------------------------------------------------------
# Pytest configuration
# ---------------------------------------------------------------------------


def pytest_configure(config: pytest.Config) -> None:
    """Register custom markers."""
    config.addinivalue_line("markers", "integration: mark test as integration test")
    config.addinivalue_line("markers", "slow: mark test as slow-running")
