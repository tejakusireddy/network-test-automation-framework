"""Unit tests for the SnapshotEngine."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, PropertyMock

import pytest

from src.core.base_driver import BaseDriver, DeviceInfo, Snapshot
from src.core.exceptions import SnapshotError
from src.core.snapshot_engine import SnapshotEngine


@pytest.fixture
def storage_dir(tmp_path: Path) -> Path:
    """Temporary directory for snapshot storage."""
    return tmp_path / "snapshots"


@pytest.fixture
def engine(storage_dir: Path) -> SnapshotEngine:
    """SnapshotEngine with temporary storage."""
    return SnapshotEngine(storage_dir=storage_dir)


@pytest.fixture
def mock_driver() -> MagicMock:
    """Mock driver with sample data."""
    driver = MagicMock(spec=BaseDriver)
    driver.hostname = "spine1"
    driver.take_snapshot.return_value = Snapshot(
        snapshot_id="test",
        device="spine1",
        bgp_neighbors={"10.0.0.1": {"state": "established"}},
        interfaces={"et-0/0/0": {"oper_status": "up"}},
        routing_table={"10.0.0.0/24": {"protocol": "ospf"}},
        lldp_neighbors={"et-0/0/0": {"remote_system": "spine2"}},
        evpn_routes={},
    )
    return driver


class TestSnapshotEngine:
    """Tests for SnapshotEngine capture, persistence, and diff."""

    def test_capture_persists_to_disk(
        self,
        engine: SnapshotEngine,
        mock_driver: MagicMock,
        storage_dir: Path,
    ) -> None:
        snapshot = engine.capture(mock_driver, "pre-change")
        assert snapshot.device == "spine1"
        files = list(storage_dir.glob("*.json"))
        assert len(files) == 1

    def test_load_roundtrip(
        self,
        engine: SnapshotEngine,
        mock_driver: MagicMock,
    ) -> None:
        engine.capture(mock_driver, "saved")
        # The mock returns snapshot_id="test", but persistence uses the
        # capture-time snapshot_id from the Snapshot object. The file is
        # keyed by (device, snapshot.snapshot_id) — here snapshot_id="test".
        loaded = engine.load("spine1", "test")
        assert loaded.snapshot_id == "test"
        assert loaded.device == "spine1"
        assert "10.0.0.1" in loaded.bgp_neighbors

    def test_load_missing_file(self, engine: SnapshotEngine) -> None:
        with pytest.raises(SnapshotError, match="not found"):
            engine.load("ghost", "nonexistent")

    def test_load_corrupt_file(
        self,
        engine: SnapshotEngine,
        storage_dir: Path,
    ) -> None:
        bad_file = storage_dir / "corrupt_bad.json"
        bad_file.write_text("not json at all", encoding="utf-8")
        with pytest.raises(SnapshotError, match="Corrupt"):
            engine.load("corrupt", "bad")

    def test_diff_no_changes(self, engine: SnapshotEngine) -> None:
        snap = Snapshot(snapshot_id="a", device="spine1")
        diff = engine.diff(snap, snap)
        assert not diff.has_changes

    def test_diff_detects_addition(self, engine: SnapshotEngine) -> None:
        pre = Snapshot(snapshot_id="a", device="spine1", bgp_neighbors={})
        post = Snapshot(
            snapshot_id="b",
            device="spine1",
            bgp_neighbors={"10.0.0.1": {"state": "established"}},
        )
        diff = engine.diff(pre, post)
        assert diff.has_changes
        assert len(diff.added) == 1

    def test_diff_detects_removal(self, engine: SnapshotEngine) -> None:
        pre = Snapshot(
            snapshot_id="a",
            device="spine1",
            bgp_neighbors={"10.0.0.1": {"state": "established"}},
        )
        post = Snapshot(snapshot_id="b", device="spine1", bgp_neighbors={})
        diff = engine.diff(pre, post)
        assert len(diff.removed) == 1

    def test_diff_detects_change(self, engine: SnapshotEngine) -> None:
        pre = Snapshot(
            snapshot_id="a",
            device="spine1",
            bgp_neighbors={"10.0.0.1": {"state": "active"}},
        )
        post = Snapshot(
            snapshot_id="b",
            device="spine1",
            bgp_neighbors={"10.0.0.1": {"state": "established"}},
        )
        diff = engine.diff(pre, post)
        assert len(diff.changed) == 1

    def test_capture_multiple(self, engine: SnapshotEngine) -> None:
        drivers = []
        for name in ["spine1", "spine2"]:
            d = MagicMock(spec=BaseDriver)
            d.hostname = name
            d.take_snapshot.return_value = Snapshot(snapshot_id="bulk", device=name)
            drivers.append(d)

        results = engine.capture_multiple(drivers, "bulk")
        assert len(results) == 2
        assert "spine1" in results
        assert "spine2" in results

    def test_list_snapshots(
        self,
        engine: SnapshotEngine,
        mock_driver: MagicMock,
    ) -> None:
        engine.capture(mock_driver, "snap-a")
        mock_driver.take_snapshot.return_value = Snapshot(snapshot_id="snap-b", device="spine1")
        engine.capture(mock_driver, "snap-b")
        files = engine.list_snapshots(device="spine1")
        assert len(files) == 2
