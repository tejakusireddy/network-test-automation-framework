"""Custom exception hierarchy for the network test automation framework.

All framework exceptions inherit from ``NetworkTestError`` to enable
granular catch clauses while still allowing a single top-level handler.

Exception tree::

    NetworkTestError
    ├── ConnectionError
    ├── ValidationError
    ├── SnapshotError
    ├── TriageError
    ├── ConfigPushError
    ├── CommandExecutionError
    ├── InventoryError
    └── TopologyError
"""

from __future__ import annotations


class NetworkTestError(Exception):
    """Base exception for all network test automation errors.

    Attributes:
        message: Human-readable error description.
        device: Optional device hostname that triggered the error.
        details: Optional mapping of additional contextual data.

    """

    def __init__(
        self,
        message: str,
        device: str | None = None,
        details: dict[str, object] | None = None,
    ) -> None:
        """Initialize with a message, optional device context, and details."""
        self.message = message
        self.device = device
        self.details = details or {}
        super().__init__(self._format_message())

    def _format_message(self) -> str:
        """Format the exception message with optional device context."""
        parts: list[str] = []
        if self.device:
            parts.append(f"[{self.device}]")
        parts.append(self.message)
        if self.details:
            detail_str = ", ".join(f"{k}={v}" for k, v in self.details.items())
            parts.append(f"({detail_str})")
        return " ".join(parts)


class ConnectionError(NetworkTestError):
    """Raised when a device connection attempt fails or times out.

    Examples:
        - SSH/NETCONF handshake failure
        - Authentication failure
        - Connection timeout
        - Transport-layer errors

    """


class ValidationError(NetworkTestError):
    """Raised when a network state assertion fails.

    Examples:
        - BGP neighbor not in established state
        - Expected route missing from RIB
        - Interface error counters above threshold

    """


class SnapshotError(NetworkTestError):
    """Raised when snapshot capture or comparison fails.

    Examples:
        - Failure to serialize device state
        - Corrupt snapshot file on disk
        - Incompatible snapshot versions during comparison

    """


class TriageError(NetworkTestError):
    """Raised when automated failure triage encounters an error.

    Examples:
        - LLM API call failure
        - Log parsing error
        - Insufficient data for triage

    """


class ConfigPushError(NetworkTestError):
    """Raised when a configuration push to a device fails.

    Examples:
        - Commit check failure
        - Syntax error in candidate config
        - Lock contention on configuration database

    """


class CommandExecutionError(NetworkTestError):
    """Raised when a command execution on a device fails.

    Examples:
        - Command syntax error
        - Privilege escalation failure
        - Command timeout

    """


class InventoryError(NetworkTestError):
    """Raised when inventory loading or lookup fails.

    Examples:
        - Missing or malformed inventory file
        - Duplicate hostname entries
        - Missing required host attributes

    """


class TopologyError(NetworkTestError):
    """Raised when topology verification detects an inconsistency.

    Examples:
        - Expected LLDP neighbor not found
        - Unidirectional link detected
        - Topology graph is disconnected

    """
