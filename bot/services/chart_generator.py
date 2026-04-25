"""Generate schedule table PNG charts using SVG + CairoSVG.

SVG markup is built programmatically then rendered to PNG at 2× resolution
via CairoSVG (Cairo graphics engine — the same used by Firefox and Inkscape).

CPU-bound rendering runs in a dedicated bounded ``ThreadPoolExecutor``
(``_chart_executor``) so that chart renders cannot saturate the default
executor shared by the rest of the application (Alembic migrations, etc.).
"""
from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from bot.constants.regions import REGIONS
from bot.utils.logger import get_logger

logger = get_logger(__name__)

# Dedicated bounded pool for CPU-heavy CairoSVG rendering.
# max_workers=4 ensures at most 4 concurrent renders — sufficient because
# the two-level cache (L1 in-memory + L2 Redis) means >99% of user requests
# are served from cache without any rendering.  This also prevents chart
# renders from saturating the default executor used by other bot subsystems
# (Alembic migrations, etc.).
_chart_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="chart-render")

KYIV_TZ = ZoneInfo("Europe/Kyiv")

MONTHS_UK = [
    "січня", "лютого", "березня", "квітня", "травня", "червня",
    "липня", "серпня", "вересня", "жовтня", "листопада", "грудня",
]

# ── Layout (logical pixels at 1×) ─────────────────────────────────────────────
# cairosvg renders at OUTPUT_SCALE× → OUTPUT_SCALE * IMG_W physical pixels.
OUTPUT_SCALE = 5.0

IMG_W    = 1193   # 1127 table + 2×33 padding
PAD_X    = 33
PAD_Y    = 33     # equal to PAD_X — uniform margins on all sides
LABEL_W  = 143
CELL_W   = 41    # 24 × 41 = 984;  984 + 143 = 1127 = 1193 − 2×33 ✓
TITLE_H  = 66    # slightly taller to keep visual balance after scaling
GAP      = 13
HEADER_H = 79
ROW_H    = 51
LEGEND_H = 51

TABLE_W   = LABEL_W + 24 * CELL_W  # 1127
LABEL_PAD = 10   # left padding inside the label column

# ── Colors ────────────────────────────────────────────────────────────────────
C_BG        = "#F1F4F9"   # overall image + header-row background
C_TABLE_BG  = "#FFFFFF"
C_HDR_BG    = "#F1F4F9"   # same as page bg (per spec §2)
C_BORDER    = "#D2DAE2"
C_BORDER_DK = "#B4BEC8"
C_TEXT      = "#1C2228"
C_TEXT_MID  = "#58606C"

CELL_ON    = "#FFFFFF"
CELL_OFF   = "#DADDE4"    # "no power" cell background (per spec §4)

# Badge styles (blue-gray gradient, per spec §8)
C_BADGE_G1  = "#DDE7F4"   # gradient top
C_BADGE_G2  = "#CAD7E8"   # gradient bottom
C_BADGE_BD  = "#BCCADE"   # border
C_BADGE_TXT  = "#3A4556"   # text
C_WATERMARK  = "#B8C2CC"   # subtle watermark text
BADGE_H     = 53
BADGE_FS    = 20.4
BADGE_PAD_H = 26          # horizontal padding inside badge
ICON_SCALE  = 0.95        # icon drawn at 95% of cell size, centered
NO_OUTAGES_TEXT = "Відключення відсутні на сайті ДТЕК"
NO_OUTAGES_FONT_SIZE = 18.7  # +20% from previous 15.6px for better readability
SECTION_LABEL_FONT_SIZE = 16.8  # +20% from 14px
HOUR_LABEL_FONT_SIZE = 15.6  # +20% from 13px
DAY_LABEL_FONT_SIZE = 15.6  # +20% from 13px
LEGEND_LABEL_FONT_SIZE = 14.4  # +20% from 12px

# ── Icon path data (viewBox 0 0 20 20) ───────────────────────────────────────
# Slashed bolt (represents "no power" / left half of split icon).
_P_SLASH = (
    "M18.75 17.8688L2.13125 1.25L1.25 2.13125L5.25 6.1375L4.375 9.85625"
    "C4.35295 9.94941 4.35259 10.0464 4.37396 10.1397C4.39532 10.233"
    " 4.43785 10.3202 4.49824 10.3945C4.55863 10.4688 4.63529 10.5282"
    " 4.72228 10.5682C4.80928 10.6081 4.9043 10.6276 5 10.625H8.01875"
    "L6.875 18.0313C6.85435 18.1685 6.88001 18.3088 6.94791 18.4299"
    "C7.01581 18.551 7.1221 18.646 7.25 18.7C7.32944 18.7323 7.41426 18.7492"
    " 7.5 18.75C7.59545 18.7498 7.68958 18.7277 7.77516 18.6854"
    "C7.86075 18.6432 7.93553 18.5819 7.99375 18.5063L12.1687 13.05"
    "L17.8688 18.75L18.75 17.8688Z"
)
# Top complement of the slashed bolt.
_P_TOP = (
    "M14.0813 10.5437L16.1188 7.88124C16.1844 7.79243 16.2254 7.68781"
    " 16.2374 7.57802C16.2495 7.46823 16.2323 7.35721 16.1875 7.25624"
    "C16.1405 7.14521 16.0624 7.05014 15.9626 6.9825C15.8628 6.91485"
    " 15.7455 6.87752 15.625 6.87499H12.6563L13.75 2.01249"
    "C13.7707 1.92026 13.7702 1.82452 13.7486 1.7325C13.7269 1.64049"
    " 13.6847 1.55458 13.625 1.48124C13.5649 1.40706 13.4885 1.34765"
    " 13.4019 1.30756C13.3152 1.26747 13.2205 1.24778 13.125 1.24999"
    "H6.875C6.73138 1.24615 6.59082 1.29191 6.47699 1.37957"
    "C6.36315 1.46722 6.28299 1.59141 6.25 1.73124L6.0625 2.54374"
    "L14.0813 10.5437Z"
)
# Clean bolt (no slash — represents "power available").
_P_CLEAN = (
    "M6.875 1.25H13.125C13.2205 1.24779 13.3152 1.26748 13.4019 1.30757"
    "C13.4885 1.34766 13.5649 1.40707 13.625 1.48125C13.6847 1.55459"
    " 13.7269 1.6405 13.7486 1.73251C13.7702 1.82453 13.7707 1.92027"
    " 13.75 2.0125L12.6563 6.875H15.625C15.7455 6.87753 15.8628 6.91486"
    " 15.9626 6.98251C16.0624 7.05015 16.1405 7.14522 16.1875 7.25625"
    "C16.2323 7.35722 16.2495 7.46824 16.2374 7.57803C16.2254 7.68782"
    " 16.1844 7.79244 16.1188 7.88125L7.99375 18.5063C7.93553 18.5819"
    " 7.86075 18.6432 7.77516 18.6854C7.68958 18.7277 7.59545 18.7498"
    " 7.5 18.75C7.41426 18.7492 7.32944 18.7323 7.25 18.7"
    "C7.1221 18.646 7.01581 18.551 6.94791 18.4299C6.88001 18.3088"
    " 6.85435 18.1685 6.875 18.0313L8.01875 10.625H5"
    "C4.9043 10.6276 4.80928 10.6081 4.72228 10.5682C4.63529 10.5282"
    " 4.55863 10.4688 4.49824 10.3945C4.43785 10.3202 4.39532 10.233"
    " 4.37396 10.1397C4.35259 10.0464 4.35295 9.94942 4.375 9.85625"
    "L6.25 1.73125C6.28299 1.59142 6.36315 1.46723 6.47699 1.37958"
    "C6.59082 1.29192 6.73138 1.24616 6.875 1.25Z"
)

# Font family (DejaVu Sans installed via fonts-dejavu-core in Dockerfile)
FONT = "DejaVu Sans, Liberation Sans, sans-serif"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _esc(text: str) -> str:
    return (
        text
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _parse_dt(v) -> datetime:
    if isinstance(v, str):
        return datetime.fromisoformat(v).astimezone(KYIV_TZ)
    return v.astimezone(KYIV_TZ)


def _day_label(dt: datetime) -> str:
    return f"{dt.day} {MONTHS_UK[dt.month - 1]}"


def _get_hour_states(events: list[dict], day_start: datetime) -> list[str]:
    half_map = bytearray(48)
    for ev in events:
        a = max(0, int((_parse_dt(ev["start"]) - day_start).total_seconds() / 1800))
        b = min(48, int((_parse_dt(ev["end"]) - day_start).total_seconds() / 1800))
        val = 2 if ev.get("isPossible") else 1
        for i in range(a, b):
            half_map[i] = val

    result = []
    for h in range(24):
        f, s = half_map[h * 2], half_map[h * 2 + 1]
        if f == 0 and s == 0:
            result.append("on")
        elif f == 1 and s == 1:
            result.append("no")
        elif f == 2 and s == 2:
            result.append("maybe")
        elif f == 1 and s == 0:
            result.append("nfirst")
        elif f == 0 and s == 1:
            result.append("nsecond")
        elif f == 2 and s == 0:
            result.append("mfirst")
        elif f == 0 and s == 2:
            result.append("msecond")
        else:
            result.append("no" if 1 in (f, s) else "maybe")
    return result


# ── Icon helpers ──────────────────────────────────────────────────────────────

def _icon_svg(x: float, y: float, w: float, h: float, paths: list[tuple[str, str]]) -> str:
    """Embed icon paths into a nested <svg> that fills the given rect.

    paths is a list of (path_d, fill_color).
    viewBox 0 0 20 20 matches the source icon coordinates.
    xMidYMid meet keeps the bolt proportional — the cell background
    rect (drawn separately) covers any letterbox gap.
    """
    iw = w * ICON_SCALE
    ih = h * ICON_SCALE
    ix = x + (w - iw) / 2
    iy = y + (h - ih) / 2
    inner = "".join(f'<path d="{d}" fill="{c}"/>' for d, c in paths)
    return (
        f'<svg x="{ix:.2f}" y="{iy:.2f}" width="{iw:.2f}" height="{ih:.2f}" '
        f'viewBox="0 0 20 20" preserveAspectRatio="xMidYMid meet" overflow="hidden">'
        f'{inner}</svg>'
    )


def _half_icon_svg(
    x: float, y: float, w: float, h: float,
    left_paths: list[tuple[str, str]],
    right_paths: list[tuple[str, str]],
) -> str:
    """Render a split (left/right) icon using nested <svg overflow="hidden">.

    Both halves scale the full 20×20 icon to fit the whole cell (w×h) with
    "meet" centering, then each nested <svg> clips its content to half-width
    via overflow="hidden". The transform inside each nested SVG is expressed
    in local coordinates (relative to the nested SVG's own origin), so the
    icon appears seamlessly split at x=10 of the 20×20 viewBox regardless of
    whether the scale is limited by width or height (cells vs legend swatches).
    No clipPath IDs are needed, avoiding any CairoSVG defs-placement issues.
    """
    hw = w / 2
    # Scale icon (20×20) to ICON_SCALE fraction of the cell with "meet"
    scale = min(w * ICON_SCALE / 20.0, h * ICON_SCALE / 20.0)
    # Icon's top-left in global coordinates (centered in full cell)
    ix = x + (w - 20.0 * scale) / 2.0
    iy = y + (h - 20.0 * scale) / 2.0

    out: list[str] = []

    if left_paths:
        # Local transform: icon origin relative to the nested SVG's x,y
        tx = ix - x
        ty = iy - y
        inner = "".join(f'<path d="{d}" fill="{c}"/>' for d, c in left_paths)
        out.append(
            f'<svg x="{x:.2f}" y="{y:.2f}" width="{hw:.2f}" height="{h:.2f}" overflow="hidden">'
            f'<g transform="translate({tx:.3f},{ty:.3f}) scale({scale:.4f})">{inner}</g>'
            f'</svg>'
        )

    if right_paths:
        # The icon's global x is ix; relative to the right half's origin (x+hw)
        tx = ix - (x + hw)
        ty = iy - y
        inner = "".join(f'<path d="{d}" fill="{c}"/>' for d, c in right_paths)
        out.append(
            f'<svg x="{x + hw:.2f}" y="{y:.2f}" width="{hw:.2f}" height="{h:.2f}" overflow="hidden">'
            f'<g transform="translate({tx:.3f},{ty:.3f}) scale({scale:.4f})">{inner}</g>'
            f'</svg>'
        )

    return "\n".join(out)


# ── Cell renderer ─────────────────────────────────────────────────────────────

_SLASH_PATHS  = [(_P_SLASH, "#000000"), (_P_TOP, "#000000")]
_CLEAN_PATHS  = [(_P_CLEAN, "#F2B200")]
_MAYBE_PATHS  = [(_P_SLASH, "#8899AA"), (_P_TOP, "#8899AA")]


def _cell_svg(x: float, y: float, state: str) -> str:
    """Return SVG markup for one data cell (CELL_W × ROW_H)."""
    w, h = float(CELL_W), float(ROW_H)
    hw   = w / 2
    out: list[str] = []

    if state == "on":
        out.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" fill="{CELL_ON}"/>')

    elif state in ("no", "maybe"):
        bg = CELL_OFF
        out.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" fill="{bg}"/>')
        paths = _SLASH_PATHS if state == "no" else _MAYBE_PATHS
        out.append(_icon_svg(x, y, w, h, paths))

    elif state == "nfirst":
        # Left: definite off | Right: on
        out.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{hw:.1f}" height="{h:.1f}" fill="{CELL_OFF}"/>')
        out.append(f'<rect x="{x+hw:.1f}" y="{y:.1f}" width="{hw:.1f}" height="{h:.1f}" fill="{CELL_ON}"/>')
        out.append(_half_icon_svg(x, y, w, h, _SLASH_PATHS, _CLEAN_PATHS))

    elif state == "mfirst":
        # Left: possible off (muted) | Right: on
        out.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{hw:.1f}" height="{h:.1f}" fill="{CELL_OFF}"/>')
        out.append(f'<rect x="{x+hw:.1f}" y="{y:.1f}" width="{hw:.1f}" height="{h:.1f}" fill="{CELL_ON}"/>')
        out.append(_half_icon_svg(x, y, w, h, _MAYBE_PATHS, []))

    elif state == "nsecond":
        # Left: on | Right: definite off
        out.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{hw:.1f}" height="{h:.1f}" fill="{CELL_ON}"/>')
        out.append(f'<rect x="{x+hw:.1f}" y="{y:.1f}" width="{hw:.1f}" height="{h:.1f}" fill="{CELL_OFF}"/>')
        out.append(_half_icon_svg(x, y, w, h, _CLEAN_PATHS, _SLASH_PATHS))

    elif state == "msecond":
        # Left: on | Right: possible off (muted)
        out.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{hw:.1f}" height="{h:.1f}" fill="{CELL_ON}"/>')
        out.append(f'<rect x="{x+hw:.1f}" y="{y:.1f}" width="{hw:.1f}" height="{h:.1f}" fill="{CELL_OFF}"/>')
        out.append(_half_icon_svg(x, y, w, h, [], _MAYBE_PATHS))

    else:
        out.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" fill="{CELL_ON}"/>')

    return "\n".join(out)


# ── Legend swatch renderer ────────────────────────────────────────────────────

def _legend_swatch(lx: float, leg_y: float, state: str, sw: float, sh: float) -> str:
    """Return SVG for one legend swatch (sw × sh)."""
    hw = sw / 2
    out: list[str] = []

    if state == "on":
        out.append(f'<rect x="{lx:.1f}" y="{leg_y:.1f}" width="{sw:.1f}" height="{sh:.1f}" fill="{CELL_ON}" stroke="{C_BORDER}" stroke-width="1"/>')

    elif state in ("no", "maybe"):
        bg = CELL_OFF
        out.append(f'<rect x="{lx:.1f}" y="{leg_y:.1f}" width="{sw:.1f}" height="{sh:.1f}" fill="{bg}"/>')
        paths = _SLASH_PATHS if state == "no" else _MAYBE_PATHS
        out.append(_icon_svg(lx, leg_y, sw, sh, paths))

    elif state == "nfirst":
        out.append(f'<rect x="{lx:.1f}" y="{leg_y:.1f}" width="{hw:.1f}" height="{sh:.1f}" fill="{CELL_OFF}"/>')
        out.append(f'<rect x="{lx+hw:.1f}" y="{leg_y:.1f}" width="{hw:.1f}" height="{sh:.1f}" fill="{CELL_ON}" stroke="{C_BORDER}" stroke-width="0.5"/>')
        out.append(_half_icon_svg(lx, leg_y, sw, sh, _SLASH_PATHS, _CLEAN_PATHS))

    elif state == "nsecond":
        out.append(f'<rect x="{lx:.1f}" y="{leg_y:.1f}" width="{hw:.1f}" height="{sh:.1f}" fill="{CELL_ON}" stroke="{C_BORDER}" stroke-width="0.5"/>')
        out.append(f'<rect x="{lx+hw:.1f}" y="{leg_y:.1f}" width="{hw:.1f}" height="{sh:.1f}" fill="{CELL_OFF}"/>')
        out.append(_half_icon_svg(lx, leg_y, sw, sh, _CLEAN_PATHS, _SLASH_PATHS))

    return "\n".join(out)


# ── SVG builder ───────────────────────────────────────────────────────────────

def _build_svg(region: str, queue: str, schedule_data: dict) -> str:  # noqa: PLR0914
    now = datetime.now(KYIV_TZ)
    today_start    = now.replace(hour=0, minute=0, second=0, microsecond=0)
    tomorrow_start = today_start + timedelta(days=1)
    day_after      = tomorrow_start + timedelta(days=1)

    events      = schedule_data.get("events", [])
    today_ev    = [e for e in events if today_start    <= _parse_dt(e["start"]) < tomorrow_start]
    tomorrow_ev = [e for e in events if tomorrow_start <= _parse_dt(e["start"]) < day_after]

    region_label    = REGIONS[region].name if region in REGIONS else region
    today_states    = _get_hour_states(today_ev,    today_start)
    tomorrow_states = _get_hour_states(tomorrow_ev, tomorrow_start)
    no_outages_rows = [len(today_ev) == 0, len(tomorrow_ev) == 0]

    table_h = HEADER_H + 2 * ROW_H
    table_y = PAD_Y + TITLE_H + GAP
    img_h   = table_y + table_h + GAP + LEGEND_H + PAD_Y

    p: list[str] = []

    # ── SVG root ──────────────────────────────────────────────────────────────
    p.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{IMG_W}" height="{img_h}" viewBox="0 0 {IMG_W} {img_h}">'
    )

    # ── Defs: table clip + badge gradient ─────────────────────────────────────
    p.append(
        f'<defs>'
        f'<clipPath id="tc">'
        f'<rect x="{PAD_X}" y="{table_y}" width="{TABLE_W}" height="{table_h}" rx="8"/>'
        f'</clipPath>'
        f'<linearGradient id="bdg" x1="0" y1="{PAD_Y}" x2="0" y2="{PAD_Y + BADGE_H}" '
        f'gradientUnits="userSpaceOnUse">'
        f'<stop offset="0" stop-color="{C_BADGE_G1}"/>'
        f'<stop offset="1" stop-color="{C_BADGE_G2}"/>'
        f'</linearGradient>'
        f'</defs>'
    )

    # ── Image background ──────────────────────────────────────────────────────
    p.append(f'<rect width="{IMG_W}" height="{img_h}" fill="{C_BG}"/>')

    # ── Header: two gradient badges ───────────────────────────────────────────
    # Parse update timestamp (contract: callers should pass normalized metadata).
    dtek_raw = schedule_data.get("dtek_updated_at")
    if not isinstance(dtek_raw, str) or not dtek_raw.strip():
        logger.warning(
            "Missing chart metadata dtek_updated_at for %s/%s; using emergency fallback", region, queue,
        )
        dtek_raw = now.strftime("%d.%m.%Y %H:%M")

    try:
        dtek_dt = datetime.strptime(dtek_raw, "%d.%m.%Y %H:%M")
        left_txt = _esc(f"Оновлення станом на {dtek_dt.strftime('%H:%M %d.%m.%Y')}")
    except ValueError:
        logger.warning(
            "Invalid chart metadata dtek_updated_at=%r for %s/%s; using emergency fallback", dtek_raw, region, queue,
        )
        dtek_dt = now
        left_txt = _esc(f"Оновлення станом на {dtek_dt.strftime('%H:%M %d.%m.%Y')}")

    right_txt = _esc(f"{region_label} • Черга: {queue}")

    # Badge width = estimated text width + horizontal padding
    # ~0.62 × font-size per character for bold DejaVu Cyrillic/digits
    def _bw(text: str) -> int:
        return max(210, int(len(text) * BADGE_FS * 0.62) + BADGE_PAD_H * 2)

    left_bw  = _bw(left_txt)
    right_bw = _bw(right_txt)
    # Ensure they fit within the table width without overlapping
    max_total = TABLE_W - 16
    if left_bw + right_bw > max_total:
        scale    = max_total / (left_bw + right_bw)
        left_bw  = int(left_bw  * scale)
        right_bw = int(right_bw * scale)

    badge_y  = PAD_Y
    left_bx  = PAD_X
    right_bx = PAD_X + TABLE_W - right_bw

    def _badge(bx: float, bw: int, text: str) -> str:
        cx = bx + bw / 2
        cy = badge_y + BADGE_H / 2
        return (
            f'<rect x="{bx:.1f}" y="{badge_y}" '
            f'width="{bw}" height="{BADGE_H}" '
            f'rx="11" fill="url(#bdg)" stroke="{C_BADGE_BD}" stroke-width="1"/>'
            f'<text x="{cx:.1f}" y="{cy:.1f}" '
            f'font-family="{FONT}" font-size="{BADGE_FS}" font-weight="bold" '
            f'fill="{C_BADGE_TXT}" text-anchor="middle" dominant-baseline="central">'
            f'{text}</text>'
        )

    p.append(_badge(left_bx,  left_bw,  left_txt))
    p.append(_badge(right_bx, right_bw, right_txt))

    # ── Table background (filled, rounded) ────────────────────────────────────
    p.append(
        f'<rect x="{PAD_X}" y="{table_y}" '
        f'width="{TABLE_W}" height="{table_h}" '
        f'rx="8" fill="{C_TABLE_BG}"/>'
    )

    # ── Clipped table contents ────────────────────────────────────────────────
    p.append('<g clip-path="url(#tc)">')

    # Header row background (same as page bg, per spec §2)
    p.append(
        f'<rect x="{PAD_X}" y="{table_y}" '
        f'width="{TABLE_W}" height="{HEADER_H}" fill="{C_HDR_BG}"/>'
    )

    # Data cells
    for row_i, states in enumerate([today_states, tomorrow_states]):
        row_y = table_y + HEADER_H + row_i * ROW_H
        # Label column — same background as header row
        p.append(
            f'<rect x="{PAD_X}" y="{row_y}" width="{LABEL_W}" '
            f'height="{ROW_H}" fill="{C_HDR_BG}"/>'
        )
        data_start_x = PAD_X + LABEL_W
        if no_outages_rows[row_i]:
            p.append(
                f'<rect x="{data_start_x}" y="{row_y}" '
                f'width="{24 * CELL_W}" height="{ROW_H}" fill="{CELL_ON}"/>'
            )
        else:
            for col_i, state in enumerate(states):
                cx = data_start_x + col_i * CELL_W
                p.append(_cell_svg(cx, row_y, state))

    # Horizontal grid lines (below header, between rows, below last row)
    for i in range(3):
        ly = table_y + HEADER_H + i * ROW_H
        p.append(
            f'<line x1="{PAD_X}" y1="{ly}" x2="{PAD_X + TABLE_W}" y2="{ly}" '
            f'stroke="{C_BORDER_DK}" stroke-width="1"/>'
        )

    # Vertical separator: label column (full height, darker)
    lsep = PAD_X + LABEL_W
    p.append(
        f'<line x1="{lsep}" y1="{table_y}" x2="{lsep}" y2="{table_y + table_h}" '
        f'stroke="{C_BORDER_DK}" stroke-width="1"/>'
    )

    # Vertical separators between hour columns in the header row.
    for col in range(1, 24):
        lx = PAD_X + LABEL_W + col * CELL_W
        p.append(
            f'<line x1="{lx}" y1="{table_y}" x2="{lx}" y2="{table_y + HEADER_H}" '
            f'stroke="{C_BORDER}" stroke-width="1"/>'
        )

    # Vertical separators for data rows with outage details.
    for row_i in range(2):
        if no_outages_rows[row_i]:
            continue
        row_y = table_y + HEADER_H + row_i * ROW_H
        for col in range(1, 24):
            lx = PAD_X + LABEL_W + col * CELL_W
            p.append(
                f'<line x1="{lx}" y1="{row_y}" x2="{lx}" y2="{row_y + ROW_H}" '
                f'stroke="{C_BORDER}" stroke-width="1"/>'
            )

    p.append('</g>')

    # ── Table outer border (drawn last — rounds off corners over content) ──────
    p.append(
        f'<rect x="{PAD_X}" y="{table_y}" '
        f'width="{TABLE_W}" height="{table_h}" '
        f'rx="8" fill="none" stroke="{C_BORDER_DK}" stroke-width="1"/>'
    )

    # ── Table text labels (outside clip — always fully visible) ───────────────
    hdr_mid  = table_y + HEADER_H / 2
    text_lx  = PAD_X + LABEL_PAD   # left-aligned start x for label column

    # "Часові проміжки" — two lines, left-aligned, vertically centered (per spec §3)
    # dominant-baseline="central" centers each glyph on its y; ±10 gives extra line gap.
    p.append(
        f'<text x="{text_lx}" y="{hdr_mid - 10:.1f}" '
        f'font-family="{FONT}" font-size="{SECTION_LABEL_FONT_SIZE}" font-weight="bold" '
        f'fill="{C_TEXT_MID}" dominant-baseline="central">Часові</text>'
    )
    p.append(
        f'<text x="{text_lx}" y="{hdr_mid + 10:.1f}" '
        f'font-family="{FONT}" font-size="{SECTION_LABEL_FONT_SIZE}" font-weight="bold" '
        f'fill="{C_TEXT_MID}" dominant-baseline="central">проміжки</text>'
    )

    # Rotated hour labels "00-01" … "23-24" — bold, larger (per spec §1)
    for h in range(24):
        label  = _esc(f"{h:02d}-{h + 1:02d}")
        col_cx = PAD_X + LABEL_W + h * CELL_W + CELL_W / 2
        col_cy = table_y + HEADER_H / 2
        p.append(
            f'<text transform="translate({col_cx:.1f},{col_cy:.1f}) rotate(-90)" '
            f'font-family="{FONT}" font-size="{HOUR_LABEL_FONT_SIZE}" font-weight="bold" '
            f'fill="{C_TEXT_MID}" text-anchor="middle" dominant-baseline="central">'
            f'{label}</text>'
        )

    # Date labels — left-aligned with padding (per spec §3)
    for row_i, dt in enumerate([today_start, tomorrow_start]):
        row_cy = table_y + HEADER_H + row_i * ROW_H + ROW_H / 2
        p.append(
            f'<text x="{text_lx}" y="{row_cy:.1f}" '
            f'font-family="{FONT}" font-size="{DAY_LABEL_FONT_SIZE}" font-weight="bold" '
            f'fill="{C_TEXT}" dominant-baseline="central">'
            f'{_esc(_day_label(dt))}</text>'
        )
        if no_outages_rows[row_i]:
            data_center_x = PAD_X + LABEL_W + (24 * CELL_W) / 2
            p.append(
                f'<text x="{data_center_x:.1f}" y="{row_cy:.1f}" '
                f'font-family="{FONT}" font-size="{NO_OUTAGES_FONT_SIZE}" font-weight="bold" '
                f'fill="{C_TEXT_MID}" text-anchor="middle" dominant-baseline="central">'
                f'{_esc(NO_OUTAGES_TEXT)}</text>'
            )

    # ── Legend ────────────────────────────────────────────────────────────────
    legend_items = [
        ("on",      "Світло є"),
        ("no",      "Світла не буде"),
        ("nfirst",  "Перші 30 хв."),
        ("nsecond", "Другі 30 хв."),
        ("maybe",   "Можливе відкл."),
    ]
    SW: float = float(CELL_W)   # same width as table cell
    SH: float = float(ROW_H)   # same height as table cell
    leg_y   = table_y + table_h + GAP + (LEGEND_H - SH) / 2
    lx: float = PAD_X  # type: ignore[no-redef]

    for state, label in legend_items:
        p.append(_legend_swatch(lx, leg_y, state, SW, SH))
        text_cx = lx + SW + 5
        text_cy = leg_y + SH / 2
        p.append(
            f'<text x="{text_cx:.1f}" y="{text_cy:.1f}" '
            f'font-family="{FONT}" font-size="{LEGEND_LABEL_FONT_SIZE}" '
            f'fill="{C_TEXT_MID}" dominant-baseline="central">'
            f'{_esc(label)}</text>'
        )
        lx += SW + 5 + len(label) * LEGEND_LABEL_FONT_SIZE * 0.58 + 18  # type: ignore[assignment]

    # ── Watermark (bottom-right, subtle) ─────────────────────────────────────
    wm_x  = IMG_W - PAD_X      # right-aligned within right margin
    wm_y2 = img_h - 8          # bottom line — 8px from image bottom
    wm_y1 = wm_y2 - 12         # top line — 12px above (both within PAD_Y zone)
    p.append(
        f'<text x="{wm_x}" y="{wm_y1:.1f}" '
        f'font-family="{FONT}" font-size="9" fill="{C_WATERMARK}" text-anchor="end">'
        f'{_esc("Вольтик")}</text>'
    )
    p.append(
        f'<text x="{wm_x}" y="{wm_y2:.1f}" '
        f'font-family="{FONT}" font-size="9" fill="{C_WATERMARK}" text-anchor="end">'
        f'{_esc("t.me/VoltykBot")}</text>'
    )

    p.append("</svg>")
    return "\n".join(p)


# ── Public API ────────────────────────────────────────────────────────────────

def _generate_sync(region: str, queue: str, schedule_data: dict) -> bytes | None:
    try:
        import cairosvg
    except ImportError:
        logger.warning("cairosvg not installed — chart generation unavailable")
        return None

    try:
        svg = _build_svg(region, queue, schedule_data)
        return cairosvg.svg2png(bytestring=svg.encode("utf-8"), scale=OUTPUT_SCALE)
    except Exception as e:
        logger.warning("Chart render error for %s/%s: %s", region, queue, e)
        return None


async def generate_schedule_chart(region: str, queue: str, schedule_data: dict) -> bytes | None:
    """Render a PNG schedule chart via SVG + CairoSVG.

    Drawing is CPU-bound and runs in ``_chart_executor`` — a dedicated
    ``ThreadPoolExecutor`` — so the asyncio event loop is never blocked and
    chart renders cannot starve other bot operations that share the default
    executor (Alembic migrations, etc.).

    Note: ``asyncio.wait_for`` cancels the *awaitable* (unblocks the coroutine)
    but the underlying thread in the pool continues running until it finishes or
    the process exits — Python threads cannot be forcibly killed.  The timeout
    therefore prevents the *caller* from hanging indefinitely, but a stuck
    CairoSVG/Pillow render still occupies one pool thread until it returns.
    """
    try:
        loop = asyncio.get_running_loop()
        return await asyncio.wait_for(
            loop.run_in_executor(_chart_executor, _generate_sync, region, queue, schedule_data),
            timeout=30.0,
        )
    except asyncio.TimeoutError:
        logger.error("Chart generation timed out for %s/%s", region, queue)
        return None
    except Exception as e:
        logger.warning("Chart generation failed for %s/%s: %s", region, queue, e)
        return None


def shutdown_chart_executor() -> None:
    """Shut down the chart rendering thread pool.

    Call once at bot shutdown. Uses wait=False so in-flight renders
    do not block the shutdown sequence — threads will finish naturally
    or be killed when the process exits.
    """
    _chart_executor.shutdown(wait=False)
