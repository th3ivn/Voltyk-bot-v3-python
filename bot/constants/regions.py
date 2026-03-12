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


def _make_queues(start: float, end: float) -> list[str]:
    result = []
    g = start
    while g <= end:
        whole = int(g)
        frac = round(g - whole, 1)
        label = f"{whole}.{int(frac * 10)}"
        result.append(label)
        g = round(g + 0.1, 1)
    return result


STANDARD_QUEUES: list[str] = []
for group in range(1, 7):
    STANDARD_QUEUES.append(f"{group}.1")
    STANDARD_QUEUES.append(f"{group}.2")

KYIV_EXTRA_QUEUES: list[str] = []
for q in range(7, 61):
    KYIV_EXTRA_QUEUES.append(f"{q}.1")

KYIV_QUEUES: list[str] = STANDARD_QUEUES + KYIV_EXTRA_QUEUES

REGION_QUEUES: dict[str, list[str]] = {
    "kyiv": KYIV_QUEUES,
    "kyiv-region": STANDARD_QUEUES,
    "dnipro": STANDARD_QUEUES,
    "odesa": STANDARD_QUEUES,
}
