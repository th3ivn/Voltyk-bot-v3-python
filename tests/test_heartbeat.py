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


def test_per_task_threshold_overrides_global():
    """A slow loop (hourly) must not be flagged stale under the fast global threshold."""
    heartbeat.reset()
    # Fast loop with no per-task threshold → falls back to global
    heartbeat.register("fast")
    # Slow loop with 2h threshold
    heartbeat.register("slow", threshold_s=7200.0)

    now = time.monotonic()
    # Force both beats to be 1 hour old
    heartbeat._beats["fast"] = now - 3600.0
    heartbeat._beats["slow"] = now - 3600.0

    stale = heartbeat.stale_tasks(threshold_s=300.0)
    # fast: age 3600 > 300 (global) → stale
    # slow: age 3600 < 7200 (per-task override) → not stale
    assert stale == ["fast"]


def test_register_without_threshold_preserves_existing():
    """Re-registering the same name without a threshold must not clobber
    an already-configured per-task threshold (defensive re-registration
    from the loop itself after app-level pre-registration)."""
    heartbeat.reset()
    heartbeat.register("slow", threshold_s=7200.0)
    # Re-register as if from inside the loop — no explicit threshold
    heartbeat.register("slow")

    now = time.monotonic()
    heartbeat._beats["slow"] = now - 3600.0

    # Still honours 7200s threshold, not the 300s global default
    assert heartbeat.stale_tasks(threshold_s=300.0) == []


def test_register_with_explicit_none_falls_back_to_global():
    heartbeat.reset()
    heartbeat.register("x", threshold_s=7200.0)
    heartbeat.register("x", threshold_s=None)  # explicit reset to global

    now = time.monotonic()
    heartbeat._beats["x"] = now - 3600.0

    assert heartbeat.stale_tasks(threshold_s=300.0) == ["x"]
