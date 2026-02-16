"""Core module providing base abstractions, snapshot engine, and validation logic.

This module contains the foundational components of the network test automation
framework including the abstract base driver, snapshot diff engine, state
validators, and the custom exception hierarchy.
"""

from .exceptions import (
    CommandExecutionError,
    ConfigPushError,
    ConnectionError,
    InventoryError,
    NetworkTestError,
    SnapshotError,
    TopologyError,
    TriageError,
    ValidationError,
)

__all__ = [
    "CommandExecutionError",
    "ConfigPushError",
    "ConnectionError",
    "InventoryError",
    "NetworkTestError",
    "SnapshotError",
    "TopologyError",
    "TriageError",
    "ValidationError",
]
