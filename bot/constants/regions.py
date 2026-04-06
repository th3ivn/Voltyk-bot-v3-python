from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Region:
    code: str
    name: str


REGIONS: dict[str, Region] = {
    "kyiv": Region(code="kyiv", name="Київ"),
    "kyiv-region": Region(code="kyiv-region", name="Київщина"),
    "dnipro": Region(code="dnipro", name="Дніпропетровщина"),
    "odesa": Region(code="odesa", name="Одещина"),
}


STANDARD_QUEUES: list[str] = [f"{g}.{s}" for g in range(1, 7) for s in (1, 2)]

KYIV_EXTRA_QUEUES: list[str] = [f"{q}.1" for q in range(7, 61)]

KYIV_QUEUES: list[str] = STANDARD_QUEUES + KYIV_EXTRA_QUEUES

REGION_QUEUES: dict[str, list[str]] = {
    "kyiv": KYIV_QUEUES,
    "kyiv-region": STANDARD_QUEUES,
    "dnipro": STANDARD_QUEUES,
    "odesa": STANDARD_QUEUES,
}
