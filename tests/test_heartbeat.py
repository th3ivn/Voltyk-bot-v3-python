"""Tests for bot.utils.heartbeat — background-task liveness registry."""
from __future__ import annotations

import time
from unittest.mock import patch

from bot.utils import heartbeat


def test_register_and_snapshot_returns_zero_age():
    heartbeat.reset()
    heartbeat.register("alpha")
    snap = heartbeat.snapshot()
    assert "alpha" in snap
    assert snap["alpha"] >= 0.0
    assert snap["alpha"] < 1.0  # just registered


def test_beat_refreshes_timestamp():
    heartbeat.reset()
    heartbeat.register("alpha")
    # Fake a 100-second-old registration
    with patch.object(heartbeat, "_beats", {"alpha": time.monotonic() - 100.0}):
        heartbeat.beat("alpha")
        assert heartbeat.snapshot()["alpha"] < 1.0


def test_stale_tasks_returns_only_old_ones():
    heartbeat.reset()
    now = time.monotonic()
    heartbeat._beats["old"] = now - 600.0
    heartbeat._beats["fresh"] = now

    stale = heartbeat.stale_tasks(threshold_s=300.0)
    assert stale == ["old"]

    stale_all = heartbeat.stale_tasks(threshold_s=60.0)
    assert set(stale_all) == {"old"}

    stale_none = heartbeat.stale_tasks(threshold_s=1000.0)
    assert stale_none == []


def test_export_metrics_updates_gauge_per_task():
    heartbeat.reset()
    heartbeat.register("alpha")
    heartbeat.register("beta")

    with patch.object(heartbeat, "BG_TASK_HEARTBEAT_AGE_SECONDS") as mock_gauge:
        heartbeat.export_metrics()
        # labels() returns the inner metric object; set() records the value
        assert mock_gauge.labels.call_count == 2
        label_names = {c.kwargs["name"] for c in mock_gauge.labels.call_args_list}
        assert label_names == {"alpha", "beta"}


def test_reset_clears_all_beats():
    heartbeat.register("alpha")
    heartbeat.register("beta")
    heartbeat.reset()
    assert heartbeat.snapshot() == {}
