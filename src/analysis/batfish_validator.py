"""Offline configuration analysis using Batfish.

Provides a high-level interface to the Batfish network analysis service
for routing table verification, traceroute simulation, ACL reachability,
and routing loop detection — all without touching live devices.

Requires:
    - pybatfish
    - A running Batfish service (docker-compose)

Usage::

    bf = BatfishValidator(host="localhost")
    bf.init_snapshot("my-network", configs_dir=Path("topology/configs"))
    routes = bf.get_routing_table("spine1")
    trace = bf.traceroute("spine1", dst_ip="10.0.0.1")
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from ..core.exceptions import ValidationError

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)

BATFISH_DEFAULT_HOST = "localhost"
BATFISH_DEFAULT_PORT = 9997


class BatfishValidator:
    """Offline network validation via Batfish.

    Connects to a running Batfish service, uploads device configurations
    as a snapshot, and runs analysis queries against the model.

    Args:
        host: Batfish service hostname.
        port: Batfish service port (default 9997 for pybatfish v2).

    """

    def __init__(
        self,
        host: str = BATFISH_DEFAULT_HOST,
        port: int = BATFISH_DEFAULT_PORT,
    ) -> None:
        """Initialize the Batfish validator with service connection settings."""
        self._host = host
        self._port = port
        self._session: Any = None
        self._network: str = ""
        self._snapshot: str = ""
        self._logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

    def connect(self) -> None:
        """Establish a session with the Batfish service.

        Raises:
            ValidationError: If pybatfish is not installed or the
                service is unreachable.

        """
        try:
            from pybatfish.client.session import Session  # type: ignore[import-untyped]

            self._session = Session(host=self._host)
            self._logger.info("Connected to Batfish at %s:%d", self._host, self._port)
        except ImportError:
            raise ValidationError("pybatfish is not installed") from None
        except Exception as exc:
            raise ValidationError(
                f"Cannot connect to Batfish: {exc}",
                details={"host": self._host, "port": self._port},
            ) from exc

    def init_snapshot(
        self,
        network_name: str,
        configs_dir: Path,
        snapshot_name: str = "snapshot",
        overwrite: bool = True,
    ) -> None:
        """Upload device configs and initialize a Batfish snapshot.

        Args:
            network_name: Logical network name within Batfish.
            configs_dir: Directory containing vendor config files.
            snapshot_name: Name for this snapshot.
            overwrite: Whether to overwrite an existing snapshot.

        Raises:
            ValidationError: If snapshot initialization fails.

        """
        if self._session is None:
            self.connect()

        try:

            self._network = network_name
            self._snapshot = snapshot_name
            self._session.set_network(network_name)
            self._session.init_snapshot(
                str(configs_dir),
                name=snapshot_name,
                overwrite=overwrite,
            )
            self._logger.info(
                "Initialized snapshot '%s' in network '%s' from %s",
                snapshot_name,
                network_name,
                configs_dir,
            )
        except Exception as exc:
            raise ValidationError(
                f"Snapshot initialization failed: {exc}",
                details={"configs_dir": str(configs_dir)},
            ) from exc

    def get_routing_table(
        self,
        node: str,
        vrf: str = "default",
    ) -> list[dict[str, Any]]:
        """Query the modeled routing table for a specific node.

        Args:
            node: Device hostname in the Batfish model.
            vrf: VRF name to query.

        Returns:
            List of route entries with prefix, next-hop, protocol, etc.

        """
        self._ensure_snapshot()
        try:
            from pybatfish.question.bfq import bfq  # type: ignore[import-untyped]

            result = bfq.routes(nodes=node, vrfs=vrf).answer()
            routes = result.frame().to_dict(orient="records")
            self._logger.debug("Batfish returned %d routes for %s", len(routes), node)
            return routes
        except Exception as exc:
            self._logger.error("Routing table query failed: %s", exc)
            raise ValidationError(
                f"Routing table query failed for {node}: {exc}"
            ) from exc

    def traceroute(
        self,
        src_node: str,
        dst_ip: str,
        src_ip: str | None = None,
    ) -> list[dict[str, Any]]:
        """Simulate a traceroute through the modeled network.

        Args:
            src_node: Source device hostname.
            dst_ip: Destination IP address.
            src_ip: Optional source IP (uses device loopback by default).

        Returns:
            List of hop entries along the simulated path.

        """
        self._ensure_snapshot()
        try:
            from pybatfish.datamodel.flow import HeaderConstraints  # type: ignore[import-untyped]
            from pybatfish.question.bfq import bfq  # type: ignore[import-untyped]

            headers = HeaderConstraints(dstIps=dst_ip)
            if src_ip:
                headers = HeaderConstraints(srcIps=src_ip, dstIps=dst_ip)

            result = bfq.traceroute(
                startLocation=src_node,
                headers=headers,
            ).answer()
            traces = result.frame().to_dict(orient="records")
            self._logger.debug(
                "Traceroute from %s to %s: %d traces", src_node, dst_ip, len(traces)
            )
            return traces
        except Exception as exc:
            self._logger.error("Traceroute query failed: %s", exc)
            raise ValidationError(
                f"Traceroute failed from {src_node} to {dst_ip}: {exc}"
            ) from exc

    def check_acl_reachability(
        self,
        node: str | None = None,
    ) -> list[dict[str, Any]]:
        """Detect unreachable ACL lines (shadowed rules).

        Args:
            node: Optional node filter; checks all nodes if omitted.

        Returns:
            List of unreachable ACL line entries.

        """
        self._ensure_snapshot()
        try:
            from pybatfish.question.bfq import bfq  # type: ignore[import-untyped]

            kwargs: dict[str, Any] = {}
            if node:
                kwargs["nodes"] = node

            result = bfq.filterLineReachability(**kwargs).answer()
            lines = result.frame().to_dict(orient="records")
            self._logger.info("Found %d unreachable ACL lines", len(lines))
            return lines
        except Exception as exc:
            self._logger.error("ACL reachability check failed: %s", exc)
            raise ValidationError(
                f"ACL reachability check failed: {exc}"
            ) from exc

    def detect_routing_loops(self) -> list[dict[str, Any]]:
        """Detect forwarding loops in the modeled network.

        Returns:
            List of detected loop entries with path information.

        """
        self._ensure_snapshot()
        try:
            from pybatfish.question.bfq import bfq  # type: ignore[import-untyped]

            result = bfq.detectLoops().answer()
            loops = result.frame().to_dict(orient="records")
            if loops:
                self._logger.warning("Detected %d routing loops!", len(loops))
            else:
                self._logger.info("No routing loops detected")
            return loops
        except Exception as exc:
            self._logger.error("Loop detection failed: %s", exc)
            raise ValidationError(
                f"Routing loop detection failed: {exc}"
            ) from exc

    def verify_bgp_sessions(
        self,
        node: str | None = None,
    ) -> list[dict[str, Any]]:
        """Verify that all configured BGP sessions can establish.

        Args:
            node: Optional node filter.

        Returns:
            List of BGP session status entries.

        """
        self._ensure_snapshot()
        try:
            from pybatfish.question.bfq import bfq  # type: ignore[import-untyped]

            kwargs: dict[str, Any] = {}
            if node:
                kwargs["nodes"] = node

            result = bfq.bgpSessionStatus(**kwargs).answer()
            sessions = result.frame().to_dict(orient="records")
            self._logger.debug("BGP session check: %d entries", len(sessions))
            return sessions
        except Exception as exc:
            self._logger.error("BGP session verification failed: %s", exc)
            raise ValidationError(
                f"BGP session verification failed: {exc}"
            ) from exc

    def compare_routing_tables(
        self,
        node: str,
        snapshot_a: str,
        snapshot_b: str,
    ) -> list[dict[str, Any]]:
        """Compare routing tables between two Batfish snapshots.

        Args:
            node: Device hostname.
            snapshot_a: Name of the reference snapshot.
            snapshot_b: Name of the comparison snapshot.

        Returns:
            List of route differences.

        """
        self._ensure_snapshot()
        try:
            from pybatfish.question.bfq import bfq  # type: ignore[import-untyped]

            result = bfq.routes(
                nodes=node,
                snapshot=snapshot_a,
                reference_snapshot=snapshot_b,
            ).answer()
            diffs = result.frame().to_dict(orient="records")
            self._logger.info("Route diffs for %s: %d entries", node, len(diffs))
            return diffs
        except Exception as exc:
            self._logger.error("Route comparison failed: %s", exc)
            raise ValidationError(
                f"Route comparison failed for {node}: {exc}"
            ) from exc

    # -- Internal helpers ---------------------------------------------------

    def _ensure_snapshot(self) -> None:
        """Raise if no snapshot has been initialized."""
        if self._session is None:
            raise ValidationError(
                "Not connected to Batfish — call connect() first"
            )
        if not self._snapshot:
            raise ValidationError(
                "No snapshot initialized — call init_snapshot() first"
            )
