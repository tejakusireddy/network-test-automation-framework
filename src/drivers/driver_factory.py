"""Factory for creating vendor-specific driver instances.

Uses the Factory Pattern to instantiate the correct ``BaseDriver``
subclass based on the vendor/platform field from the inventory.
Integrates with Nornir inventory for automated driver selection.

Usage::

    factory = DriverFactory()
    driver = factory.create("juniper", device_info)

    # From Nornir inventory
    drivers = factory.from_nornir_inventory(nornir_instance)
"""

from __future__ import annotations

import logging
from typing import Any

from ..core.base_driver import BaseDriver, DeviceInfo
from ..core.exceptions import InventoryError
from .arista_driver import AristaDriver
from .cisco_driver import CiscoDriver
from .juniper_driver import JuniperDriver

logger = logging.getLogger(__name__)

VENDOR_DRIVER_MAP: dict[str, type[BaseDriver]] = {
    "juniper": JuniperDriver,
    "junos": JuniperDriver,
    "cisco": CiscoDriver,
    "ios": CiscoDriver,
    "iosxe": CiscoDriver,
    "iosxr": CiscoDriver,
    "nxos": CiscoDriver,
    "arista": AristaDriver,
    "eos": AristaDriver,
}

DEFAULT_PORTS: dict[str, int] = {
    "juniper": 830,
    "junos": 830,
    "cisco": 22,
    "ios": 22,
    "iosxe": 22,
    "iosxr": 22,
    "nxos": 22,
    "arista": 443,
    "eos": 443,
}


class DriverFactory:
    """Factory for creating vendor-specific ``BaseDriver`` instances.

    Maintains a registry of vendor names to driver classes and handles
    conversion from Nornir host objects to ``DeviceInfo`` dataclasses.

    Args:
        custom_drivers: Optional mapping of additional vendor names to
            driver classes for extensibility.

    """

    def __init__(
        self,
        custom_drivers: dict[str, type[BaseDriver]] | None = None,
    ) -> None:
        """Initialize the factory with an optional set of custom driver mappings."""
        self._registry: dict[str, type[BaseDriver]] = dict(VENDOR_DRIVER_MAP)
        if custom_drivers:
            self._registry.update(custom_drivers)
        self._logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

    def register(self, vendor: str, driver_cls: type[BaseDriver]) -> None:
        """Register a new vendor driver.

        Args:
            vendor: Vendor name or platform string.
            driver_cls: The driver class to associate.

        """
        self._registry[vendor.lower()] = driver_cls
        self._logger.info("Registered driver %s for vendor '%s'", driver_cls.__name__, vendor)

    def create(
        self,
        vendor: str,
        device_info: DeviceInfo,
    ) -> BaseDriver:
        """Create a driver instance for the given vendor.

        Args:
            vendor: Vendor or platform identifier (case-insensitive).
            device_info: Connection parameters.

        Returns:
            An unconnected ``BaseDriver`` subclass instance.

        Raises:
            InventoryError: If the vendor is not recognized.

        """
        vendor_key = vendor.lower()
        driver_cls = self._registry.get(vendor_key)
        if driver_cls is None:
            supported = ", ".join(sorted(self._registry.keys()))
            raise InventoryError(
                f"Unsupported vendor '{vendor}'. Supported: {supported}",
                details={"vendor": vendor},
            )
        self._logger.debug(
            "Creating %s for %s", driver_cls.__name__, device_info.hostname
        )
        return driver_cls(device_info)

    def create_from_dict(self, host_data: dict[str, Any]) -> BaseDriver:
        """Create a driver from a flat dictionary of host parameters.

        Expected keys: ``hostname``, ``vendor`` or ``platform``,
        ``username``, ``password``, and optionally ``port``, ``timeout``.

        Args:
            host_data: Dictionary of host parameters.

        Returns:
            An unconnected ``BaseDriver`` subclass instance.

        """
        vendor = host_data.get("vendor", host_data.get("platform", ""))
        if not vendor:
            raise InventoryError(
                "Host data missing 'vendor' or 'platform' field",
                details={"host_data": host_data},
            )

        device_info = DeviceInfo(
            hostname=host_data["hostname"],
            vendor=vendor,
            platform=host_data.get("platform", vendor),
            username=host_data.get("username", ""),
            password=host_data.get("password", ""),
            port=host_data.get("port", DEFAULT_PORTS.get(vendor.lower(), 22)),
            timeout=host_data.get("timeout", 30),
        )
        return self.create(vendor, device_info)

    def from_nornir_inventory(self, nornir: Any) -> dict[str, BaseDriver]:
        """Create drivers for all hosts in a Nornir inventory.

        Reads each ``nornir.inventory.hosts`` entry and constructs the
        appropriate driver.  The platform field determines the vendor.

        Args:
            nornir: An initialized Nornir instance.

        Returns:
            Mapping of hostname to ``BaseDriver`` instances (unconnected).

        """
        drivers: dict[str, BaseDriver] = {}
        for hostname, host in nornir.inventory.hosts.items():
            platform = host.platform or ""
            if not platform:
                self._logger.warning(
                    "Host %s has no platform, skipping", hostname
                )
                continue

            device_info = DeviceInfo(
                hostname=str(host.hostname or hostname),
                vendor=platform,
                platform=platform,
                username=str(host.username or ""),
                password=str(host.password or ""),
                port=int(host.port or DEFAULT_PORTS.get(platform.lower(), 22)),
                timeout=int(host.connection_options.get("timeout", 30))
                if hasattr(host, "connection_options")
                else 30,
            )
            try:
                drivers[hostname] = self.create(platform, device_info)
            except InventoryError:
                self._logger.warning(
                    "No driver for host %s (platform: %s)", hostname, platform
                )

        self._logger.info(
            "Created %d drivers from Nornir inventory", len(drivers)
        )
        return drivers

    @property
    def supported_vendors(self) -> list[str]:
        """Return sorted list of supported vendor/platform identifiers."""
        return sorted(self._registry.keys())
