"""Abstract base class for vendor-specific network device drivers.

Defines the contract that every vendor driver must implement and provides
concrete *template method* implementations for common workflows such as
connectivity validation and health checks.

Usage::

    with JuniperDriver(host="spine1", ...) as driver:
        snapshot = driver.take_snapshot("pre-change")
        driver.push_config(candidate)
        post = driver.take_snapshot("post-change")
        diff = driver.compare_snapshots(snapshot, post)
"""

from __future__ import annotations

import abc
import json
import logging
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from .exceptions import (
    ConnectionError,
    SnapshotError,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

MAX_RETRY_ATTEMPTS = 3
RETRY_BACKOFF_BASE = 2.0


class InterfaceState(StrEnum):
    """Operational state of a network interface."""

    UP = "up"
    DOWN = "down"
    ADMIN_DOWN = "admin-down"
    UNKNOWN = "unknown"


class BgpState(StrEnum):
    """BGP session state machine values."""

    IDLE = "idle"
    CONNECT = "connect"
    ACTIVE = "active"
    OPENSENT = "opensent"
    OPENCONFIRM = "openconfirm"
    ESTABLISHED = "established"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class DeviceInfo:
    """Immutable device connection parameters.

    Attributes:
        hostname: DNS name or IP address of the device.
        vendor: Vendor identifier (``juniper``, ``cisco``, ``arista``).
        platform: Platform string used by Nornir / NAPALM.
        username: Login username.
        password: Login password.
        port: Management port (default varies by transport).
        timeout: Connection timeout in seconds.

    """

    hostname: str
    vendor: str
    platform: str
    username: str
    password: str
    port: int = 830
    timeout: int = 30


@dataclass
class Snapshot:
    """Point-in-time capture of device network state.

    Attributes:
        snapshot_id: Unique identifier for this snapshot.
        device: Hostname of the device.
        timestamp: ISO-8601 timestamp of capture.
        bgp_neighbors: Mapping of peer address to session details.
        interfaces: Mapping of interface name to status details.
        routing_table: Mapping of prefix to route details.
        lldp_neighbors: Mapping of local interface to neighbor info.
        evpn_routes: Mapping of route distinguisher to EVPN route entries.
        raw_data: Optional vendor-specific unstructured data.

    """

    snapshot_id: str
    device: str
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    bgp_neighbors: dict[str, Any] = field(default_factory=dict)
    interfaces: dict[str, Any] = field(default_factory=dict)
    routing_table: dict[str, Any] = field(default_factory=dict)
    lldp_neighbors: dict[str, Any] = field(default_factory=dict)
    evpn_routes: dict[str, Any] = field(default_factory=dict)
    raw_data: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> str:
        """Serialize the snapshot to a JSON string."""
        return json.dumps(asdict(self), indent=2, default=str)

    @classmethod
    def from_json(cls, data: str) -> Snapshot:
        """Deserialize a snapshot from a JSON string."""
        payload: dict[str, Any] = json.loads(data)
        return cls(**payload)


@dataclass
class DiffEntry:
    """Single difference between two snapshot fields.

    Attributes:
        category: The data domain (e.g., ``bgp_neighbors``).
        key: The specific item that differs.
        action: One of ``added``, ``removed``, ``changed``.
        before: Value in the pre-snapshot (``None`` for additions).
        after: Value in the post-snapshot (``None`` for removals).

    """

    category: str
    key: str
    action: str
    before: Any = None
    after: Any = None


@dataclass
class SnapshotDiff:
    """Structured comparison result between two snapshots.

    Attributes:
        pre_id: ID of the pre-change snapshot.
        post_id: ID of the post-change snapshot.
        device: Hostname of the device.
        timestamp: When the diff was computed.
        diffs: Ordered list of individual differences.

    """

    pre_id: str
    post_id: str
    device: str
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    diffs: list[DiffEntry] = field(default_factory=list)

    @property
    def has_changes(self) -> bool:
        """Return ``True`` if any differences were detected."""
        return len(self.diffs) > 0

    @property
    def added(self) -> list[DiffEntry]:
        """Return entries that were added post-change."""
        return [d for d in self.diffs if d.action == "added"]

    @property
    def removed(self) -> list[DiffEntry]:
        """Return entries that were removed post-change."""
        return [d for d in self.diffs if d.action == "removed"]

    @property
    def changed(self) -> list[DiffEntry]:
        """Return entries that changed between snapshots."""
        return [d for d in self.diffs if d.action == "changed"]


# ---------------------------------------------------------------------------
# Abstract base driver
# ---------------------------------------------------------------------------


class BaseDriver(abc.ABC):
    """Abstract base class for all vendor network device drivers.

    Subclasses **must** implement every ``@abstractmethod``.  Concrete
    *template methods* (``validate_connectivity``, ``run_health_check``)
    orchestrate the abstract operations into reusable workflows.

    The driver supports context-manager usage for automatic connect/disconnect::

        with SomeDriver(device_info) as drv:
            drv.get_bgp_neighbors()

    Args:
        device_info: Connection parameters for the target device.

    """

    def __init__(self, device_info: DeviceInfo) -> None:
        """Initialize the driver with device connection parameters."""
        self._device_info = device_info
        self._connected: bool = False
        self._logger = logging.getLogger(f"{self.__class__.__module__}.{self.__class__.__name__}")

    # -- Properties ---------------------------------------------------------

    @property
    def hostname(self) -> str:
        """Return the hostname of the managed device."""
        return self._device_info.hostname

    @property
    def vendor(self) -> str:
        """Return the vendor string (e.g., ``juniper``)."""
        return self._device_info.vendor

    @property
    def is_connected(self) -> bool:
        """Return ``True`` if the driver currently holds an open session."""
        return self._connected

    # -- Context manager ----------------------------------------------------

    def __enter__(self) -> BaseDriver:
        """Open a connection to the device upon entering a ``with`` block."""
        self.connect()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object | None,
    ) -> None:
        """Ensure the connection is closed when leaving a ``with`` block."""
        try:
            self.disconnect()
        except Exception:
            self._logger.exception("Error during disconnect in __exit__")

    # -- Abstract methods (vendor-specific) ---------------------------------

    @abc.abstractmethod
    def connect(self) -> None:
        """Establish a management session to the device.

        Raises:
            ConnectionError: If the connection cannot be established.

        """

    @abc.abstractmethod
    def disconnect(self) -> None:
        """Gracefully close the management session.

        Implementations must be idempotent—calling ``disconnect`` on an
        already-closed session should be a no-op.
        """

    @abc.abstractmethod
    def get_bgp_neighbors(self) -> dict[str, Any]:
        """Retrieve BGP neighbor table.

        Returns:
            Mapping of peer address to session details including state,
            prefixes received/sent, and uptime.

        """

    @abc.abstractmethod
    def get_interfaces(self) -> dict[str, Any]:
        """Retrieve interface status and counters.

        Returns:
            Mapping of interface name to operational details including
            admin/oper status, speed, MTU, and error counters.

        """

    @abc.abstractmethod
    def get_routing_table(self) -> dict[str, Any]:
        """Retrieve the IP routing table (RIB).

        Returns:
            Mapping of prefix to route details including next-hop,
            protocol, metric, and preference.

        """

    @abc.abstractmethod
    def get_lldp_neighbors(self) -> dict[str, Any]:
        """Retrieve LLDP neighbor adjacencies.

        Returns:
            Mapping of local interface to neighbor system name and
            remote port identifier.

        """

    @abc.abstractmethod
    def get_evpn_routes(self) -> dict[str, Any]:
        """Retrieve EVPN route table.

        Returns:
            Mapping of route distinguisher to EVPN route entries
            including route type, MAC/IP, and VNI.

        """

    @abc.abstractmethod
    def push_config(self, config: str) -> bool:
        """Push a configuration snippet to the device.

        Args:
            config: Vendor-native configuration text.

        Returns:
            ``True`` if the configuration was committed successfully.

        Raises:
            ConfigPushError: If the commit fails.

        """

    @abc.abstractmethod
    def execute_command(self, command: str) -> str:
        """Execute an operational-mode command on the device.

        Args:
            command: The CLI command string.

        Returns:
            Raw text output from the device.

        Raises:
            CommandExecutionError: If execution fails.

        """

    # -- Snapshot operations ------------------------------------------------

    def take_snapshot(self, snapshot_id: str) -> Snapshot:
        """Capture a full-state snapshot of the device.

        Collects BGP neighbors, interfaces, routing table, LLDP
        neighbors, and EVPN routes into a single ``Snapshot`` instance.

        Args:
            snapshot_id: Unique label for this snapshot (e.g., ``pre-change``).

        Returns:
            A populated ``Snapshot`` dataclass.

        Raises:
            SnapshotError: If any collection step fails.

        """
        self._logger.info("Taking snapshot '%s' on %s", snapshot_id, self.hostname)
        try:
            snapshot = Snapshot(
                snapshot_id=snapshot_id,
                device=self.hostname,
                bgp_neighbors=self._retry(self.get_bgp_neighbors),
                interfaces=self._retry(self.get_interfaces),
                routing_table=self._retry(self.get_routing_table),
                lldp_neighbors=self._retry(self.get_lldp_neighbors),
                evpn_routes=self._retry(self.get_evpn_routes),
            )
        except Exception as exc:
            raise SnapshotError(
                f"Failed to capture snapshot '{snapshot_id}'",
                device=self.hostname,
                details={"original_error": str(exc)},
            ) from exc
        self._logger.info("Snapshot '%s' captured successfully", snapshot_id)
        return snapshot

    def compare_snapshots(self, pre: Snapshot, post: Snapshot) -> SnapshotDiff:
        """Compute structured differences between two snapshots.

        Iterates over each data category (BGP, interfaces, routes, LLDP,
        EVPN) and records additions, removals, and value changes.

        Args:
            pre: The baseline snapshot.
            post: The snapshot to compare against the baseline.

        Returns:
            A ``SnapshotDiff`` with categorized differences.

        """
        diff = SnapshotDiff(
            pre_id=pre.snapshot_id,
            post_id=post.snapshot_id,
            device=pre.device,
        )
        categories = [
            ("bgp_neighbors", pre.bgp_neighbors, post.bgp_neighbors),
            ("interfaces", pre.interfaces, post.interfaces),
            ("routing_table", pre.routing_table, post.routing_table),
            ("lldp_neighbors", pre.lldp_neighbors, post.lldp_neighbors),
            ("evpn_routes", pre.evpn_routes, post.evpn_routes),
        ]
        for category, pre_data, post_data in categories:
            self._diff_dicts(diff, category, pre_data, post_data)

        self._logger.info(
            "Snapshot diff: %d additions, %d removals, %d changes",
            len(diff.added),
            len(diff.removed),
            len(diff.changed),
        )
        return diff

    # -- Template methods (concrete workflows) ------------------------------

    def validate_connectivity(self) -> bool:
        """Template method: verify the device is reachable and responsive.

        Connects, runs a lightweight command, and disconnects.

        Returns:
            ``True`` if the device responded successfully.

        Raises:
            ConnectionError: If the device is unreachable.

        """
        self._logger.info("Validating connectivity to %s", self.hostname)
        was_connected = self._connected
        try:
            if not self._connected:
                self.connect()
            output = self.execute_command("show version")
            if not output:
                raise ConnectionError(
                    "Empty response from device",
                    device=self.hostname,
                )
            self._logger.info("Connectivity validated for %s", self.hostname)
            return True
        except Exception as exc:
            self._logger.error("Connectivity check failed for %s: %s", self.hostname, exc)
            raise
        finally:
            if not was_connected and self._connected:
                self.disconnect()

    def run_health_check(self) -> dict[str, Any]:
        """Template method: run a comprehensive health check.

        Collects and evaluates BGP neighbor status, interface states,
        and LLDP adjacencies. Returns a structured health report.

        Returns:
            Dict with keys ``bgp``, ``interfaces``, ``lldp``, each
            containing a ``healthy`` boolean and ``details`` mapping.

        """
        self._logger.info("Running health check on %s", self.hostname)
        report: dict[str, Any] = {}

        bgp = self._retry(self.get_bgp_neighbors)
        bgp_healthy = all(
            neighbor.get("state", "").lower() == BgpState.ESTABLISHED.value
            for neighbor in bgp.values()
        )
        report["bgp"] = {"healthy": bgp_healthy, "details": bgp}

        interfaces = self._retry(self.get_interfaces)
        iface_healthy = all(
            iface.get("oper_status", "").lower() == InterfaceState.UP.value
            for name, iface in interfaces.items()
            if not name.startswith(("lo", "Loopback", "Management", "mgmt"))
        )
        report["interfaces"] = {"healthy": iface_healthy, "details": interfaces}

        lldp = self._retry(self.get_lldp_neighbors)
        report["lldp"] = {"healthy": len(lldp) > 0, "details": lldp}

        overall = bgp_healthy and iface_healthy and len(lldp) > 0
        report["overall_healthy"] = overall

        level = logging.INFO if overall else logging.WARNING
        self._logger.log(level, "Health check result for %s: %s", self.hostname, overall)
        return report

    # -- Internal helpers ---------------------------------------------------

    @staticmethod
    def _diff_dicts(
        diff: SnapshotDiff,
        category: str,
        pre_data: dict[str, Any],
        post_data: dict[str, Any],
    ) -> None:
        """Compare two flat dictionaries and populate diff entries."""
        all_keys = set(pre_data.keys()) | set(post_data.keys())
        for key in sorted(all_keys):
            if key not in pre_data:
                diff.diffs.append(
                    DiffEntry(category=category, key=key, action="added", after=post_data[key])
                )
            elif key not in post_data:
                diff.diffs.append(
                    DiffEntry(category=category, key=key, action="removed", before=pre_data[key])
                )
            elif pre_data[key] != post_data[key]:
                diff.diffs.append(
                    DiffEntry(
                        category=category,
                        key=key,
                        action="changed",
                        before=pre_data[key],
                        after=post_data[key],
                    )
                )

    def _retry(
        self,
        func: Any,
        max_attempts: int = MAX_RETRY_ATTEMPTS,
        backoff_base: float = RETRY_BACKOFF_BASE,
    ) -> Any:
        """Retry a callable with exponential back-off.

        Args:
            func: Callable to invoke.
            max_attempts: Maximum number of attempts before raising.
            backoff_base: Base multiplier for exponential delay.

        Returns:
            The return value of *func* on the first successful call.

        Raises:
            The last exception if all attempts are exhausted.

        """
        last_exc: Exception | None = None
        for attempt in range(1, max_attempts + 1):
            try:
                return func()
            except Exception as exc:
                last_exc = exc
                if attempt < max_attempts:
                    delay = backoff_base**attempt
                    self._logger.warning(
                        "Attempt %d/%d for %s failed (%s), retrying in %.1fs",
                        attempt,
                        max_attempts,
                        func.__name__,
                        exc,
                        delay,
                    )
                    time.sleep(delay)
        raise last_exc  # type: ignore[misc]
