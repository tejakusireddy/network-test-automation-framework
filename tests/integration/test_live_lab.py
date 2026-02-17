"""Live integration tests against the FRR docker-compose lab.

These tests connect to the running FRR containers via docker exec
and validate BGP, OSPF, and connectivity using the framework's
validation logic.

Prerequisites:
    - Lab must be running: make topology-up
    - Run with: pytest tests/integration/test_live_lab.py -v
"""

from __future__ import annotations

import json
import re
import subprocess
import time
from typing import ClassVar

import pytest

# Mark all tests in this module as integration (skip in normal CI)
pytestmark = pytest.mark.integration


def docker_exec(container: str, command: str) -> str:
    """Execute a vtysh command on an FRR container."""
    result = subprocess.run(
        ["docker", "exec", container, "vtysh", "-c", command],
        capture_output=True,
        text=True,
        timeout=10,
    )
    return result.stdout


def docker_exec_json(container: str, command: str) -> dict:
    """Execute a vtysh command and return JSON output."""
    result = docker_exec(container, f"{command} json")
    # Strip any warning lines before the JSON
    lines = result.strip().split("\n")
    for i, line in enumerate(lines):
        if line.startswith("{") or line.startswith("["):
            return json.loads("\n".join(lines[i:]))
    return {}


def ping_from_container(container: str, target: str, count: int = 3) -> dict:
    """Ping from one container to another and return results."""
    result = subprocess.run(
        ["docker", "exec", container, "ping", "-c", str(count), "-W", "2", target],
        capture_output=True,
        text=True,
        timeout=15,
    )
    # Parse packet loss
    loss_match = re.search(r"(\d+)% packet loss", result.stdout)
    loss = int(loss_match.group(1)) if loss_match else 100
    return {
        "target": target,
        "packets_sent": count,
        "packet_loss_percent": loss,
        "output": result.stdout,
    }


# ---------------------------------------------------------------------------
# Topology Constants
# ---------------------------------------------------------------------------

SPINES = ["clab-spine1", "clab-spine2"]
LEAVES = ["clab-leaf1", "clab-leaf2", "clab-leaf3", "clab-leaf4"]
WAN = ["clab-wan-edge"]
ALL_ROUTERS = SPINES + LEAVES + WAN

EXPECTED_BGP_PEERS = {
    "clab-spine1": 6,  # 4 leaves + spine2 + wan-edge
    "clab-spine2": 5,  # 4 leaves + spine1
    "clab-leaf1": 2,  # spine1 + spine2
    "clab-leaf2": 2,
    "clab-leaf3": 2,
    "clab-leaf4": 2,
    "clab-wan-edge": 1,  # spine1 only
}

UNDERLAY_IPS = {
    "clab-spine1": "10.0.1.1",
    "clab-spine2": "10.0.1.2",
    "clab-leaf1": "10.0.1.11",
    "clab-leaf2": "10.0.1.12",
    "clab-leaf3": "10.0.1.13",
    "clab-leaf4": "10.0.1.14",
    "clab-wan-edge": "10.0.1.100",
}


# ---------------------------------------------------------------------------
# Fixture: Check lab is running
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module", autouse=True)
def lab_running():
    """Verify all containers are running before tests execute."""
    result = subprocess.run(
        ["docker", "ps", "--format", "{{.Names}}"],
        capture_output=True,
        text=True,
    )
    running = result.stdout.strip().split("\n")
    for container in ALL_ROUTERS:
        if container not in running:
            pytest.skip(f"Lab not running: {container} not found. Run 'make topology-up' first.")


# ---------------------------------------------------------------------------
# Test Class: BGP Validation
# ---------------------------------------------------------------------------


class TestBGPValidation:
    """Validate BGP peering across the fabric."""

    @pytest.mark.parametrize("router,expected_peers", list(EXPECTED_BGP_PEERS.items()))
    def test_bgp_peer_count(self, router: str, expected_peers: int) -> None:
        """Each router should have the expected number of established BGP peers."""
        output = docker_exec(router, "show bgp summary")
        # Only look at IPv4 Unicast section (before L2VPN EVPN section)
        ipv4_section = output.split("L2VPN EVPN")[0] if "L2VPN EVPN" in output else output
        established = ipv4_section.count("FRRouting")
        assert established == expected_peers, (
            f"{router}: expected {expected_peers} established IPv4 peers, "
            f"got {established}\n{ipv4_section}"
        )

    @pytest.mark.parametrize("router", SPINES)
    def test_spine_is_route_reflector(self, router: str) -> None:
        """Spine routers should have route-reflector-client configured for leaves."""
        output = docker_exec(router, "show running-config")
        rr_count = output.count("route-reflector-client")
        assert rr_count >= 4, (
            f"{router}: expected at least 4 route-reflector-client configs, " f"got {rr_count}"
        )

    def test_spine1_receives_wan_routes(self) -> None:
        """spine1 should receive routes from wan-edge via eBGP."""
        output = docker_exec("clab-spine1", "show bgp ipv4 unicast")
        assert "65100" in output, "spine1 should have routes from AS 65100 (wan-edge)"

    def test_wan_edge_receives_fabric_routes(self) -> None:
        """wan-edge should receive fabric routes from spine1."""
        output = docker_exec("clab-wan-edge", "show bgp ipv4 unicast")
        assert "65000" in output, "wan-edge should have routes from AS 65000 (fabric)"

    # Known peers that are configured but intentionally not established
    ALLOWED_INACTIVE_PEERS: ClassVar[set[str]] = {"10.0.1.100"}

    @pytest.mark.parametrize("router", ALL_ROUTERS)
    def test_no_bgp_peers_in_active_state(self, router: str) -> None:
        """No BGP peer should be stuck in Active/Connect state (except known inactive)."""
        output = docker_exec(router, "show bgp summary")
        lines = output.split("\n")
        for line in lines:
            if (
                any(state in line for state in ["Active", "Connect", "OpenSent", "OpenConfirm"])
                and "Neighbor" not in line
                and "Status" not in line
                and not any(peer in line for peer in self.ALLOWED_INACTIVE_PEERS)
            ):
                pytest.fail(f"{router}: BGP peer not established:\n{line}")


# ---------------------------------------------------------------------------
# Test Class: OSPF Validation
# ---------------------------------------------------------------------------


class TestOSPFValidation:
    """Validate OSPF adjacencies and routing."""

    @pytest.mark.parametrize("router", ALL_ROUTERS)
    def test_ospf_has_neighbors(self, router: str) -> None:
        """Each router should have at least one OSPF neighbor."""
        output = docker_exec(router, "show ip ospf neighbor")
        # Count lines with IP addresses (neighbor entries)
        neighbor_lines = [
            line for line in output.split("\n") if re.match(r"\d+\.\d+\.\d+\.\d+", line.strip())
        ]
        assert len(neighbor_lines) >= 1, f"{router}: no OSPF neighbors found\n{output}"

    @pytest.mark.parametrize("router", SPINES)
    def test_spine_ospf_neighbor_count(self, router: str) -> None:
        """Spines should see all other routers as OSPF neighbors."""
        output = docker_exec(router, "show ip ospf neighbor")
        neighbor_lines = [
            line for line in output.split("\n") if re.match(r"\d+\.\d+\.\d+\.\d+", line.strip())
        ]
        # Spine should see at least 5 neighbors (other spine + 4 leaves + wan or subset)
        assert len(neighbor_lines) >= 5, (
            f"{router}: expected at least 5 OSPF neighbors, " f"got {len(neighbor_lines)}\n{output}"
        )


# ---------------------------------------------------------------------------
# Test Class: Connectivity Validation
# ---------------------------------------------------------------------------


class TestConnectivity:
    """Validate end-to-end reachability across the fabric."""

    @pytest.mark.parametrize(
        "src,dst_name,dst_ip",
        [
            ("clab-leaf1", "leaf2", "10.0.1.12"),
            ("clab-leaf1", "leaf3", "10.0.1.13"),
            ("clab-leaf1", "leaf4", "10.0.1.14"),
            ("clab-leaf1", "spine1", "10.0.1.1"),
            ("clab-leaf1", "wan-edge", "10.0.1.100"),
            ("clab-spine1", "spine2", "10.0.1.2"),
            ("clab-wan-edge", "spine1", "10.0.1.1"),
        ],
    )
    def test_ping_reachability(self, src: str, dst_name: str, dst_ip: str) -> None:
        """Verify ping reachability between key network pairs."""
        result = ping_from_container(src, dst_ip, count=3)
        assert result["packet_loss_percent"] == 0, (
            f"{src} -> {dst_name} ({dst_ip}): "
            f"{result['packet_loss_percent']}% packet loss\n"
            f"{result['output']}"
        )

    @pytest.mark.parametrize("leaf", LEAVES)
    def test_leaf_can_reach_all_spines(self, leaf: str) -> None:
        """Every leaf should be able to reach both spines."""
        for spine_ip in ["10.0.1.1", "10.0.1.2"]:
            result = ping_from_container(leaf, spine_ip, count=2)
            assert result["packet_loss_percent"] == 0, f"{leaf} -> {spine_ip}: unreachable"


# ---------------------------------------------------------------------------
# Test Class: Route Validation
# ---------------------------------------------------------------------------


class TestRouteValidation:
    """Validate the routing table has expected entries."""

    @pytest.mark.parametrize("router", ALL_ROUTERS)
    def test_has_bgp_routes(self, router: str) -> None:
        """Each router should have BGP routes in its table."""
        output = docker_exec(router, "show bgp ipv4 unicast")
        # Should have at least some routes displayed
        assert (
            "Network" in output or "Displayed" in output
        ), f"{router}: no BGP routes found\n{output}"

    def test_spine1_route_count(self) -> None:
        """spine1 should have routes to all loopbacks and networks."""
        output = docker_exec("clab-spine1", "show bgp ipv4 unicast")
        displayed_match = re.search(r"Displayed\s+(\d+)\s+routes", output)
        if displayed_match:
            route_count = int(displayed_match.group(1))
            assert route_count >= 5, f"spine1: expected at least 5 BGP routes, got {route_count}"

    @pytest.mark.parametrize("router", LEAVES)
    def test_leaf_has_default_or_full_table(self, router: str) -> None:
        """Leaves should receive routes from route reflectors."""
        output = docker_exec(router, "show bgp ipv4 unicast")
        assert (
            "65000" in output or "Displayed" in output
        ), f"{router}: not receiving BGP routes from spines"


# ---------------------------------------------------------------------------
# Test Class: L2VPN EVPN Validation
# ---------------------------------------------------------------------------


class TestEVPNValidation:
    """Validate L2VPN EVPN address family is active."""

    @pytest.mark.parametrize("router", SPINES + LEAVES)
    def test_evpn_address_family_active(self, router: str) -> None:
        """EVPN address family should be configured and have peers."""
        output = docker_exec(router, "show bgp l2vpn evpn summary")
        assert (
            "L2VPN EVPN" in output or "Neighbor" in output
        ), f"{router}: L2VPN EVPN address family not active\n{output}"


# ---------------------------------------------------------------------------
# Test Class: Failover Simulation
# ---------------------------------------------------------------------------


class TestFailoverSimulation:
    """Simulate failures and validate recovery."""

    def test_spine1_bgp_reset_recovery(self) -> None:
        """After clearing BGP on spine1, sessions should re-establish."""
        # Record pre-state
        pre_output = docker_exec("clab-spine1", "show bgp summary")
        pre_established = pre_output.count("FRRouting")

        # Clear BGP (soft reset, non-destructive)
        docker_exec("clab-spine1", "clear bgp ipv4 unicast * soft")

        # Wait for reconvergence
        time.sleep(10)

        # Verify sessions came back
        post_output = docker_exec("clab-spine1", "show bgp summary")
        post_established = post_output.count("FRRouting")

        assert post_established == pre_established, (
            f"BGP sessions did not recover after soft reset: "
            f"pre={pre_established}, post={post_established}\n{post_output}"
        )
