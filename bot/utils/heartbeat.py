"""Background-task heartbeat tracking.

Each long-running background loop (power monitor, schedule checker, reminder
checker, daily flush) calls :func:`beat` once per iteration.  The health
endpoint and Prometheus use :func:`snapshot` / :func:`stale_tasks` to verify
the loops are still progressing.

A single in-process map is sufficient because each replica has its own event
loop; cross-replica liveness is the orchestrator's (Kubernetes/Railway) job.
"""
from __future__ import annotations

import time

from bot.utils.metrics import BG_TASK_HEARTBEAT_AGE_SECONDS

_beats: dict[str, float] = {}


def register(name: str) -> None:
    """Record the initial heartbeat for *name* so it appears in snapshots even
    before its first loop iteration completes."""
    _beats[name] = time.monotonic()


def beat(name: str) -> None:
    """Record that background task *name* just completed a unit of work."""
    _beats[name] = time.monotonic()


def snapshot() -> dict[str, float]:
    """Return {name: seconds_since_last_beat} for every registered task."""
    now = time.monotonic()
    return {name: now - ts for name, ts in _beats.items()}


def stale_tasks(threshold_s: float) -> list[str]:
    """Return the names of tasks whose last heartbeat is older than *threshold_s*."""
    now = time.monotonic()
    return [name for name, ts in _beats.items() if (now - ts) > threshold_s]


def export_metrics() -> None:
    """Update the Prometheus gauge with the current per-task heartbeat age.

    Called from the /metrics handler to ensure the gauge is fresh at scrape
    time (Prometheus pulls rather than pushes).
    """
    now = time.monotonic()
    for name, ts in _beats.items():
        BG_TASK_HEARTBEAT_AGE_SECONDS.labels(name=name).set(now - ts)


def reset() -> None:
    """Wipe all heartbeats.  Used in tests and in graceful shutdown to prevent
    stale state if the process is reused (e.g. in-process reloads)."""
    _beats.clear()
