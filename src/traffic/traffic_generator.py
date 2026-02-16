"""Abstract traffic generator interface.

Defines the strategy pattern contract for traffic generation backends
(Ixia, Spirent, TRex, etc.).  Each implementation handles the specific
API calls while the test framework interacts with the uniform interface.

Usage::

    gen: TrafficGenerator = IxiaClient(api_server="10.0.0.100")
    gen.connect()
    gen.configure_stream(profile)
    gen.start_traffic()
    stats = gen.get_statistics()
    gen.stop_traffic()
"""

from __future__ import annotations

import abc
import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class TrafficProfile:
    """Configuration for a traffic stream.

    Attributes:
        name: Human-readable stream identifier.
        src_ip: Source IP address or range.
        dst_ip: Destination IP address or range.
        src_port: Source UDP/TCP port.
        dst_port: Destination UDP/TCP port.
        protocol: L4 protocol (``udp``, ``tcp``, ``icmp``).
        frame_size: Frame size in bytes.
        rate_pps: Transmission rate in packets per second.
        duration_seconds: How long to transmit (0 = continuous).
        vlan_id: Optional VLAN tag.
        dscp: Optional DSCP value for QoS testing.

    """

    name: str
    src_ip: str = "10.0.0.1"
    dst_ip: str = "10.0.0.2"
    src_port: int = 10000
    dst_port: int = 20000
    protocol: str = "udp"
    frame_size: int = 256
    rate_pps: int = 1000
    duration_seconds: int = 60
    vlan_id: int | None = None
    dscp: int | None = None


@dataclass
class TrafficStats:
    """Aggregated traffic statistics from a test run.

    Attributes:
        stream_name: Identifier of the traffic stream.
        tx_frames: Total frames transmitted.
        rx_frames: Total frames received.
        tx_rate_pps: Average transmit rate (pps).
        rx_rate_pps: Average receive rate (pps).
        loss_frames: Number of lost frames.
        loss_percent: Frame loss as a percentage.
        min_latency_us: Minimum latency in microseconds.
        max_latency_us: Maximum latency in microseconds.
        avg_latency_us: Average latency in microseconds.
        jitter_us: Jitter in microseconds.

    """

    stream_name: str
    tx_frames: int = 0
    rx_frames: int = 0
    tx_rate_pps: float = 0.0
    rx_rate_pps: float = 0.0
    loss_frames: int = 0
    loss_percent: float = 0.0
    min_latency_us: float = 0.0
    max_latency_us: float = 0.0
    avg_latency_us: float = 0.0
    jitter_us: float = 0.0
    raw_data: dict[str, Any] = field(default_factory=dict)


class TrafficGenerator(abc.ABC):
    """Abstract base class for traffic generation backends.

    Implementations must handle connection management, stream
    configuration, traffic control, and statistics collection.
    """

    def __init__(self) -> None:
        """Initialize the traffic generator base class."""
        self._logger = logging.getLogger(
            f"{self.__class__.__module__}.{self.__class__.__name__}"
        )

    @abc.abstractmethod
    def connect(self) -> None:
        """Establish a session with the traffic generator chassis/API."""

    @abc.abstractmethod
    def disconnect(self) -> None:
        """Close the session.  Must be idempotent."""

    @abc.abstractmethod
    def configure_stream(self, profile: TrafficProfile) -> str:
        """Configure a traffic stream based on the given profile.

        Args:
            profile: Traffic stream parameters.

        Returns:
            A stream handle/identifier for later reference.

        """

    @abc.abstractmethod
    def start_traffic(self, stream_id: str | None = None) -> None:
        """Start transmitting traffic.

        Args:
            stream_id: If given, start only this stream; otherwise
                start all configured streams.

        """

    @abc.abstractmethod
    def stop_traffic(self, stream_id: str | None = None) -> None:
        """Stop transmitting traffic.

        Args:
            stream_id: If given, stop only this stream; otherwise
                stop all streams.

        """

    @abc.abstractmethod
    def get_statistics(self, stream_id: str | None = None) -> list[TrafficStats]:
        """Collect traffic statistics.

        Args:
            stream_id: If given, return stats for only this stream.

        Returns:
            List of ``TrafficStats`` for each stream.

        """

    @abc.abstractmethod
    def clear_statistics(self) -> None:
        """Reset all traffic counters."""

    def __enter__(self) -> TrafficGenerator:
        """Connect upon entering a ``with`` block."""
        self.connect()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object | None,
    ) -> None:
        """Disconnect upon exiting a ``with`` block."""
        try:
            self.disconnect()
        except Exception:
            self._logger.exception("Error during traffic generator disconnect")
