"""L2/L3 topology verification using graph-based reachability analysis.

Builds a logical network graph from LLDP neighbor data and routing
tables, then verifies expected adjacencies, detects unidirectional
links, and checks overall graph connectivity.

Usage::

    verifier = TopologyVerifier()
    verifier.build_from_lldp(lldp_data_by_device)
    issues = verifier.verify_expected_links(expected_links)
    verifier.assert_fully_connected()
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from ..core.exceptions import TopologyError

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Link:
    """Representation of a network link between two devices.

    Attributes:
        local_device: Hostname of the local device.
        local_interface: Interface name on the local device.
        remote_device: Hostname of the remote device.
        remote_interface: Interface name on the remote device.

    """

    local_device: str
    local_interface: str
    remote_device: str
    remote_interface: str


@dataclass
class TopologyIssue:
    """A detected topology inconsistency.

    Attributes:
        issue_type: Category (e.g., ``missing_link``, ``unidirectional``).
        description: Human-readable explanation.
        affected_devices: Devices involved.
        severity: One of ``critical``, ``high``, ``medium``, ``low``.

    """

    issue_type: str
    description: str
    affected_devices: list[str] = field(default_factory=list)
    severity: str = "high"


class TopologyVerifier:
    """Graph-based L2/L3 topology verifier.

    Constructs an adjacency graph from live LLDP data and performs
    structural validation.  The graph is bidirectional — each LLDP
    entry produces a directed edge, and the verifier checks for
    symmetry.

    Args:
        strict: If ``True``, raise ``TopologyError`` on any issue;
            otherwise issues are collected silently.

    """

    def __init__(self, strict: bool = False) -> None:
        """Initialize the topology verifier with optional strict mode."""
        self._strict = strict
        self._adjacency: dict[str, dict[str, str]] = defaultdict(dict)
        self._links: list[Link] = []
        self._devices: set[str] = set()
        self._logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

    def build_from_lldp(
        self,
        lldp_by_device: dict[str, dict[str, Any]],
    ) -> None:
        """Build the topology graph from per-device LLDP neighbor data.

        Args:
            lldp_by_device: Mapping of device hostname to its LLDP
                neighbor table (as returned by ``get_lldp_neighbors()``).

        """
        self._adjacency.clear()
        self._links.clear()
        self._devices.clear()

        for device, neighbors in lldp_by_device.items():
            self._devices.add(device)
            for local_if, neighbor_info in neighbors.items():
                remote_device = neighbor_info.get("remote_system", "")
                remote_port = neighbor_info.get("remote_port", "")
                if not remote_device:
                    continue
                self._devices.add(remote_device)
                self._adjacency[device][local_if] = remote_device
                self._links.append(
                    Link(
                        local_device=device,
                        local_interface=local_if,
                        remote_device=remote_device,
                        remote_interface=remote_port,
                    )
                )

        self._logger.info(
            "Topology graph built: %d devices, %d links",
            len(self._devices),
            len(self._links),
        )

    def verify_expected_links(
        self,
        expected_links: list[tuple[str, str]],
    ) -> list[TopologyIssue]:
        """Check that expected device pairs are adjacent.

        Args:
            expected_links: List of ``(device_a, device_b)`` pairs that
                should be directly connected.

        Returns:
            List of issues for any missing links.

        """
        issues: list[TopologyIssue] = []
        for device_a, device_b in expected_links:
            a_to_b = device_b in self._adjacency.get(device_a, {}).values()
            b_to_a = device_a in self._adjacency.get(device_b, {}).values()

            if not a_to_b and not b_to_a:
                issue = TopologyIssue(
                    issue_type="missing_link",
                    description=(
                        f"Expected link between {device_a} and {device_b} not found in LLDP data"
                    ),
                    affected_devices=[device_a, device_b],
                    severity="critical",
                )
                issues.append(issue)
                self._logger.warning(issue.description)
            elif a_to_b != b_to_a:
                issue = TopologyIssue(
                    issue_type="unidirectional",
                    description=(
                        f"Unidirectional link between {device_a} and "
                        f"{device_b}: only visible from one side"
                    ),
                    affected_devices=[device_a, device_b],
                    severity="high",
                )
                issues.append(issue)
                self._logger.warning(issue.description)

        if self._strict and issues:
            raise TopologyError(
                f"Topology verification found {len(issues)} issue(s)",
                details={"issues": [i.description for i in issues]},
            )
        return issues

    def detect_unidirectional_links(self) -> list[TopologyIssue]:
        """Scan for links visible from only one direction.

        Returns:
            List of ``TopologyIssue`` for each unidirectional link.

        """
        issues: list[TopologyIssue] = []
        checked: set[tuple[str, str]] = set()

        for link in self._links:
            a, b = sorted([link.local_device, link.remote_device])
            pair = (a, b)
            if pair in checked:
                continue
            checked.add(pair)

            forward = link.remote_device in self._adjacency.get(link.local_device, {}).values()
            reverse = link.local_device in self._adjacency.get(link.remote_device, {}).values()

            if forward != reverse:
                issue = TopologyIssue(
                    issue_type="unidirectional",
                    description=(
                        f"Unidirectional LLDP between {link.local_device} and {link.remote_device}"
                    ),
                    affected_devices=[link.local_device, link.remote_device],
                    severity="high",
                )
                issues.append(issue)

        return issues

    def assert_fully_connected(self) -> TopologyIssue | None:
        """Verify the topology graph is fully connected (single component).

        Uses BFS to check that all devices are reachable from any
        starting node.

        Returns:
            ``None`` if fully connected; a ``TopologyIssue`` otherwise.

        Raises:
            TopologyError: In strict mode, if the graph is disconnected.

        """
        if not self._devices:
            return None

        undirected: dict[str, set[str]] = defaultdict(set)
        for link in self._links:
            undirected[link.local_device].add(link.remote_device)
            undirected[link.remote_device].add(link.local_device)

        start = next(iter(self._devices))
        visited: set[str] = set()
        queue: list[str] = [start]

        while queue:
            node = queue.pop(0)
            if node in visited:
                continue
            visited.add(node)
            for neighbor in undirected.get(node, set()):
                if neighbor not in visited:
                    queue.append(neighbor)

        unreachable = self._devices - visited
        if unreachable:
            issue = TopologyIssue(
                issue_type="disconnected",
                description=(
                    f"Topology graph is disconnected. Unreachable devices: "
                    f"{', '.join(sorted(unreachable))}"
                ),
                affected_devices=sorted(unreachable),
                severity="critical",
            )
            if self._strict:
                raise TopologyError(issue.description)
            return issue

        self._logger.info("Topology is fully connected (%d devices)", len(visited))
        return None

    @property
    def devices(self) -> set[str]:
        """Return the set of discovered device hostnames."""
        return set(self._devices)

    @property
    def links(self) -> list[Link]:
        """Return the list of discovered links."""
        return list(self._links)

    @property
    def link_count(self) -> int:
        """Return the total number of discovered links."""
        return len(self._links)
