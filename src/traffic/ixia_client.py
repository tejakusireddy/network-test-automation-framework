"""Keysight/Ixia IxNetwork REST API traffic generator client.

Wraps the ``ixnetwork_restpy`` SDK to provide a ``TrafficGenerator``
implementation for Ixia chassis.  Handles session management, topology
configuration, traffic item creation, and real-time statistics.

Requires:
    - ixnetwork_restpy

Usage::

    with IxiaClient(api_server="10.0.0.100", ports=[("10.0.0.100", 1, 1)]) as ixia:
        stream_id = ixia.configure_stream(profile)
        ixia.start_traffic(stream_id)
        stats = ixia.get_statistics()
        ixia.stop_traffic()
"""

from __future__ import annotations

import logging
import time
from typing import Any

from .traffic_generator import TrafficGenerator, TrafficProfile, TrafficStats

logger = logging.getLogger(__name__)

STATS_POLL_INTERVAL = 2
TRAFFIC_START_DELAY = 5


class IxiaClient(TrafficGenerator):
    """IxNetwork REST API client for traffic generation.

    Args:
        api_server: IP address of the IxNetwork API server.
        api_port: REST API port (default 443 for HTTPS).
        ports: List of ``(chassis_ip, card, port)`` tuples.
        username: IxNetwork username.
        password: IxNetwork password.

    """

    def __init__(
        self,
        api_server: str,
        api_port: int = 443,
        ports: list[tuple[str, int, int]] | None = None,
        username: str = "admin",
        password: str = "admin",
    ) -> None:
        """Initialize the Ixia client with API server connection settings."""
        super().__init__()
        self._api_server = api_server
        self._api_port = api_port
        self._ports = ports or []
        self._username = username
        self._password = password
        self._session: Any = None
        self._ixnetwork: Any = None
        self._stream_map: dict[str, Any] = {}

    def connect(self) -> None:
        """Connect to the IxNetwork API server and set up the session.

        Raises:
            RuntimeError: If ``ixnetwork_restpy`` is not installed.

        """
        try:
            from ixnetwork_restpy import SessionAssistant

            self._session = SessionAssistant(
                IpAddress=self._api_server,
                RestPort=self._api_port,
                UserName=self._username,
                Password=self._password,
                LogLevel="info",
            )
            self._ixnetwork = self._session.Ixnetwork
            self._logger.info("Connected to IxNetwork at %s", self._api_server)

            if self._ports:
                self._assign_ports()
        except ImportError:
            raise RuntimeError(
                "ixnetwork_restpy is not installed. Install with: pip install ixnetwork-restpy"
            ) from None
        except Exception as exc:
            raise RuntimeError(f"Failed to connect to IxNetwork: {exc}") from exc

    def disconnect(self) -> None:
        """Close the IxNetwork session.  Idempotent."""
        if self._session is not None:
            try:
                self._ixnetwork.NewConfig()
            except Exception:
                self._logger.debug("Error resetting config", exc_info=True)
            self._session = None
            self._ixnetwork = None
            self._stream_map.clear()
            self._logger.info("Disconnected from IxNetwork")

    def configure_stream(self, profile: TrafficProfile) -> str:
        """Create a traffic item from the given profile.

        Args:
            profile: Traffic stream configuration.

        Returns:
            Stream handle (the profile name).

        """
        self._ensure_connected()
        try:
            traffic = self._ixnetwork.Traffic
            traffic_item = traffic.TrafficItem.add(
                Name=profile.name,
                TrafficType="ipv4",
                BiDirectional=False,
            )

            traffic_item.EndpointSet.add(
                Sources=self._ixnetwork.Vport.find().Protocols.find(),
                Destinations=self._ixnetwork.Vport.find().Protocols.find(),
            )

            config_element = traffic_item.ConfigElement.find()
            config_element.FrameSize.FixedSize = profile.frame_size
            config_element.FrameRate.Type = "framesPerSecond"
            config_element.FrameRate.Rate = profile.rate_pps

            if profile.duration_seconds > 0:
                config_element.TransmissionControl.Type = "fixedDuration"
                config_element.TransmissionControl.Duration = profile.duration_seconds
            else:
                config_element.TransmissionControl.Type = "continuous"

            traffic_item.Generate()
            self._stream_map[profile.name] = traffic_item
            self._logger.info("Configured stream '%s'", profile.name)
            return profile.name

        except Exception as exc:
            self._logger.error("Failed to configure stream: %s", exc)
            raise RuntimeError(f"Stream configuration failed: {exc}") from exc

    def start_traffic(self, stream_id: str | None = None) -> None:
        """Start traffic transmission.

        Args:
            stream_id: Specific stream to start; starts all if omitted.

        """
        self._ensure_connected()
        try:
            if stream_id and stream_id in self._stream_map:
                self._stream_map[stream_id].Enabled = True
            self._ixnetwork.Traffic.Apply()
            self._ixnetwork.Traffic.Start()
            time.sleep(TRAFFIC_START_DELAY)
            self._logger.info("Traffic started")
        except Exception as exc:
            self._logger.error("Failed to start traffic: %s", exc)
            raise RuntimeError(f"Traffic start failed: {exc}") from exc

    def stop_traffic(self, stream_id: str | None = None) -> None:
        """Stop traffic transmission.

        Args:
            stream_id: Specific stream to stop; stops all if omitted.

        """
        self._ensure_connected()
        try:
            self._ixnetwork.Traffic.Stop()
            self._logger.info("Traffic stopped")
        except Exception as exc:
            self._logger.error("Failed to stop traffic: %s", exc)
            raise RuntimeError(f"Traffic stop failed: {exc}") from exc

    def get_statistics(self, stream_id: str | None = None) -> list[TrafficStats]:
        """Collect traffic statistics from IxNetwork.

        Args:
            stream_id: Optional stream filter.

        Returns:
            List of ``TrafficStats`` instances.

        """
        self._ensure_connected()
        stats_list: list[TrafficStats] = []
        try:
            flow_stats = self._ixnetwork.Statistics.Stat.find(Caption="Flow Statistics")
            if not flow_stats:
                return stats_list

            for row in flow_stats.Data.find():
                name = row.get("Traffic Item", "unknown")
                if stream_id and name != stream_id:
                    continue

                tx_frames = int(row.get("Tx Frames", 0))
                rx_frames = int(row.get("Rx Frames", 0))
                loss = tx_frames - rx_frames
                loss_pct = (loss / tx_frames * 100) if tx_frames > 0 else 0.0

                stats_list.append(
                    TrafficStats(
                        stream_name=name,
                        tx_frames=tx_frames,
                        rx_frames=rx_frames,
                        tx_rate_pps=float(row.get("Tx Rate (fps)", 0)),
                        rx_rate_pps=float(row.get("Rx Rate (fps)", 0)),
                        loss_frames=loss,
                        loss_percent=loss_pct,
                        min_latency_us=float(row.get("Store-Forward Min Latency (us)", 0)),
                        max_latency_us=float(row.get("Store-Forward Max Latency (us)", 0)),
                        avg_latency_us=float(row.get("Store-Forward Avg Latency (us)", 0)),
                        raw_data=dict(row),
                    )
                )
        except Exception as exc:
            self._logger.error("Failed to get statistics: %s", exc)

        return stats_list

    def clear_statistics(self) -> None:
        """Clear all traffic statistics counters."""
        self._ensure_connected()
        try:
            self._ixnetwork.ClearStats()
            self._logger.info("Statistics cleared")
        except Exception as exc:
            self._logger.warning("Failed to clear statistics: %s", exc)

    # -- Internal helpers ---------------------------------------------------

    def _assign_ports(self) -> None:
        """Map physical chassis ports to virtual ports."""
        try:
            port_map = self._session.PortMapAssistant()
            for chassis_ip, card, port in self._ports:
                port_map.Map(
                    IpAddress=chassis_ip,
                    CardId=card,
                    PortId=port,
                )
            port_map.Connect(ForceOwnership=True)
            self._logger.info("Assigned %d ports", len(self._ports))
        except Exception as exc:
            self._logger.error("Port assignment failed: %s", exc)
            raise RuntimeError(f"Port assignment failed: {exc}") from exc

    def _ensure_connected(self) -> None:
        """Raise if not connected to IxNetwork."""
        if self._ixnetwork is None:
            raise RuntimeError("Not connected to IxNetwork — call connect() first")
