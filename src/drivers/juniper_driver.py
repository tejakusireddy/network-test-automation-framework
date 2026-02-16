"""Juniper Networks device driver using PyEZ (junos-eznc).

Implements ``BaseDriver`` for JunOS devices via NETCONF. Uses the
PyEZ ``Device`` context manager, RPC calls for structured data
retrieval, and integrates with JSNAPy for snapshot comparison.

Requires:
    - junos-eznc (PyEZ)
    - jsnapy (optional, for snapshot comparison)

Usage::

    info = DeviceInfo(hostname="spine1", vendor="juniper", ...)
    with JuniperDriver(info) as drv:
        bgp = drv.get_bgp_neighbors()
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from ..core.base_driver import BaseDriver, DeviceInfo
from ..core.exceptions import (
    CommandExecutionError,
    ConfigPushError,
    ConnectionError,
)

if TYPE_CHECKING:
    from xml.etree import ElementTree

logger = logging.getLogger(__name__)

JUNOS_NETCONF_PORT = 830


class JuniperDriver(BaseDriver):
    """Juniper JunOS driver using PyEZ NETCONF.

    Leverages ``jnpr.junos.Device`` for transport and RPC execution,
    ``jnpr.junos.utils.config.Config`` for configuration management,
    and native XML RPC responses parsed into Python dicts.

    Args:
        device_info: Connection parameters for the Juniper device.

    """

    def __init__(self, device_info: DeviceInfo) -> None:
        """Initialize the Juniper driver with device connection parameters."""
        super().__init__(device_info)
        self._device: Any = None  # jnpr.junos.Device instance
        self._config: Any = None  # jnpr.junos.utils.config.Config instance

    # -- Connection lifecycle -----------------------------------------------

    def connect(self) -> None:
        """Open a NETCONF session to the Juniper device via PyEZ.

        Raises:
            ConnectionError: If the NETCONF session cannot be established.

        """
        try:
            from jnpr.junos import Device  # type: ignore[import-untyped]

            self._device = Device(
                host=self._device_info.hostname,
                user=self._device_info.username,
                passwd=self._device_info.password,
                port=self._device_info.port or JUNOS_NETCONF_PORT,
                timeout=self._device_info.timeout,
                gather_facts=True,
            )
            self._device.open()
            self._connected = True
            self._logger.info(
                "Connected to %s (JunOS %s)",
                self.hostname,
                self._device.facts.get("version", "unknown"),
            )
        except ImportError:
            raise ConnectionError(
                "junos-eznc (PyEZ) is not installed",
                device=self.hostname,
            ) from None
        except Exception as exc:
            raise ConnectionError(
                f"Failed to connect: {exc}",
                device=self.hostname,
                details={"port": self._device_info.port},
            ) from exc

    def disconnect(self) -> None:
        """Close the NETCONF session.  Idempotent."""
        if self._device is not None:
            try:
                self._device.close()
            except Exception:
                self._logger.debug("Ignoring error during disconnect", exc_info=True)
            finally:
                self._device = None
                self._connected = False
                self._logger.info("Disconnected from %s", self.hostname)

    # -- Data collection (abstract method implementations) ------------------

    def get_bgp_neighbors(self) -> dict[str, Any]:
        """Retrieve BGP neighbor table via ``<get-bgp-neighbor-information>`` RPC.

        Returns:
            Mapping of peer address to session details.

        """
        self._ensure_connected()
        rpc_reply = self._device.rpc.get_bgp_neighbor_information()  # type: ignore[union-attr]
        neighbors: dict[str, Any] = {}

        for item in rpc_reply.findall(".//bgp-peer"):
            peer_address = self._text(item, "peer-address")
            if not peer_address:
                continue
            peer_addr_clean = peer_address.split("+")[0]
            neighbors[peer_addr_clean] = {
                "peer_address": peer_addr_clean,
                "state": self._text(item, "peer-state", "unknown").lower(),
                "peer_as": self._text(item, "peer-as"),
                "local_as": self._text(item, "local-as"),
                "input_messages": self._int_text(item, "input-messages"),
                "output_messages": self._int_text(item, "output-messages"),
                "route_queue_count": self._int_text(item, "route-queue-count"),
                "flap_count": self._int_text(item, "flap-count"),
                "peer_id": self._text(item, "peer-id"),
                "description": self._text(item, "description"),
            }

        self._logger.debug("Retrieved %d BGP neighbors", len(neighbors))
        return neighbors

    def get_interfaces(self) -> dict[str, Any]:
        """Retrieve interface status via ``<get-interface-information>`` RPC.

        Returns:
            Mapping of interface name to operational details.

        """
        self._ensure_connected()
        rpc_reply = self._device.rpc.get_interface_information(terse=True)  # type: ignore[union-attr]
        interfaces: dict[str, Any] = {}

        for iface in rpc_reply.findall(".//physical-interface"):
            name = self._text(iface, "name")
            if not name:
                continue
            interfaces[name] = {
                "name": name,
                "admin_status": self._text(iface, "admin-status", "unknown").lower(),
                "oper_status": self._text(iface, "oper-status", "unknown").lower(),
                "description": self._text(iface, "description"),
                "speed": self._text(iface, "speed"),
                "mtu": self._text(iface, "mtu"),
                "input_errors": self._int_text(
                    iface, ".//input-error-list/input-errors"
                ),
                "output_errors": self._int_text(
                    iface, ".//output-error-list/output-errors"
                ),
            }

        self._logger.debug("Retrieved %d interfaces", len(interfaces))
        return interfaces

    def get_routing_table(self) -> dict[str, Any]:
        """Retrieve IPv4 unicast routing table via RPC.

        Returns:
            Mapping of prefix to route details.

        """
        self._ensure_connected()
        rpc_reply = self._device.rpc.get_route_information(table="inet.0")  # type: ignore[union-attr]
        routes: dict[str, Any] = {}

        for rt in rpc_reply.findall(".//rt"):
            prefix = self._text(rt, "rt-destination")
            if not prefix:
                continue
            entry = rt.find("rt-entry")
            if entry is None:
                continue
            routes[prefix] = {
                "prefix": prefix,
                "protocol": self._text(entry, "protocol-name"),
                "preference": self._int_text(entry, "preference"),
                "next_hop": self._text(
                    entry, ".//nh/to"
                ) or self._text(entry, ".//nh/nh-local-interface"),
                "age": self._text(entry, "age"),
                "metric": self._int_text(entry, "metric"),
            }

        self._logger.debug("Retrieved %d routes", len(routes))
        return routes

    def get_lldp_neighbors(self) -> dict[str, Any]:
        """Retrieve LLDP neighbor table via ``<get-lldp-neighbors-information>`` RPC.

        Returns:
            Mapping of local interface to neighbor details.

        """
        self._ensure_connected()
        rpc_reply = self._device.rpc.get_lldp_neighbors_information()  # type: ignore[union-attr]
        neighbors: dict[str, Any] = {}

        for item in rpc_reply.findall(".//lldp-neighbor-information"):
            local_if = self._text(item, "lldp-local-port-id")
            if not local_if:
                continue
            neighbors[local_if] = {
                "local_interface": local_if,
                "remote_system": self._text(item, "lldp-remote-system-name"),
                "remote_port": self._text(item, "lldp-remote-port-id"),
                "remote_port_description": self._text(
                    item, "lldp-remote-port-description"
                ),
                "remote_chassis_id": self._text(
                    item, "lldp-remote-chassis-id"
                ),
            }

        self._logger.debug("Retrieved %d LLDP neighbors", len(neighbors))
        return neighbors

    def get_evpn_routes(self) -> dict[str, Any]:
        """Retrieve EVPN route table via RPC.

        Returns:
            Mapping of route distinguisher to EVPN route entries.

        """
        self._ensure_connected()
        try:
            rpc_reply = self._device.rpc.get_route_information(  # type: ignore[union-attr]
                table="default-switch.evpn.0"
            )
        except Exception:
            self._logger.debug("EVPN table not available, returning empty")
            return {}

        routes: dict[str, Any] = {}
        for rt in rpc_reply.findall(".//rt"):
            prefix = self._text(rt, "rt-destination")
            if not prefix:
                continue
            entry = rt.find("rt-entry")
            if entry is None:
                continue

            route_type = self._detect_evpn_route_type(prefix)
            routes[prefix] = {
                "prefix": prefix,
                "route_type": route_type,
                "protocol": self._text(entry, "protocol-name"),
                "next_hop": self._text(entry, ".//nh/to"),
                "label": self._text(entry, ".//nh/label"),
                "communities": self._text(entry, "communities"),
            }

        self._logger.debug("Retrieved %d EVPN routes", len(routes))
        return routes

    # -- Configuration management -------------------------------------------

    def push_config(self, config: str) -> bool:
        """Push and commit a configuration snippet via PyEZ Config utility.

        Args:
            config: JunOS configuration text (set/hierarchical format).

        Returns:
            ``True`` on successful commit.

        Raises:
            ConfigPushError: If load or commit fails.

        """
        self._ensure_connected()
        try:
            from jnpr.junos.utils.config import Config  # type: ignore[import-untyped]

            with Config(self._device, mode="exclusive") as cu:
                cu.load(config, format="set", merge=True)
                cu.pdiff()
                cu.commit(timeout=60)
            self._logger.info("Configuration committed on %s", self.hostname)
            return True
        except Exception as exc:
            raise ConfigPushError(
                f"Config push failed: {exc}",
                device=self.hostname,
            ) from exc

    def execute_command(self, command: str) -> str:
        """Execute an operational CLI command.

        Args:
            command: JunOS operational command string.

        Returns:
            Text output from the command.

        Raises:
            CommandExecutionError: If the command fails.

        """
        self._ensure_connected()
        try:
            result = self._device.cli(command, warning=False)  # type: ignore[union-attr]
            return str(result)
        except Exception as exc:
            raise CommandExecutionError(
                f"Command execution failed: {exc}",
                device=self.hostname,
                details={"command": command},
            ) from exc

    # -- JSNAPy integration -------------------------------------------------

    def run_jsnapy_tests(
        self,
        test_files: list[str],
        action: str = "snap_pre",
    ) -> dict[str, Any]:
        """Execute JSNAPy test files against this device.

        Args:
            test_files: List of JSNAPy test file paths.
            action: JSNAPy action (``snap_pre``, ``snap_post``, ``check``).

        Returns:
            JSNAPy results dictionary.

        """
        try:
            from jnpr.jsnapy import SnapAdmin  # type: ignore[import-untyped]

            js_config = {
                "hosts": [
                    {
                        "device": self._device_info.hostname,
                        "username": self._device_info.username,
                        "passwd": self._device_info.password,
                        "port": self._device_info.port,
                    }
                ],
                "tests": test_files,
            }
            snap = SnapAdmin()
            if action == "snap_pre":
                return snap.snap(js_config, "pre")  # type: ignore[return-value]
            elif action == "snap_post":
                return snap.snap(js_config, "post")  # type: ignore[return-value]
            else:
                return snap.check(js_config, "pre", "post")  # type: ignore[return-value]
        except ImportError:
            self._logger.warning("jsnapy not installed, skipping JSNAPy tests")
            return {"error": "jsnapy not installed"}

    # -- Internal helpers ---------------------------------------------------

    def _ensure_connected(self) -> None:
        """Raise if the driver is not connected."""
        if not self._connected or self._device is None:
            raise ConnectionError(
                "Not connected — call connect() first",
                device=self.hostname,
            )

    @staticmethod
    def _text(
        element: ElementTree.Element,
        xpath: str,
        default: str = "",
    ) -> str:
        """Extract text from an XML element via XPath."""
        node = element.find(xpath)
        if node is not None and node.text:
            return node.text.strip()
        return default

    @staticmethod
    def _int_text(
        element: ElementTree.Element,
        xpath: str,
        default: int = 0,
    ) -> int:
        """Extract integer text from an XML element via XPath."""
        node = element.find(xpath)
        if node is not None and node.text:
            try:
                return int(node.text.strip())
            except ValueError:
                return default
        return default

    @staticmethod
    def _detect_evpn_route_type(prefix: str) -> int:
        """Infer EVPN route type from the route prefix string.

        JunOS EVPN routes are formatted as ``<type>:<fields>``.
        """
        if prefix.startswith("2:"):
            return 2
        elif prefix.startswith("5:"):
            return 5
        elif prefix.startswith("1:"):
            return 1
        elif prefix.startswith("3:"):
            return 3
        elif prefix.startswith("4:"):
            return 4
        return 0
