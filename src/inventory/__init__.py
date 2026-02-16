"""Nornir-based inventory management for the network test automation framework.

Provides a unified interface for loading, querying, and managing the
device inventory that feeds into the driver factory and test runners.
"""

from .inventory_manager import InventoryManager

__all__ = ["InventoryManager"]
