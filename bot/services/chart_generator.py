"""Generate schedule table PNG charts using SVG + CairoSVG.

SVG markup is built programmatically then rendered to PNG at 2× resolution
via CairoSVG (Cairo graphics engine — the same used by Firefox and Inkscape).

Advantages over Pillow:
  • Vector rendering — no pixel aliasing on lines, curves, or text
  • Sub-pixel font hinting via Cairo — crisp Cyrillic at any size
  • clipPath clips data cells to the rounded-corner table boundary
  • Rotated labels via SVG transform — mathematically perfect, never clipped

CPU-bound rendering runs in a thread-pool executor.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from bot.constants.regions import REGIONS
from bot.utils.logger import get_logger

logger = get_logger(__name__)

KYIV_TZ = ZoneInfo("Europe/Kyiv")

MONTHS_UK = [
    "січня", "лютого", "березня", "квітня", "травня", "червня",
    "липня", "серпня", "вересня", "жовтня", "листопада", "грудня",
]

# ── Layout (logical pixels at 1×) ─────────────────────────────────────────────
# cairosvg renders at OUTPUT_SCALE× → OUTPUT_SCALE * IMG_W physical pixels.
OUTPUT_SCALE = 2.0

IMG_W    = 1000
PAD_X    = 15
PAD_Y    = 20
LABEL_W  = 130
CELL_W   = 35    # 24 × 35 = 840;  840 + 130 = 970 = 1000 − 2×15 ✓
TITLE_H  = 84    # reduced: less empty space between header block and table
GAP      = 12    # ↓25 % — header block and table feel connected
HEADER_H = 72    # accommodates larger bold hour labels without excess padding
ROW_H    = 44    # slightly more compact data rows
LEGEND_H = 44

TABLE_W  = LABEL_W + 24 * CELL_W   # 970

# ── Colors ────────────────────────────────────────────────────────────────────
C_BG        = "#F5F7F9"
C_TABLE_BG  = "#FFFFFF"
C_HDR_BG    = "#F4F6F8"
C_BORDER    = "#D2DAE2"
C_BORDER_DK = "#B4BEC8"
C_TEXT      = "#1C2228"
C_TEXT_MID  = "#58606C"
C_BADGE_BG  = "#F2B200"

CELL_ON    = "#FFFFFF"
CELL_OFF   = "#3A424D"
CELL_MAYBE = "#9EA3A9"

# Font family — DejaVu Sans is installed via fonts-dejavu-core in the Dockerfile.
# CairoSVG resolves fonts through fontconfig; font-weight="bold" auto-selects
# DejaVuSans-Bold.ttf.
FONT = "DejaVu Sans, Liberation Sans, sans-serif"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _esc(text: str) -> str:
    """XML-escape text for safe embedding in SVG."""
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
    """Return a 24-element list of cell states for one day."""
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


def _bolt_pts(cx: float, cy: float, w: float) -> str:
    """SVG polygon `points` string for a lightning bolt centered at (cx, cy)."""
    h = w * 1.55
    ox, oy = cx - w / 2, cy - h / 2
    pts = [
        (ox + w * 0.65, oy),
        (ox + w * 0.08, oy + h * 0.52),
        (ox + w * 0.42, oy + h * 0.52),
        (ox + w * 0.35, oy + h),
        (ox + w * 0.92, oy + h * 0.48),
        (ox + w * 0.58, oy + h * 0.48),
    ]
    return " ".join(f"{x:.2f},{y:.2f}" for x, y in pts)


def _cell_svg(x: float, y: float, state: str) -> str:
    """Return SVG markup for one data cell (CELL_W × ROW_H)."""
    w, h = float(CELL_W), float(ROW_H)
    _BG = {
        "on":      (CELL_ON,    CELL_ON),
        "no":      (CELL_OFF,   CELL_OFF),
        "maybe":   (CELL_MAYBE, CELL_MAYBE),
        "nfirst":  (CELL_OFF,   CELL_ON),
        "nsecond": (CELL_ON,    CELL_OFF),
        "mfirst":  (CELL_MAYBE, CELL_ON),
        "msecond": (CELL_ON,    CELL_MAYBE),
    }
    _BOLT: dict[str, str | None] = {
        "on":      None,
        "no":      "#FFFFFF",
        "maybe":   "#DCE0E4",
        "nfirst":  "#FFFFFF",
        "nsecond": "#FFFFFF",
        "mfirst":  "#DCE0E4",
        "msecond": "#DCE0E4",
    }
    left_bg, right_bg = _BG.get(state, (CELL_ON, CELL_ON))
    hw = w / 2
    out: list[str] = []

    if left_bg == right_bg:
        out.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" fill="{left_bg}"/>')
    else:
        out.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{hw:.1f}" height="{h:.1f}" fill="{left_bg}"/>')
        out.append(f'<rect x="{x+hw:.1f}" y="{y:.1f}" width="{hw:.1f}" height="{h:.1f}" fill="{right_bg}"/>')

    bolt_color = _BOLT.get(state)
    if bolt_color:
        cx, cy = x + w / 2, y + h / 2
        # Bolt size proportional to cell: ~30 % of min(CELL_W, ROW_H)
        bolt_sz = round(min(CELL_W, ROW_H) * 0.30)
        out.append(f'<polygon points="{_bolt_pts(cx, cy, bolt_sz)}" fill="{bolt_color}"/>')

    return "\n".join(out)


# ── SVG builder ───────────────────────────────────────────────────────────────

def _build_svg(region: str, queue: str, schedule_data: dict) -> str:
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

    table_h = HEADER_H + 2 * ROW_H
    table_y = PAD_Y + TITLE_H + GAP
    img_h   = table_y + table_h + GAP + LEGEND_H + PAD_Y

    p: list[str] = []

    # ── SVG root ──────────────────────────────────────────────────────────────
    p.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{IMG_W}" height="{img_h}" viewBox="0 0 {IMG_W} {img_h}">'
    )

    # clipPath clips everything inside the table to its rounded-rect boundary
    p.append(
        f'<defs><clipPath id="tc">'
        f'<rect x="{PAD_X}" y="{table_y}" '
        f'width="{TABLE_W}" height="{table_h}" rx="8"/>'
        f'</clipPath></defs>'
    )

    # ── Image background ──────────────────────────────────────────────────────
    p.append(f'<rect width="{IMG_W}" height="{img_h}" fill="{C_BG}"/>')

    # ── Header ────────────────────────────────────────────────────────────────
    # Badge pill (right-aligned).
    # Estimate badge width: ~0.65 × font-size per char for bold Cyrillic/digits.
    queue_txt       = _esc(f"Черга {queue}")
    badge_fs        = 22
    badge_pad_h     = 22   # horizontal padding inside badge
    badge_pad_v     = 10   # vertical padding inside badge
    badge_text_w    = len(f"Черга {queue}") * badge_fs * 0.65
    badge_h         = badge_fs + badge_pad_v * 2   # 42
    badge_w         = badge_text_w + badge_pad_h * 2
    badge_x         = IMG_W - PAD_X - badge_w
    badge_cx        = badge_x + badge_w / 2

    p.append(
        f'<rect x="{badge_x:.1f}" y="{PAD_Y}" '
        f'width="{badge_w:.1f}" height="{badge_h}" '
        f'rx="{badge_h // 2}" fill="{C_BADGE_BG}"/>'
    )
    p.append(
        f'<text x="{badge_cx:.1f}" y="{PAD_Y + badge_h / 2:.1f}" '
        f'font-family="{FONT}" font-size="{badge_fs}" '
        f'fill="{C_TEXT}" text-anchor="middle" dominant-baseline="central">'
        f'{queue_txt}</text>'
    )

    # Title (left-aligned, vertically centered with badge)
    title_txt = _esc(f"Графік відключень ({region_label}):")
    title_cy  = PAD_Y + badge_h / 2
    p.append(
        f'<text x="{PAD_X}" y="{title_cy:.1f}" '
        f'font-family="{FONT}" font-size="20" font-weight="bold" '
        f'fill="{C_TEXT}" dominant-baseline="central">'
        f'{title_txt}</text>'
    )

    # Subtitle — DTEK update timestamp
    dtek_raw = schedule_data.get("dtek_updated_at")
    subtitle_txt = ""
    if dtek_raw:
        try:
            dtek_dt     = datetime.strptime(dtek_raw, "%d.%m.%Y %H:%M")
            subtitle_txt = _esc(
                "Дата та час останнього оновлення інформації на графіку: "
                + dtek_dt.strftime("%d.%m.%Y %H:%M")
            )
        except ValueError:
            pass
    if subtitle_txt:
        sub_y = PAD_Y + badge_h + 8
        p.append(
            f'<text x="{PAD_X}" y="{sub_y}" '
            f'font-family="{FONT}" font-size="11" '
            f'fill="{C_TEXT_MID}">{subtitle_txt}</text>'
        )

    # ── Table background (filled, rounded) ────────────────────────────────────
    p.append(
        f'<rect x="{PAD_X}" y="{table_y}" '
        f'width="{TABLE_W}" height="{table_h}" '
        f'rx="8" fill="{C_TABLE_BG}"/>'
    )

    # ── Table contents clipped to rounded rect ────────────────────────────────
    p.append('<g clip-path="url(#tc)">')

    # Header row background
    p.append(
        f'<rect x="{PAD_X}" y="{table_y}" '
        f'width="{TABLE_W}" height="{HEADER_H}" fill="{C_HDR_BG}"/>'
    )

    # Data cells
    for row_i, states in enumerate([today_states, tomorrow_states]):
        row_y = table_y + HEADER_H + row_i * ROW_H
        for col_i, state in enumerate(states):
            cx = PAD_X + LABEL_W + col_i * CELL_W
            p.append(_cell_svg(cx, row_y, state))

    # Horizontal grid lines (below header, between rows, below last row)
    for i in range(3):
        ly = table_y + HEADER_H + i * ROW_H
        p.append(
            f'<line x1="{PAD_X}" y1="{ly}" x2="{PAD_X + TABLE_W}" y2="{ly}" '
            f'stroke="{C_BORDER_DK}" stroke-width="1"/>'
        )

    # Vertical separator: label column (full height)
    label_sep_x = PAD_X + LABEL_W
    p.append(
        f'<line x1="{label_sep_x}" y1="{table_y}" '
        f'x2="{label_sep_x}" y2="{table_y + table_h}" '
        f'stroke="{C_BORDER_DK}" stroke-width="1"/>'
    )

    # Vertical separators between hour columns — full height including header
    for col in range(1, 24):
        lx = PAD_X + LABEL_W + col * CELL_W
        p.append(
            f'<line x1="{lx}" y1="{table_y}" x2="{lx}" y2="{table_y + table_h}" '
            f'stroke="{C_BORDER}" stroke-width="1"/>'
        )

    p.append('</g>')  # end clip group

    # ── Table border (drawn last — rounds off corners over the clip group) ────
    p.append(
        f'<rect x="{PAD_X}" y="{table_y}" '
        f'width="{TABLE_W}" height="{table_h}" '
        f'rx="8" fill="none" stroke="{C_BORDER_DK}" stroke-width="1"/>'
    )

    # ── Table text labels (outside clip — always fully visible) ───────────────
    # "Часові проміжки" centered in the header label cell
    hdr_cx = PAD_X + LABEL_W / 2
    hdr_mid = table_y + HEADER_H / 2
    p.append(
        f'<text x="{hdr_cx:.1f}" y="{hdr_mid - 7:.1f}" '
        f'font-family="{FONT}" font-size="11" font-weight="bold" '
        f'fill="{C_TEXT_MID}" text-anchor="middle">Часові</text>'
    )
    p.append(
        f'<text x="{hdr_cx:.1f}" y="{hdr_mid + 7:.1f}" '
        f'font-family="{FONT}" font-size="11" font-weight="bold" '
        f'fill="{C_TEXT_MID}" text-anchor="middle">проміжки</text>'
    )

    # Rotated hour labels "00-01" … "23-24" (rotate(-90) around cell center)
    for h in range(24):
        label  = _esc(f"{h:02d}-{h + 1:02d}")
        col_cx = PAD_X + LABEL_W + h * CELL_W + CELL_W / 2
        col_cy = table_y + HEADER_H / 2
        p.append(
            f'<text transform="translate({col_cx:.1f},{col_cy:.1f}) rotate(-90)" '
            f'font-family="{FONT}" font-size="11" font-weight="bold" '
            f'fill="{C_TEXT_MID}" text-anchor="middle" dominant-baseline="central">'
            f'{label}</text>'
        )

    # Date labels — centered in each data row's label cell
    for row_i, dt in enumerate([today_start, tomorrow_start]):
        row_cy = table_y + HEADER_H + row_i * ROW_H + ROW_H / 2
        p.append(
            f'<text x="{hdr_cx:.1f}" y="{row_cy:.1f}" '
            f'font-family="{FONT}" font-size="13" font-weight="bold" '
            f'fill="{C_TEXT}" text-anchor="middle" dominant-baseline="central">'
            f'{_esc(_day_label(dt))}</text>'
        )

    # ── Legend ────────────────────────────────────────────────────────────────
    legend_items = [
        ("on",      "Світло є"),
        ("no",      "Світла нема"),
        ("nfirst",  "Перші 30 хв."),
        ("nsecond", "Другі 30 хв."),
        ("maybe",   "Можливе відкл."),
    ]
    SW, SH  = 24, 18
    leg_y   = table_y + table_h + GAP + (LEGEND_H - SH) // 2
    lx: float = PAD_X

    for state, label in legend_items:
        hw = SW / 2
        if state == "nfirst":
            p.append(f'<rect x="{lx:.1f}" y="{leg_y}" width="{hw:.1f}" height="{SH}" fill="{CELL_OFF}"/>')
            p.append(f'<rect x="{lx+hw:.1f}" y="{leg_y}" width="{hw:.1f}" height="{SH}" fill="{CELL_ON}" stroke="{C_BORDER}" stroke-width="0.5"/>')
            p.append(f'<polygon points="{_bolt_pts(lx+SW/2, leg_y+SH/2, 7)}" fill="#FFFFFF"/>')
        elif state == "nsecond":
            p.append(f'<rect x="{lx:.1f}" y="{leg_y}" width="{hw:.1f}" height="{SH}" fill="{CELL_ON}" stroke="{C_BORDER}" stroke-width="0.5"/>')
            p.append(f'<rect x="{lx+hw:.1f}" y="{leg_y}" width="{hw:.1f}" height="{SH}" fill="{CELL_OFF}"/>')
            p.append(f'<polygon points="{_bolt_pts(lx+SW/2, leg_y+SH/2, 7)}" fill="#FFFFFF"/>')
        elif state == "no":
            p.append(f'<rect x="{lx:.1f}" y="{leg_y}" width="{SW}" height="{SH}" fill="{CELL_OFF}"/>')
            p.append(f'<polygon points="{_bolt_pts(lx+SW/2, leg_y+SH/2, 7)}" fill="#FFFFFF"/>')
        elif state == "maybe":
            p.append(f'<rect x="{lx:.1f}" y="{leg_y}" width="{SW}" height="{SH}" fill="{CELL_MAYBE}"/>')
            p.append(f'<polygon points="{_bolt_pts(lx+SW/2, leg_y+SH/2, 7)}" fill="#DCE0E4"/>')
        else:  # "on"
            p.append(f'<rect x="{lx:.1f}" y="{leg_y}" width="{SW}" height="{SH}" fill="{CELL_ON}" stroke="{C_BORDER}" stroke-width="1"/>')

        text_x = lx + SW + 5
        text_cy = leg_y + SH / 2
        p.append(
            f'<text x="{text_x:.1f}" y="{text_cy:.1f}" '
            f'font-family="{FONT}" font-size="12" '
            f'fill="{C_TEXT_MID}" dominant-baseline="central">'
            f'{_esc(label)}</text>'
        )
        # Advance: swatch + gap + estimated text width (0.58 × font_size per char) + spacing
        lx += SW + 5 + len(label) * 12 * 0.58 + 18

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

    Drawing is CPU-bound and runs in the default thread-pool executor so the
    asyncio event loop is never blocked.
    """
    try:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, _generate_sync, region, queue, schedule_data)
    except Exception as e:
        logger.warning("Chart generation failed for %s/%s: %s", region, queue, e)
        return None
