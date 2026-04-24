"""Background-task heartbeat tracking.

Each long-running background loop (power monitor, schedule checker, reminder
checker, daily flush) calls :func:`beat` once per iteration.  The health
endpoint and Prometheus use :func:`snapshot` / :func:`stale_tasks` to verify
the loops are still progressing.

A single in-process map is sufficient because each replica has its own event
loop; cross-replica liveness is the orchestrator's (Kubernetes/Railway) job.

Each task can register a **per-task staleness threshold**.  Fast loops (e.g.
power-monitor, 10-60s cadence) use the global default (typically 300s); slow
loops (hourly daily alert, once-daily flush) register a much larger threshold
so a healthy low-cadence loop does not flip ``/health`` to 503 and cause
liveness probes to restart the pod.
"""
from __future__ import annotations

import time

from bot.utils.metrics import BG_TASK_HEARTBEAT_AGE_SECONDS

_beats: dict[str, float] = {}
# None → use the caller-supplied global threshold in stale_tasks().
_thresholds: dict[str, float | None] = {}

_UNSET: object = object()


def register(name: str, threshold_s: float | None | object = _UNSET) -> None:
    """Record the initial heartbeat for *name*.

    *threshold_s* overrides the global staleness threshold passed to
    :func:`stale_tasks`.  Use a value that comfortably exceeds the loop's
    natural cadence (e.g. 2× cadence) to avoid false-positive restarts on
    slow daily loops.  Pass ``None`` explicitly to force fallback to the
    caller-supplied global.  Omit the argument to preserve a previously
    registered threshold — this lets individual loops re-register themselves
    at startup (defensive) without clobbering the centrally-configured
    threshold from :func:`bot.app.on_startup`.
    """
    _beats[name] = time.monotonic()
    if threshold_s is not _UNSET:
        _thresholds[name] = threshold_s  # type: ignore[assignment]
    else:
        _thresholds.setdefault(name, None)


def beat(name: str) -> None:
    """Record that background task *name* just completed a unit of work."""
    _beats[name] = time.monotonic()


def snapshot() -> dict[str, float]:
    """Return {name: seconds_since_last_beat} for every registered task."""
    now = time.monotonic()
    return {name: now - ts for name, ts in _beats.items()}


def stale_tasks(threshold_s: float) -> list[str]:
    """Return names of tasks whose heartbeat is older than their effective threshold.

    A task's effective threshold is ``_thresholds[name]`` if set, else the
    caller-supplied *threshold_s*.  This lets fast loops share a tight global
    threshold while slow (daily/hourly) loops use a loose per-task threshold
    without dragging the health endpoint into false-positives.
    """
    now = time.monotonic()
    stale: list[str] = []
    for name, ts in _beats.items():
        effective = _thresholds.get(name) or threshold_s
        if (now - ts) > effective:
            stale.append(name)
    return stale


def export_metrics() -> None:
    """Update the Prometheus gauge with the current per-task heartbeat age.

    Called from the /metrics handler to ensure the gauge is fresh at scrape
    time (Prometheus pulls rather than pushes).
    """
    now = time.monotonic()
    for name, ts in _beats.items():
        BG_TASK_HEARTBEAT_AGE_SECONDS.labels(name=name).set(now - ts)


def reset() -> None:
    """Wipe all heartbeats and thresholds.  Used in tests and in graceful
    shutdown to prevent stale state if the process is reused (e.g. in-process
    reloads)."""
    _beats.clear()
    _thresholds.clear()
