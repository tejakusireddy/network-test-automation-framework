"""Nornir-based inventory management.

Wraps Nornir's inventory system to provide a convenient API for
loading device inventories, filtering hosts, and integrating with
the driver factory.

Supports YAML-based SimpleInventory (default), as well as programmatic
host registration for dynamic environments like containerlab.

Usage::

    mgr = InventoryManager(hosts_file="inventory/hosts.yml")
    juniper_hosts = mgr.filter(vendor="juniper")
    all_hosts = mgr.get_all_hosts()
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..core.base_driver import DeviceInfo
from ..core.exceptions import InventoryError

logger = logging.getLogger(__name__)

DEFAULT_HOSTS_FILE = Path("inventory/hosts.yml")
DEFAULT_GROUPS_FILE = Path("inventory/groups.yml")
DEFAULT_DEFAULTS_FILE = Path("inventory/defaults.yml")


@dataclass
class HostEntry:
    """Lightweight representation of an inventory host.

    Attributes:
        hostname: DNS name or IP address.
        vendor: Vendor identifier.
        platform: Nornir/NAPALM platform string.
        username: Login username.
        password: Login password.
        port: Management port.
        groups: Group memberships.
        data: Arbitrary key-value data attached to the host.

    """

    hostname: str
    vendor: str
    platform: str
    username: str = ""
    password: str = ""
    port: int = 22
    groups: list[str] = field(default_factory=list)
    data: dict[str, Any] = field(default_factory=dict)

    def to_device_info(self) -> DeviceInfo:
        """Convert to a ``DeviceInfo`` for driver instantiation."""
        return DeviceInfo(
            hostname=self.hostname,
            vendor=self.vendor,
            platform=self.platform,
            username=self.username,
            password=self.password,
            port=self.port,
        )


class InventoryManager:
    """Manage network device inventory with Nornir integration.

    Provides methods to load, query, filter, and export inventory data.
    If Nornir is available, it delegates to Nornir's SimpleInventory
    plugin.  Otherwise, it falls back to a standalone YAML-based loader.

    Args:
        hosts_file: Path to the hosts YAML inventory file.
        groups_file: Path to the groups YAML file.
        defaults_file: Path to the defaults YAML file.

    """

    def __init__(
        self,
        hosts_file: Path = DEFAULT_HOSTS_FILE,
        groups_file: Path = DEFAULT_GROUPS_FILE,
        defaults_file: Path = DEFAULT_DEFAULTS_FILE,
    ) -> None:
        """Initialize the inventory manager with inventory file paths."""
        self._hosts_file = Path(hosts_file)
        self._groups_file = Path(groups_file)
        self._defaults_file = Path(defaults_file)
        self._nornir: Any = None
        self._hosts: dict[str, HostEntry] = {}
        self._logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

    def load(self) -> None:
        """Load the inventory from YAML files.

        Attempts to initialize a Nornir instance with SimpleInventory.
        Falls back to direct YAML parsing if Nornir is unavailable.

        Raises:
            InventoryError: If the inventory files cannot be loaded.

        """
        try:
            self._load_nornir()
            self._logger.info("Inventory loaded via Nornir (%d hosts)", len(self._hosts))
        except ImportError:
            self._logger.info("Nornir not available, falling back to YAML loader")
            self._load_yaml()
            self._logger.info("Inventory loaded via YAML (%d hosts)", len(self._hosts))

    def _load_nornir(self) -> None:
        """Initialize Nornir with SimpleInventory plugin."""
        from nornir import InitNornir  # type: ignore[import-untyped]

        self._nornir = InitNornir(
            runner={"plugin": "threaded", "options": {"num_workers": 10}},
            inventory={
                "plugin": "SimpleInventory",
                "options": {
                    "host_file": str(self._hosts_file),
                    "group_file": str(self._groups_file)
                    if self._groups_file.exists()
                    else None,
                    "defaults_file": str(self._defaults_file)
                    if self._defaults_file.exists()
                    else None,
                },
            },
        )
        for name, host in self._nornir.inventory.hosts.items():
            self._hosts[name] = HostEntry(
                hostname=str(host.hostname or name),
                vendor=str(host.platform or ""),
                platform=str(host.platform or ""),
                username=str(host.username or ""),
                password=str(host.password or ""),
                port=int(host.port or 22),
                groups=[str(g) for g in host.groups],
                data=dict(host.data),
            )

    def _load_yaml(self) -> None:
        """Fall back to loading hosts from a YAML file without Nornir."""
        import yaml  # type: ignore[import-untyped]

        if not self._hosts_file.exists():
            raise InventoryError(
                f"Hosts file not found: {self._hosts_file}",
            )
        with self._hosts_file.open("r", encoding="utf-8") as fh:
            raw: dict[str, Any] = yaml.safe_load(fh) or {}

        for name, host_data in raw.items():
            if not isinstance(host_data, dict):
                continue
            self._hosts[name] = HostEntry(
                hostname=host_data.get("hostname", name),
                vendor=host_data.get("platform", ""),
                platform=host_data.get("platform", ""),
                username=host_data.get("username", ""),
                password=host_data.get("password", ""),
                port=host_data.get("port", 22),
                groups=host_data.get("groups", []),
                data=host_data.get("data", {}),
            )

    def add_host(self, name: str, entry: HostEntry) -> None:
        """Programmatically add a host to the inventory.

        Args:
            name: Inventory name for the host.
            entry: Host parameters.

        """
        self._hosts[name] = entry
        self._logger.debug("Added host %s to inventory", name)

    def get_host(self, name: str) -> HostEntry:
        """Retrieve a single host by name.

        Args:
            name: Inventory name.

        Returns:
            The ``HostEntry`` for the requested host.

        Raises:
            InventoryError: If the host is not found.

        """
        if name not in self._hosts:
            raise InventoryError(
                f"Host '{name}' not found in inventory",
                details={"available": list(self._hosts.keys())},
            )
        return self._hosts[name]

    def get_all_hosts(self) -> dict[str, HostEntry]:
        """Return a copy of all hosts in the inventory."""
        return dict(self._hosts)

    def filter(
        self,
        vendor: str | None = None,
        platform: str | None = None,
        group: str | None = None,
    ) -> dict[str, HostEntry]:
        """Filter hosts by vendor, platform, or group membership.

        Args:
            vendor: Filter by vendor (case-insensitive).
            platform: Filter by platform string (case-insensitive).
            group: Filter by group membership.

        Returns:
            Mapping of matching host names to ``HostEntry`` instances.

        """
        results: dict[str, HostEntry] = {}
        for name, entry in self._hosts.items():
            if vendor and entry.vendor.lower() != vendor.lower():
                continue
            if platform and entry.platform.lower() != platform.lower():
                continue
            if group and group not in entry.groups:
                continue
            results[name] = entry
        return results

    def get_device_infos(
        self,
        vendor: str | None = None,
    ) -> list[DeviceInfo]:
        """Return ``DeviceInfo`` objects for filtered hosts.

        Args:
            vendor: Optional vendor filter.

        Returns:
            List of ``DeviceInfo`` instances suitable for driver creation.

        """
        hosts = self.filter(vendor=vendor) if vendor else self._hosts
        return [entry.to_device_info() for entry in hosts.values()]

    @property
    def nornir(self) -> Any:
        """Return the underlying Nornir instance, if available."""
        return self._nornir

    @property
    def host_count(self) -> int:
        """Return the number of hosts in the inventory."""
        return len(self._hosts)
