"""Pre/post network state capture, persistence, and structured diff engine.

The ``SnapshotEngine`` orchestrates snapshot capture across multiple devices,
stores them on disk as JSON, and computes deterministic diffs that downstream
validators and reporters can consume.

Usage::

    engine = SnapshotEngine(storage_dir=Path("./snapshots"))
    pre = engine.capture(driver, "pre-change")
    # ... perform change ...
    post = engine.capture(driver, "post-change")
    diff = engine.diff(pre, post)
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from .base_driver import BaseDriver, DiffEntry, Snapshot, SnapshotDiff
from .exceptions import SnapshotError

logger = logging.getLogger(__name__)

DEFAULT_STORAGE_DIR = Path("snapshots")


class SnapshotEngine:
    """Manage the lifecycle of device-state snapshots.

    Captures full device state through a ``BaseDriver``, persists snapshots
    as JSON files, and provides a deterministic diff engine for comparing
    pre/post states.

    Args:
        storage_dir: Directory where snapshot JSON files are written.

    """

    def __init__(self, storage_dir: Path = DEFAULT_STORAGE_DIR) -> None:
        """Initialize the snapshot engine with a storage directory."""
        self._storage_dir = storage_dir
        self._storage_dir.mkdir(parents=True, exist_ok=True)
        self._logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

    # -- Public API ---------------------------------------------------------

    def capture(self, driver: BaseDriver, snapshot_id: str) -> Snapshot:
        """Capture and persist a device-state snapshot.

        Args:
            driver: An open driver connection to the target device.
            snapshot_id: Human-readable label for this snapshot.

        Returns:
            The captured ``Snapshot`` instance.

        Raises:
            SnapshotError: If capture or persistence fails.

        """
        self._logger.info("Capturing snapshot '%s' from %s", snapshot_id, driver.hostname)
        try:
            snapshot = driver.take_snapshot(snapshot_id)
            self._persist(snapshot)
            return snapshot
        except SnapshotError:
            raise
        except Exception as exc:
            raise SnapshotError(
                f"Snapshot capture failed for '{snapshot_id}'",
                device=driver.hostname,
                details={"error": str(exc)},
            ) from exc

    def capture_multiple(self, drivers: list[BaseDriver], snapshot_id: str) -> dict[str, Snapshot]:
        """Capture snapshots from multiple devices.

        Args:
            drivers: List of connected drivers.
            snapshot_id: Common label applied to all snapshots.

        Returns:
            Mapping of hostname to its ``Snapshot``.

        """
        results: dict[str, Snapshot] = {}
        for driver in drivers:
            results[driver.hostname] = self.capture(driver, snapshot_id)
        return results

    def load(self, device: str, snapshot_id: str) -> Snapshot:
        """Load a previously-persisted snapshot from disk.

        Args:
            device: Hostname of the device.
            snapshot_id: Label used when the snapshot was captured.

        Returns:
            The deserialized ``Snapshot``.

        Raises:
            SnapshotError: If the file is missing or corrupt.

        """
        path = self._snapshot_path(device, snapshot_id)
        if not path.exists():
            raise SnapshotError(
                f"Snapshot file not found: {path}",
                device=device,
            )
        try:
            return Snapshot.from_json(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, TypeError, KeyError) as exc:
            raise SnapshotError(
                f"Corrupt snapshot file: {path}",
                device=device,
                details={"error": str(exc)},
            ) from exc

    def diff(self, pre: Snapshot, post: Snapshot) -> SnapshotDiff:
        """Compute a structured diff between two snapshots.

        Iterates over every data category and records additions, removals,
        and value changes.

        Args:
            pre: The baseline (before-change) snapshot.
            post: The comparison (after-change) snapshot.

        Returns:
            A ``SnapshotDiff`` instance with categorized differences.

        """
        self._logger.info(
            "Computing diff: %s (%s) vs %s (%s)",
            pre.snapshot_id,
            pre.device,
            post.snapshot_id,
            post.device,
        )
        result = SnapshotDiff(
            pre_id=pre.snapshot_id,
            post_id=post.snapshot_id,
            device=pre.device,
        )
        categories: list[tuple[str, dict[str, Any], dict[str, Any]]] = [
            ("bgp_neighbors", pre.bgp_neighbors, post.bgp_neighbors),
            ("interfaces", pre.interfaces, post.interfaces),
            ("routing_table", pre.routing_table, post.routing_table),
            ("lldp_neighbors", pre.lldp_neighbors, post.lldp_neighbors),
            ("evpn_routes", pre.evpn_routes, post.evpn_routes),
        ]
        for category, pre_data, post_data in categories:
            self._diff_category(result, category, pre_data, post_data)

        self._logger.info(
            "Diff complete: +%d / -%d / ~%d",
            len(result.added),
            len(result.removed),
            len(result.changed),
        )
        return result

    def diff_multiple(
        self,
        pre_snapshots: dict[str, Snapshot],
        post_snapshots: dict[str, Snapshot],
    ) -> dict[str, SnapshotDiff]:
        """Compute diffs for multiple devices.

        Args:
            pre_snapshots: Mapping of hostname to pre-change snapshot.
            post_snapshots: Mapping of hostname to post-change snapshot.

        Returns:
            Mapping of hostname to ``SnapshotDiff``.

        """
        results: dict[str, SnapshotDiff] = {}
        common_hosts = set(pre_snapshots.keys()) & set(post_snapshots.keys())
        for host in sorted(common_hosts):
            results[host] = self.diff(pre_snapshots[host], post_snapshots[host])
        return results

    def list_snapshots(self, device: str | None = None) -> list[Path]:
        """List snapshot files, optionally filtered by device.

        Args:
            device: If provided, only list snapshots for this hostname.

        Returns:
            Sorted list of snapshot file paths.

        """
        pattern = f"{device}_*.json" if device else "*.json"
        return sorted(self._storage_dir.glob(pattern))

    # -- Internal helpers ---------------------------------------------------

    def _persist(self, snapshot: Snapshot) -> Path:
        """Write a snapshot to disk as JSON.

        Args:
            snapshot: The snapshot to persist.

        Returns:
            Path to the written file.

        """
        path = self._snapshot_path(snapshot.device, snapshot.snapshot_id)
        path.write_text(snapshot.to_json(), encoding="utf-8")
        self._logger.debug("Snapshot persisted to %s", path)
        return path

    def _snapshot_path(self, device: str, snapshot_id: str) -> Path:
        """Construct the filesystem path for a snapshot file."""
        safe_device = device.replace("/", "_").replace("\\", "_")
        safe_id = snapshot_id.replace("/", "_").replace("\\", "_")
        return self._storage_dir / f"{safe_device}_{safe_id}.json"

    @staticmethod
    def _diff_category(
        result: SnapshotDiff,
        category: str,
        pre_data: dict[str, Any],
        post_data: dict[str, Any],
    ) -> None:
        """Compare two dictionaries within a single category."""
        all_keys = sorted(set(pre_data.keys()) | set(post_data.keys()))
        for key in all_keys:
            pre_val = pre_data.get(key)
            post_val = post_data.get(key)

            if pre_val is None and post_val is not None:
                result.diffs.append(
                    DiffEntry(category=category, key=key, action="added", after=post_val)
                )
            elif pre_val is not None and post_val is None:
                result.diffs.append(
                    DiffEntry(category=category, key=key, action="removed", before=pre_val)
                )
            elif pre_val != post_val:
                result.diffs.append(
                    DiffEntry(
                        category=category,
                        key=key,
                        action="changed",
                        before=pre_val,
                        after=post_val,
                    )
                )
