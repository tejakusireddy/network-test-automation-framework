"""Unit tests for the DriverFactory."""

from __future__ import annotations

from typing import Any

import pytest
from src.core.base_driver import BaseDriver, DeviceInfo
from src.core.exceptions import InventoryError
from src.drivers.arista_driver import AristaDriver
from src.drivers.cisco_driver import CiscoDriver
from src.drivers.driver_factory import DriverFactory
from src.drivers.juniper_driver import JuniperDriver


@pytest.fixture
def factory() -> DriverFactory:
    """A default DriverFactory instance."""
    return DriverFactory()


class TestDriverFactory:
    """Tests for driver creation and registration."""

    @pytest.mark.parametrize(
        "vendor,expected_cls",
        [
            ("juniper", JuniperDriver),
            ("junos", JuniperDriver),
            ("cisco", CiscoDriver),
            ("ios", CiscoDriver),
            ("iosxe", CiscoDriver),
            ("iosxr", CiscoDriver),
            ("nxos", CiscoDriver),
            ("arista", AristaDriver),
            ("eos", AristaDriver),
        ],
    )
    def test_create_returns_correct_driver(
        self,
        factory: DriverFactory,
        juniper_device_info: DeviceInfo,
        vendor: str,
        expected_cls: type[BaseDriver],
    ) -> None:
        driver = factory.create(vendor, juniper_device_info)
        assert isinstance(driver, expected_cls)

    def test_create_unsupported_vendor_raises(
        self, factory: DriverFactory, juniper_device_info: DeviceInfo
    ) -> None:
        with pytest.raises(InventoryError, match="Unsupported vendor"):
            factory.create("nokia", juniper_device_info)

    def test_create_case_insensitive(
        self, factory: DriverFactory, juniper_device_info: DeviceInfo
    ) -> None:
        driver = factory.create("JUNIPER", juniper_device_info)
        assert isinstance(driver, JuniperDriver)

    def test_register_custom_driver(
        self, factory: DriverFactory, juniper_device_info: DeviceInfo
    ) -> None:

        class CustomDriver(BaseDriver):
            def connect(self) -> None: ...
            def disconnect(self) -> None: ...
            def get_bgp_neighbors(self) -> dict[str, Any]:
                return {}

            def get_interfaces(self) -> dict[str, Any]:
                return {}

            def get_routing_table(self) -> dict[str, Any]:
                return {}

            def get_lldp_neighbors(self) -> dict[str, Any]:
                return {}

            def get_evpn_routes(self) -> dict[str, Any]:
                return {}

            def push_config(self, config: str) -> bool:
                return True

            def execute_command(self, command: str) -> str:
                return ""

        factory.register("custom-vendor", CustomDriver)
        driver = factory.create("custom-vendor", juniper_device_info)
        assert isinstance(driver, CustomDriver)

    def test_create_from_dict(self, factory: DriverFactory) -> None:
        host = {
            "hostname": "spine1",
            "vendor": "juniper",
            "platform": "junos",
            "username": "admin",
            "password": "secret",
        }
        driver = factory.create_from_dict(host)
        assert isinstance(driver, JuniperDriver)
        assert driver.hostname == "spine1"

    def test_create_from_dict_missing_vendor_raises(self, factory: DriverFactory) -> None:
        with pytest.raises(InventoryError, match="missing"):
            factory.create_from_dict({"hostname": "test"})

    def test_supported_vendors(self, factory: DriverFactory) -> None:
        vendors = factory.supported_vendors
        assert "juniper" in vendors
        assert "cisco" in vendors
        assert "arista" in vendors

    def test_custom_drivers_in_constructor(self, juniper_device_info: DeviceInfo) -> None:

        class MyDriver(BaseDriver):
            def connect(self) -> None: ...
            def disconnect(self) -> None: ...
            def get_bgp_neighbors(self) -> dict[str, Any]:
                return {}

            def get_interfaces(self) -> dict[str, Any]:
                return {}

            def get_routing_table(self) -> dict[str, Any]:
                return {}

            def get_lldp_neighbors(self) -> dict[str, Any]:
                return {}

            def get_evpn_routes(self) -> dict[str, Any]:
                return {}

            def push_config(self, config: str) -> bool:
                return True

            def execute_command(self, command: str) -> str:
                return ""

        factory = DriverFactory(custom_drivers={"myvendor": MyDriver})
        driver = factory.create("myvendor", juniper_device_info)
        assert isinstance(driver, MyDriver)
