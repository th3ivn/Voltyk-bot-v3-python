"""Region and queue constants for Voltyk Bot.

Defines the supported regions, their display names, and the available
power-outage queues for each region.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Region definitions
# ---------------------------------------------------------------------------

REGIONS: dict[str, dict[str, str]] = {
    "kyiv": {"name": "Київ", "code": "kyiv"},
    "kyiv-region": {"name": "Київщина", "code": "kyiv-region"},
    "dnipro": {"name": "Дніпропетровщина", "code": "dnipro"},
    "odesa": {"name": "Одещина", "code": "odesa"},
}

REGION_CODE_TO_ID: dict[str, int] = {
    "kyiv": 1,
    "kyiv-region": 2,
    "dnipro": 3,
    "odesa": 4,
}

REGION_ID_TO_CODE: dict[int, str] = {v: k for k, v in REGION_CODE_TO_ID.items()}

# ---------------------------------------------------------------------------
# Queue definitions
# ---------------------------------------------------------------------------

GROUPS: list[int] = [1, 2, 3, 4, 5, 6]
SUBGROUPS: list[int] = [1, 2]

# Standard queues: 1.1, 1.2, 2.1, 2.2, ..., 6.1, 6.2
QUEUES: list[str] = [f"{g}.{s}" for g in GROUPS for s in SUBGROUPS]

# Kyiv has 66 queues: 1.1–6.2 (12) + 7.1–60.1 (54)
KYIV_QUEUES: list[str] = QUEUES + [f"{i}.1" for i in range(7, 61)]

REGION_QUEUES: dict[str, list[str]] = {
    "kyiv": KYIV_QUEUES,
    "kyiv-region": QUEUES,
    "dnipro": QUEUES,
    "odesa": QUEUES,
}

REGION_CODES: list[str] = list(REGIONS.keys())

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def get_queues_for_region(region_code: str) -> list[str]:
    """Return the list of queue strings for the given region code."""
    return REGION_QUEUES.get(region_code, QUEUES)
