from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Region:
    name: str
    code: str


REGIONS: dict[str, Region] = {
    "kyiv": Region(name="Київ", code="kyiv"),
    "kyiv-region": Region(name="Київщина", code="kyiv-region"),
    "dnipro": Region(name="Дніпропетровщина", code="dnipro"),
    "odesa": Region(name="Одещина", code="odesa"),
}

GROUPS = [1, 2, 3, 4, 5, 6]
SUBGROUPS = [1, 2]

# Standard queues 1.1 — 6.2  (12 items)
QUEUES: list[str] = [f"{g}.{s}" for g in GROUPS for s in SUBGROUPS]

# Kyiv queues: 1.1—6.2 (12) + 7.1—60.1 (54) = 66 total
KYIV_QUEUES: list[str] = QUEUES.copy() + [f"{i}.1" for i in range(7, 61)]

REGION_QUEUES: dict[str, list[str]] = {
    "kyiv": KYIV_QUEUES,
    "kyiv-region": QUEUES,
    "dnipro": QUEUES,
    "odesa": QUEUES,
}


def get_queues_for_region(region_code: str) -> list[str]:
    return REGION_QUEUES.get(region_code, QUEUES)
