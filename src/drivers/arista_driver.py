"""Arista Networks device driver using pyeapi and NAPALM.

Implements ``BaseDriver`` for Arista EOS devices.  Primary access is
via the eAPI JSON-RPC interface (pyeapi) for Arista-specific commands,
with NAPALM as a secondary provider for standardized getters.

Requires:
    - pyeapi
    - napalm

Usage::

    info = DeviceInfo(hostname="leaf1", vendor="arista", platform="eos", ...)
    with AristaDriver(info) as drv:
        bgp = drv.get_bgp_neighbors()
"""

from __future__ import annotations

import logging
from typing import Any

from ..core.base_driver import BaseDriver, DeviceInfo
from ..core.exceptions import (
    CommandExecutionError,
    ConfigPushError,
    ConnectionError,
)

logger = logging.getLogger(__name__)

EAPI_DEFAULT_PORT = 443
EAPI_HTTP_PORT = 80


class AristaDriver(BaseDriver):
    """Arista EOS driver using pyeapi + NAPALM.

    Uses the eAPI JSON-RPC interface for native EOS commands and NAPALM
    for standardized cross-vendor getters.

    Args:
        device_info: Connection parameters for the Arista device.

    """

    def __init__(self, device_info: DeviceInfo) -> None:
        """Initialize the Arista driver with device connection parameters."""
        super().__init__(device_info)
        self._eapi_node: Any = None
        self._napalm_driver: Any = None

    # -- Connection lifecycle -----------------------------------------------

    def connect(self) -> None:
        """Open eAPI and NAPALM sessions to the Arista device.

        Raises:
            ConnectionError: If the session cannot be established.

        """
        self._connect_eapi()
        self._connect_napalm()
        self._connected = True
        self._logger.info("Connected to %s (Arista EOS)", self.hostname)

    def disconnect(self) -> None:
        """Close connections.  Idempotent."""
        if self._napalm_driver is not None:
            try:
                self._napalm_driver.close()
            except Exception:
                self._logger.debug("Error closing NAPALM session", exc_info=True)
            finally:
                self._napalm_driver = None

        self._eapi_node = None
        self._connected = False
        self._logger.info("Disconnected from %s", self.hostname)

    # -- Data collection ----------------------------------------------------

    def get_bgp_neighbors(self) -> dict[str, Any]:
        """Retrieve BGP neighbors via eAPI ``show ip bgp summary``.

        Returns:
            Mapping of peer address to session details.

        """
        self._ensure_connected()
        result = self._eapi_command("show ip bgp summary")
        neighbors: dict[str, Any] = {}

        vrfs = result.get("vrfs", {"default": result})
        for vrf_name, vrf_data in vrfs.items():
            peers = vrf_data.get("peers", {})
            for peer_addr, peer_info in peers.items():
                state = peer_info.get("peerState", "unknown")
                neighbors[peer_addr] = {
                    "peer_address": peer_addr,
                    "state": (
                        state.lower()
                        if isinstance(state, str)
                        else "established" if isinstance(state, int) and state > 0 else "unknown"
                    ),
                    "peer_as": peer_info.get("asn"),
                    "prefixes_received": peer_info.get("prefixReceived", 0),
                    "prefixes_accepted": peer_info.get("prefixAccepted", 0),
                    "uptime_seconds": peer_info.get("upDownTime", 0),
                    "msg_rcvd": peer_info.get("msgReceived", 0),
                    "msg_sent": peer_info.get("msgSent", 0),
                    "description": peer_info.get("description", ""),
                    "vrf": vrf_name,
                }

        self._logger.debug("Retrieved %d BGP neighbors", len(neighbors))
        return neighbors

    def get_interfaces(self) -> dict[str, Any]:
        """Retrieve interface details via eAPI ``show interfaces``.

        Returns:
            Mapping of interface name to operational details.

        """
        self._ensure_connected()
        result = self._eapi_command("show interfaces")
        interfaces: dict[str, Any] = {}

        for name, info in result.get("interfaces", {}).items():
            counters = info.get("interfaceCounters", {})
            interfaces[name] = {
                "name": name,
                "admin_status": info.get("interfaceStatus", "unknown").lower(),
                "oper_status": ("up" if info.get("lineProtocolStatus", "") == "up" else "down"),
                "description": info.get("description", ""),
                "speed": info.get("bandwidth", 0),
                "mtu": info.get("mtu", 0),
                "mac_address": info.get("physicalAddress", ""),
                "input_errors": counters.get("inputErrors", 0),
                "output_errors": counters.get("outputErrors", 0),
                "input_rate": counters.get("inBitsRate", 0),
                "output_rate": counters.get("outBitsRate", 0),
            }

        self._logger.debug("Retrieved %d interfaces", len(interfaces))
        return interfaces

    def get_routing_table(self) -> dict[str, Any]:
        """Retrieve IP routing table via eAPI ``show ip route``.

        Returns:
            Mapping of prefix to route details.

        """
        self._ensure_connected()
        result = self._eapi_command("show ip route")
        routes: dict[str, Any] = {}

        vrfs = result.get("vrfs", {"default": result})
        for _vrf_name, vrf_data in vrfs.items():
            for prefix, route_info in vrf_data.get("routes", {}).items():
                via_list = route_info.get("vias", [])
                next_hop = via_list[0].get("nexthopAddr", "") if via_list else ""
                next_hop_if = via_list[0].get("interface", "") if via_list else ""
                routes[prefix] = {
                    "prefix": prefix,
                    "protocol": route_info.get("routeType", ""),
                    "next_hop": next_hop or next_hop_if,
                    "preference": route_info.get("preference", 0),
                    "metric": route_info.get("metric", 0),
                    "directly_connected": route_info.get("directlyConnected", False),
                }

        self._logger.debug("Retrieved %d routes", len(routes))
        return routes

    def get_lldp_neighbors(self) -> dict[str, Any]:
        """Retrieve LLDP neighbors via eAPI ``show lldp neighbors detail``.

        Returns:
            Mapping of local interface to neighbor details.

        """
        self._ensure_connected()
        result = self._eapi_command("show lldp neighbors detail")
        neighbors: dict[str, Any] = {}

        for local_if, neighbor_list in result.get("lldpNeighbors", {}).items():
            if neighbor_list:
                n = neighbor_list[0] if isinstance(neighbor_list, list) else neighbor_list
                neighbors[local_if] = {
                    "local_interface": local_if,
                    "remote_system": n.get("neighborDevice", ""),
                    "remote_port": n.get("neighborPort", ""),
                    "remote_port_description": n.get("neighborPortDescription", ""),
                    "remote_chassis_id": n.get("chassisId", ""),
                }

        self._logger.debug("Retrieved %d LLDP neighbors", len(neighbors))
        return neighbors

    def get_evpn_routes(self) -> dict[str, Any]:
        """Retrieve EVPN routes via eAPI ``show bgp evpn``.

        Returns:
            Mapping of route key to EVPN route details.

        """
        self._ensure_connected()
        routes: dict[str, Any] = {}
        try:
            result = self._eapi_command("show bgp evpn summary")
            peers = result.get("vrfs", {}).get("default", {}).get("peers", {})
            for peer, info in peers.items():
                routes[peer] = {
                    "peer": peer,
                    "route_type": 2,
                    "state": info.get("peerState", "unknown"),
                    "prefix_count": info.get("prefixReceived", 0),
                }
        except Exception:
            self._logger.debug("EVPN not available on %s", self.hostname)
        return routes

    # -- Configuration management -------------------------------------------

    def push_config(self, config: str) -> bool:
        """Push configuration via eAPI configure session.

        Args:
            config: EOS configuration commands (one per line).

        Returns:
            ``True`` on success.

        Raises:
            ConfigPushError: If the configuration push fails.

        """
        self._ensure_connected()
        try:
            commands = [line.strip() for line in config.splitlines() if line.strip()]
            self._eapi_node.config(commands)
            self._logger.info("Configuration pushed to %s", self.hostname)
            return True
        except Exception as exc:
            raise ConfigPushError(
                f"Config push failed: {exc}",
                device=self.hostname,
            ) from exc

    def execute_command(self, command: str) -> str:
        """Execute an operational command via eAPI.

        Args:
            command: EOS CLI command.

        Returns:
            Text representation of the command output.

        Raises:
            CommandExecutionError: If the command fails.

        """
        self._ensure_connected()
        try:
            result = self._eapi_node.enable(command, encoding="text")
            if isinstance(result, list) and result:
                return str(result[0].get("result", {}).get("output", ""))
            return str(result)
        except Exception as exc:
            raise CommandExecutionError(
                f"Command execution failed: {exc}",
                device=self.hostname,
                details={"command": command},
            ) from exc

    # -- Internal helpers ---------------------------------------------------

    def _connect_eapi(self) -> None:
        """Establish an eAPI connection via pyeapi."""
        try:
            import pyeapi

            self._eapi_node = pyeapi.connect(
                transport="https",
                host=self._device_info.hostname,
                username=self._device_info.username,
                password=self._device_info.password,
                port=self._device_info.port or EAPI_DEFAULT_PORT,
                timeout=self._device_info.timeout,
            )
            self._logger.debug("eAPI connected to %s", self.hostname)
        except ImportError:
            raise ConnectionError(
                "pyeapi is not installed",
                device=self.hostname,
            ) from None
        except Exception as exc:
            raise ConnectionError(
                f"eAPI connection failed: {exc}",
                device=self.hostname,
            ) from exc

    def _connect_napalm(self) -> None:
        """Establish a NAPALM EOS session."""
        try:
            import napalm

            driver_cls = napalm.get_network_driver("eos")
            self._napalm_driver = driver_cls(
                hostname=self._device_info.hostname,
                username=self._device_info.username,
                password=self._device_info.password,
                timeout=self._device_info.timeout,
                optional_args={
                    "port": self._device_info.port or EAPI_DEFAULT_PORT,
                },
            )
            self._napalm_driver.open()
            self._logger.debug("NAPALM (EOS) connected to %s", self.hostname)
        except ImportError:
            self._logger.warning("napalm not installed — NAPALM getters will be unavailable")
        except Exception as exc:
            self._logger.warning("NAPALM connection failed: %s", exc)

    def _ensure_connected(self) -> None:
        """Raise if the eAPI node is not connected."""
        if not self._connected or self._eapi_node is None:
            raise ConnectionError(
                "Not connected — call connect() first",
                device=self.hostname,
            )

    def _eapi_command(self, command: str) -> dict[str, Any]:
        """Execute a single eAPI command and return JSON response.

        Args:
            command: EOS show command.

        Returns:
            Parsed JSON result dict.

        """
        try:
            result = self._eapi_node.enable(command, encoding="json")
            if isinstance(result, list) and result:
                return dict(result[0].get("result", {}))
            return {}
        except Exception as exc:
            raise CommandExecutionError(
                f"eAPI command failed: {exc}",
                device=self.hostname,
                details={"command": command},
            ) from exc
