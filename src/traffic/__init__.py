"""Traffic generation abstractions and vendor implementations.

Provides a strategy interface for traffic generators and a concrete
implementation for Keysight/Ixia IxNetwork via the REST API.
"""

from .ixia_client import IxiaClient
from .traffic_generator import TrafficGenerator, TrafficProfile, TrafficStats

__all__ = ["IxiaClient", "TrafficGenerator", "TrafficProfile", "TrafficStats"]
