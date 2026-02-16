"""Cisco IOS-XE / IOS-XR device driver using NAPALM with Netmiko fallback.

Implements ``BaseDriver`` for Cisco devices.  Primary data collection
uses NAPALM getters; commands not covered by NAPALM fall back to
Netmiko SSH sessions.

Requires:
    - napalm
    - netmiko

Usage::

    info = DeviceInfo(hostname="wan-router", vendor="cisco", platform="ios", ...)
    with CiscoDriver(info) as drv:
        bgp = drv.get_bgp_neighbors()
"""

from __future__ import annotations

import contextlib
import logging
from typing import Any

from ..core.base_driver import BaseDriver, DeviceInfo
from ..core.exceptions import (
    CommandExecutionError,
    ConfigPushError,
    ConnectionError,
)

logger = logging.getLogger(__name__)

NAPALM_PLATFORM_MAP: dict[str, str] = {
    "ios": "ios",
    "iosxe": "ios",
    "iosxr": "iosxr",
    "nxos": "nxos",
    "nxos_ssh": "nxos_ssh",
}


class CiscoDriver(BaseDriver):
    """Cisco device driver using NAPALM + Netmiko fallback.

    NAPALM provides a unified getter interface for common network data.
    For commands or operations not supported by NAPALM, the driver opens
    a parallel Netmiko SSH session.

    Args:
        device_info: Connection parameters for the Cisco device.

    """

    def __init__(self, device_info: DeviceInfo) -> None:
        """Initialize the Cisco driver with device connection parameters."""
        super().__init__(device_info)
        self._napalm_driver: Any = None
        self._netmiko_conn: Any = None

    # -- Connection lifecycle -----------------------------------------------

    def connect(self) -> None:
        """Open NAPALM and Netmiko sessions to the device.

        Raises:
            ConnectionError: If the session cannot be established.

        """
        try:
            import napalm

            platform = NAPALM_PLATFORM_MAP.get(
                self._device_info.platform, self._device_info.platform
            )
            driver_cls = napalm.get_network_driver(platform)
            self._napalm_driver = driver_cls(
                hostname=self._device_info.hostname,
                username=self._device_info.username,
                password=self._device_info.password,
                timeout=self._device_info.timeout,
                optional_args={
                    "port": self._device_info.port,
                },
            )
            self._napalm_driver.open()
            self._connected = True
            self._logger.info(
                "NAPALM connected to %s (platform: %s)",
                self.hostname,
                platform,
            )
        except ImportError:
            raise ConnectionError(
                "napalm is not installed",
                device=self.hostname,
            ) from None
        except Exception as exc:
            raise ConnectionError(
                f"Failed to connect: {exc}",
                device=self.hostname,
                details={"platform": self._device_info.platform},
            ) from exc

    def disconnect(self) -> None:
        """Close NAPALM and Netmiko sessions.  Idempotent."""
        if self._napalm_driver is not None:
            try:
                self._napalm_driver.close()
            except Exception:
                self._logger.debug("Error closing NAPALM session", exc_info=True)
            finally:
                self._napalm_driver = None

        if self._netmiko_conn is not None:
            try:
                self._netmiko_conn.disconnect()
            except Exception:
                self._logger.debug("Error closing Netmiko session", exc_info=True)
            finally:
                self._netmiko_conn = None

        self._connected = False
        self._logger.info("Disconnected from %s", self.hostname)

    # -- Data collection ----------------------------------------------------

    def get_bgp_neighbors(self) -> dict[str, Any]:
        """Retrieve BGP neighbors via NAPALM ``get_bgp_neighbors``.

        Returns:
            Mapping of peer address to session details.

        """
        self._ensure_connected()
        raw = self._napalm_driver.get_bgp_neighbors()
        neighbors: dict[str, Any] = {}

        for _vrf_name, vrf_data in raw.items():
            if not isinstance(vrf_data, dict):
                continue
            peers = vrf_data.get("peers", vrf_data)
            if not isinstance(peers, dict):
                continue
            for peer_addr, peer_info in peers.items():
                if not isinstance(peer_info, dict):
                    continue
                neighbors[peer_addr] = {
                    "peer_address": peer_addr,
                    "state": str(
                        (peer_info.get("is_up", False) and "established")
                        or peer_info.get("state", "unknown")
                    ).lower(),
                    "peer_as": peer_info.get("remote_as"),
                    "local_as": peer_info.get("local_as"),
                    "received_prefixes": peer_info.get("address_family", {})
                    .get("ipv4", {})
                    .get("received_prefixes", 0),
                    "sent_prefixes": peer_info.get("address_family", {})
                    .get("ipv4", {})
                    .get("sent_prefixes", 0),
                    "is_up": peer_info.get("is_up", False),
                    "uptime": peer_info.get("uptime", 0),
                    "description": peer_info.get("description", ""),
                }

        self._logger.debug("Retrieved %d BGP neighbors", len(neighbors))
        return neighbors

    def get_interfaces(self) -> dict[str, Any]:
        """Retrieve interface table via NAPALM ``get_interfaces``.

        Returns:
            Mapping of interface name to operational details.

        """
        self._ensure_connected()
        raw = self._napalm_driver.get_interfaces()
        counters = self._safe_get_counters()
        interfaces: dict[str, Any] = {}

        for name, info in raw.items():
            iface_counters = counters.get(name, {})
            interfaces[name] = {
                "name": name,
                "admin_status": "up" if info.get("is_enabled") else "down",
                "oper_status": "up" if info.get("is_up") else "down",
                "description": info.get("description", ""),
                "speed": info.get("speed", 0),
                "mtu": info.get("mtu", 0),
                "mac_address": info.get("mac_address", ""),
                "input_errors": iface_counters.get("rx_errors", 0),
                "output_errors": iface_counters.get("tx_errors", 0),
            }

        self._logger.debug("Retrieved %d interfaces", len(interfaces))
        return interfaces

    def get_routing_table(self) -> dict[str, Any]:
        """Retrieve routing table via NAPALM ``get_route_to``.

        Falls back to Netmiko CLI parsing if NAPALM does not support
        the required getter on this platform.

        Returns:
            Mapping of prefix to route details.

        """
        self._ensure_connected()
        routes: dict[str, Any] = {}
        try:
            raw = self._napalm_driver.get_route_to()
            for prefix, entries in raw.items():
                if entries:
                    best = entries[0] if isinstance(entries, list) else entries
                    routes[prefix] = {
                        "prefix": prefix,
                        "protocol": best.get("protocol", ""),
                        "next_hop": best.get("next_hop", ""),
                        "preference": best.get("preference", 0),
                        "metric": best.get("metric", 0),
                        "age": best.get("age", 0),
                    }
        except (NotImplementedError, AttributeError):
            self._logger.info("NAPALM get_route_to not supported, falling back to CLI")
            output = self._netmiko_command("show ip route")
            routes = self._parse_cisco_routes(output)

        self._logger.debug("Retrieved %d routes", len(routes))
        return routes

    def get_lldp_neighbors(self) -> dict[str, Any]:
        """Retrieve LLDP neighbor table via NAPALM ``get_lldp_neighbors_detail``.

        Returns:
            Mapping of local interface to neighbor details.

        """
        self._ensure_connected()
        raw = self._napalm_driver.get_lldp_neighbors_detail()
        neighbors: dict[str, Any] = {}

        for local_if, neighbor_list in raw.items():
            if neighbor_list:
                n = neighbor_list[0]
                neighbors[local_if] = {
                    "local_interface": local_if,
                    "remote_system": n.get("remote_system_name", ""),
                    "remote_port": n.get("remote_port", ""),
                    "remote_port_description": n.get("remote_port_description", ""),
                    "remote_chassis_id": n.get("remote_chassis_id", ""),
                }

        self._logger.debug("Retrieved %d LLDP neighbors", len(neighbors))
        return neighbors

    def get_evpn_routes(self) -> dict[str, Any]:
        """Retrieve EVPN routes via CLI (NAPALM lacks an EVPN getter).

        Returns:
            Mapping of route key to EVPN route details.

        """
        self._ensure_connected()
        routes: dict[str, Any] = {}
        try:
            output = self._netmiko_command("show bgp l2vpn evpn summary")
            routes = self._parse_evpn_summary(output)
        except Exception:
            self._logger.debug("EVPN not supported on %s, returning empty", self.hostname)
        return routes

    # -- Configuration management -------------------------------------------

    def push_config(self, config: str) -> bool:
        """Push configuration via NAPALM merge + commit.

        Args:
            config: IOS-style configuration text.

        Returns:
            ``True`` on successful commit.

        Raises:
            ConfigPushError: If load or commit fails.

        """
        self._ensure_connected()
        try:
            self._napalm_driver.load_merge_candidate(config=config)
            diff = self._napalm_driver.compare_config()
            if diff:
                self._logger.info("Config diff:\n%s", diff)
                self._napalm_driver.commit_config()
                self._logger.info("Configuration committed on %s", self.hostname)
            else:
                self._logger.info("No config changes to commit on %s", self.hostname)
                self._napalm_driver.discard_config()
            return True
        except Exception as exc:
            with contextlib.suppress(Exception):
                self._napalm_driver.discard_config()
            raise ConfigPushError(
                f"Config push failed: {exc}",
                device=self.hostname,
            ) from exc

    def execute_command(self, command: str) -> str:
        """Execute a CLI command via Netmiko.

        Args:
            command: Cisco CLI command.

        Returns:
            Raw text output.

        Raises:
            CommandExecutionError: If the command fails.

        """
        self._ensure_connected()
        return self._netmiko_command(command)

    # -- Internal helpers ---------------------------------------------------

    def _ensure_connected(self) -> None:
        """Raise if the NAPALM driver is not connected."""
        if not self._connected or self._napalm_driver is None:
            raise ConnectionError(
                "Not connected — call connect() first",
                device=self.hostname,
            )

    def _get_netmiko_connection(self) -> Any:
        """Lazily establish a Netmiko SSH session.

        Returns:
            An active Netmiko connection handler.

        """
        if self._netmiko_conn is not None:
            return self._netmiko_conn

        try:
            from netmiko import ConnectHandler

            device_type_map: dict[str, str] = {
                "ios": "cisco_ios",
                "iosxe": "cisco_ios",
                "iosxr": "cisco_xr",
                "nxos": "cisco_nxos",
            }
            self._netmiko_conn = ConnectHandler(
                device_type=device_type_map.get(self._device_info.platform, "cisco_ios"),
                host=self._device_info.hostname,
                username=self._device_info.username,
                password=self._device_info.password,
                port=self._device_info.port,
                timeout=self._device_info.timeout,
            )
            return self._netmiko_conn
        except ImportError:
            raise ConnectionError(
                "netmiko is not installed",
                device=self.hostname,
            ) from None
        except Exception as exc:
            raise ConnectionError(
                f"Netmiko connection failed: {exc}",
                device=self.hostname,
            ) from exc

    def _netmiko_command(self, command: str) -> str:
        """Execute a command via Netmiko and return raw output."""
        try:
            conn = self._get_netmiko_connection()
            return str(conn.send_command(command, read_timeout=self._device_info.timeout))
        except Exception as exc:
            raise CommandExecutionError(
                f"Command execution failed: {exc}",
                device=self.hostname,
                details={"command": command},
            ) from exc

    def _safe_get_counters(self) -> dict[str, Any]:
        """Attempt to get interface counters; return empty on failure."""
        try:
            return dict(self._napalm_driver.get_interfaces_counters())
        except Exception:
            self._logger.debug("Interface counters unavailable", exc_info=True)
            return {}

    @staticmethod
    def _parse_cisco_routes(output: str) -> dict[str, Any]:
        """Parse ``show ip route`` text output into structured data.

        This is a simplified parser for the most common IOS output format.
        """
        routes: dict[str, Any] = {}
        for line in output.splitlines():
            line = line.strip()
            if not line or line.startswith("Gateway") or line.startswith("Codes"):
                continue
            parts = line.split()
            if len(parts) < 2:
                continue
            protocol_char = parts[0]
            protocol_map: dict[str, str] = {
                "C": "connected",
                "S": "static",
                "O": "ospf",
                "B": "bgp",
                "D": "eigrp",
                "R": "rip",
                "i": "isis",
            }
            protocol = protocol_map.get(protocol_char, protocol_char)
            prefix = ""
            next_hop = ""
            for i, part in enumerate(parts):
                if "/" in part and "." in part:
                    prefix = part.rstrip(",")
                if part == "via":
                    next_hop = parts[i + 1].rstrip(",") if i + 1 < len(parts) else ""

            if prefix:
                routes[prefix] = {
                    "prefix": prefix,
                    "protocol": protocol,
                    "next_hop": next_hop,
                    "preference": 0,
                    "metric": 0,
                }
        return routes

    @staticmethod
    def _parse_evpn_summary(output: str) -> dict[str, Any]:
        """Parse EVPN summary output into structured data."""
        routes: dict[str, Any] = {}
        for line in output.splitlines():
            line = line.strip()
            if not line or line.startswith("BGP") or line.startswith("Neighbor"):
                continue
            parts = line.split()
            if len(parts) >= 3:
                neighbor = parts[0]
                routes[neighbor] = {
                    "neighbor": neighbor,
                    "route_type": 2,
                    "state": parts[-1] if parts else "unknown",
                }
        return routes
