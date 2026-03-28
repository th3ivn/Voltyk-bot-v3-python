"""Generate schedule table PNG charts using Pillow.

Produces a light-themed table image that mirrors the standard Ukrainian
power-outage schedule format:
  • Two-badge header  (update time left | region+queue right)
  • 24-column hourly table  (today + tomorrow rows)
  • Per-cell state with lightning-bolt icons
  • Legend row at the bottom

CPU-bound drawing runs in a thread-pool executor — the event loop is never
blocked.
"""
from __future__ import annotations

import asyncio
import io
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

# ── Layout ────────────────────────────────────────────────────────────────────
IMG_W      = 1000   # total image width
PAD_X      = 20     # horizontal padding
PAD_Y      = 16     # vertical padding
LABEL_W    = 110    # width of the date-label column
CELL_W     = 37     # width of each 1-hour column  (24*37 + 110 + 2*20 = 1018 → adjust)
# Recalculate so everything fits:  24*CELL_W = IMG_W - 2*PAD_X - LABEL_W
# 24*CELL_W = 1000 - 40 - 110 = 850  → CELL_W = 35.4 → use 35, LABEL_W = 860-840=130
# Final: LABEL_W=130, CELL_W=35 → 130+24*35=130+840=970=1000-2*15 → PAD_X=15
PAD_X      = 15
LABEL_W    = 130
CELL_W     = 35     # 24*35 = 840; 840+130 = 970 = 1000-2*15 ✓

BADGE_H    = 36     # header badge height
GAP        = 12     # gap between badge section and table
HEADER_H   = 58     # table header row height (for rotated labels)
ROW_H      = 40     # data row height
LEGEND_H   = 36     # legend row height

TABLE_W    = LABEL_W + 24 * CELL_W  # = 970

# ── Colors ────────────────────────────────────────────────────────────────────
C_BG          = (245, 247, 249)   # overall image background
C_TABLE_BG    = (255, 255, 255)
C_HDR_BG      = (244, 246, 248)   # header row fill
C_BORDER      = (210, 218, 226)
C_BORDER_DARK = (180, 190, 200)

C_TEXT        = (28,  34,  40)
C_TEXT_MID    = (88,  96, 108)
C_TEXT_DIM    = (150, 160, 172)

# Header badge colors
C_BADGE_L_BG  = (236, 240, 244)   # left badge bg
C_BADGE_L_BD  = (210, 218, 226)   # left badge border
C_BADGE_R_BG  = (242, 178, 0)     # right badge bg (yellow)

# Cell colors
CELL_ON       = (255, 255, 255)
CELL_OFF      = (58,  66,  77)    # dark slate
CELL_MAYBE    = (158, 163, 169)   # medium gray

# Icon colors (drawn on top of cells)
ICON_ON_DARK  = (255, 255, 255)   # white bolt on dark cell
ICON_ON_GRAY  = (220, 224, 228)   # light bolt on gray cell

# "No outages" row message colors
C_OK_TEXT     = (40, 150, 70)     # green for "no outages"
C_NA_TEXT     = (140, 150, 162)   # gray for "no data"

# ── Font helpers ──────────────────────────────────────────────────────────────
_REG = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
    "/usr/share/fonts/truetype/ubuntu/Ubuntu-R.ttf",
    "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
]
_BOLD = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
    "/usr/share/fonts/truetype/ubuntu/Ubuntu-B.ttf",
    "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
]


def _font(paths: list[str], size: int):
    from PIL import ImageFont
    for p in paths:
        try:
            return ImageFont.truetype(p, size)
        except (IOError, OSError):
            continue
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def _load_fonts() -> dict:
    return {
        "badge":    _font(_REG,  13),
        "badge_b":  _font(_BOLD, 13),
        "hdr_lbl":  _font(_BOLD, 11),   # "Часові проміжки"
        "col_lbl":  _font(_REG,   9),   # "00-01" rotated
        "date_lbl": _font(_BOLD, 13),   # "27 березня"
        "msg":      _font(_REG,  12),   # row messages
        "legend":   _font(_REG,  12),
        "legend_b": _font(_BOLD, 12),
    }


# ── Data helpers ──────────────────────────────────────────────────────────────

def _parse_dt(v) -> datetime:
    if isinstance(v, str):
        return datetime.fromisoformat(v).astimezone(KYIV_TZ)
    return v.astimezone(KYIV_TZ)


def _day_label(dt: datetime) -> str:
    return f"{dt.day} {MONTHS_UK[dt.month - 1]}"


def _get_hour_states(events: list[dict], day_start: datetime) -> list[str]:
    """Return a 24-element list of state strings for each hour of the day.

    States: 'on' | 'no' | 'maybe' | 'nfirst' | 'nsecond' | 'mfirst' | 'msecond'
    """
    half_map = bytearray(48)  # 30-min slots; 0=on, 1=planned, 2=possible
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


# ── Drawing primitives ────────────────────────────────────────────────────────

def _tw(draw, text: str, font) -> int:
    bb = draw.textbbox((0, 0), text, font=font)
    return bb[2] - bb[0]


def _th(draw, text: str, font) -> int:
    bb = draw.textbbox((0, 0), text, font=font)
    return bb[3] - bb[1]


def _draw_bolt(draw, cx: int, cy: int, w: int, color) -> None:
    """Draw a lightning bolt icon centered at (cx, cy), bounding-box width w."""
    h = int(w * 1.55)
    ox, oy = cx - w // 2, cy - h // 2
    pts = [
        (ox + int(w * 0.65), oy),
        (ox + int(w * 0.08), oy + int(h * 0.52)),
        (ox + int(w * 0.42), oy + int(h * 0.52)),
        (ox + int(w * 0.35), oy + h),
        (ox + int(w * 0.92), oy + int(h * 0.48)),
        (ox + int(w * 0.58), oy + int(h * 0.48)),
    ]
    draw.polygon(pts, fill=color)


def _paste_rotated_text(
    img, text: str, font, cx: int, cy: int, cell_h: int, cell_w: int, color: tuple
) -> None:
    """Draw text rotated 90° CCW, centered in the given cell bounding box.

    cx / cy mark the top-left of the cell.
    """
    from PIL import Image as _Img
    from PIL import ImageDraw as _ID

    dummy = _Img.new("RGBA", (300, 40), (0, 0, 0, 0))
    dd = _ID.Draw(dummy)
    bb = dd.textbbox((0, 0), text, font=font)
    tw, th = bb[2] - bb[0], bb[3] - bb[1]

    txt_img = _Img.new("RGBA", (tw + 2, th + 2), (0, 0, 0, 0))
    _ID.Draw(txt_img).text((1, 1), text, font=font, fill=(*color, 255))

    rotated = txt_img.rotate(90, expand=True)

    rx = cx + (cell_w - rotated.width) // 2
    ry = cy + (cell_h - rotated.height) // 2
    img.paste(rotated, (rx, ry), rotated)


def _draw_cell(draw, x: int, y: int, state: str) -> None:
    """Fill a single hour cell and overlay the bolt icon when needed."""
    w, h = CELL_W, ROW_H

    _BG: dict[str, tuple] = {
        "on":      (CELL_ON,    CELL_ON),
        "no":      (CELL_OFF,   CELL_OFF),
        "maybe":   (CELL_MAYBE, CELL_MAYBE),
        "nfirst":  (CELL_OFF,   CELL_ON),
        "nsecond": (CELL_ON,    CELL_OFF),
        "mfirst":  (CELL_MAYBE, CELL_ON),
        "msecond": (CELL_ON,    CELL_MAYBE),
    }
    _ICON: dict[str, tuple | None] = {
        "on":      None,
        "no":      ICON_ON_DARK,
        "maybe":   ICON_ON_GRAY,
        "nfirst":  ICON_ON_DARK,
        "nsecond": ICON_ON_DARK,
        "mfirst":  ICON_ON_GRAY,
        "msecond": ICON_ON_GRAY,
    }

    left_bg, right_bg = _BG.get(state, (CELL_ON, CELL_ON))
    hw = w // 2

    if left_bg == right_bg:
        draw.rectangle([x, y, x + w - 1, y + h - 1], fill=left_bg)
    else:
        draw.rectangle([x,      y, x + hw - 1, y + h - 1], fill=left_bg)
        draw.rectangle([x + hw, y, x + w  - 1, y + h - 1], fill=right_bg)

    icon_color = _ICON.get(state)
    if icon_color is not None:
        _draw_bolt(draw, x + w // 2, y + h // 2, 11, icon_color)


# ── Table renderer ────────────────────────────────────────────────────────────

def _draw_table(
    img,
    draw,
    ox: int, oy: int,
    today_ev: list[dict],
    tomorrow_ev: list[dict],
    today_start: datetime,
    tomorrow_start: datetime,
    has_data: bool,
    fonts: dict,
) -> None:
    """Draw the full schedule table starting at (ox, oy)."""
    total_h = HEADER_H + 2 * ROW_H

    # ── Outer border & background ─────────────────────────────────────────────
    draw.rounded_rectangle(
        [ox, oy, ox + TABLE_W, oy + total_h],
        radius=6, fill=C_TABLE_BG, outline=C_BORDER_DARK, width=1,
    )

    # Header row background
    draw.rectangle(
        [ox + 1, oy + 1, ox + TABLE_W - 1, oy + HEADER_H - 1],
        fill=C_HDR_BG,
    )

    # ── Fill data cells ───────────────────────────────────────────────────────
    if has_data:
        today_states    = _get_hour_states(today_ev,    today_start)
        tomorrow_states = _get_hour_states(tomorrow_ev, tomorrow_start)
    else:
        today_states    = ["on"] * 24
        tomorrow_states = ["on"] * 24

    for row_idx, states in enumerate([today_states, tomorrow_states]):
        row_y = oy + HEADER_H + row_idx * ROW_H
        for col_idx, state in enumerate(states):
            cell_x = ox + LABEL_W + col_idx * CELL_W
            _draw_cell(draw, cell_x, row_y, state)

    # ── Grid lines ────────────────────────────────────────────────────────────
    # Horizontal separators
    for i in range(1, 3):
        ly = oy + HEADER_H + (i - 1) * ROW_H
        draw.line([(ox, ly), (ox + TABLE_W, ly)], fill=C_BORDER, width=1)
    draw.line([(ox, oy + total_h), (ox + TABLE_W, oy + total_h)], fill=C_BORDER_DARK, width=1)

    # Vertical separators between hour columns
    for col in range(1, 24):
        lx = ox + LABEL_W + col * CELL_W
        draw.line([(lx, oy + HEADER_H), (lx, oy + total_h)], fill=C_BORDER, width=1)

    # Label column separator (darker)
    draw.line([(ox + LABEL_W, oy), (ox + LABEL_W, oy + total_h)], fill=C_BORDER_DARK, width=1)

    # ── Header labels ─────────────────────────────────────────────────────────
    # "Часові проміжки" in the top-left cell — two lines, centered
    hdr_lines = ["Часові", "проміжки"]
    line_h = _th(draw, "A", fonts["hdr_lbl"]) + 2
    total_lines_h = len(hdr_lines) * line_h
    txt_y = oy + (HEADER_H - total_lines_h) // 2
    for line in hdr_lines:
        tw = _tw(draw, line, fonts["hdr_lbl"])
        draw.text(
            (ox + (LABEL_W - tw) // 2, txt_y),
            line, font=fonts["hdr_lbl"], fill=C_TEXT_MID,
        )
        txt_y += line_h

    # Rotated hour labels "00-01" … "23-24"
    for h in range(24):
        label = f"{h:02d}-{h + 1:02d}"
        cell_x = ox + LABEL_W + h * CELL_W
        _paste_rotated_text(
            img, label, fonts["col_lbl"],
            cell_x, oy, HEADER_H, CELL_W, C_TEXT_MID,
        )

    # ── Date labels + row messages ────────────────────────────────────────────
    for row_idx, (dt, ev_list) in enumerate([
        (today_start,    today_ev),
        (tomorrow_start, tomorrow_ev),
    ]):
        row_y = oy + HEADER_H + row_idx * ROW_H

        # Date label (left column)
        dlabel = _day_label(dt)
        dtw = _tw(draw, dlabel, fonts["date_lbl"])
        dth = _th(draw, dlabel, fonts["date_lbl"])
        draw.text(
            (ox + (LABEL_W - dtw) // 2, row_y + (ROW_H - dth) // 2),
            dlabel, font=fonts["date_lbl"], fill=C_TEXT,
        )

        # Optional overlay message (spans the hours area)
        if not has_data:
            msg, msg_color = "Дані відсутні", C_NA_TEXT
        elif not ev_list:
            msg, msg_color = "Відключень не заплановано", C_OK_TEXT
        else:
            continue  # cells already drawn with states

        hours_area_w = 24 * CELL_W
        mtw = _tw(draw, msg, fonts["msg"])
        mth = _th(draw, msg, fonts["msg"])
        draw.text(
            (ox + LABEL_W + (hours_area_w - mtw) // 2,
             row_y + (ROW_H - mth) // 2),
            msg, font=fonts["msg"], fill=msg_color,
        )


# ── Legend renderer ───────────────────────────────────────────────────────────

def _draw_legend(draw, ox: int, oy: int, fonts: dict) -> None:
    """Draw the icon legend row."""
    items = [
        ("on",     "Світло є"),
        ("no",     "Світла нема"),
        ("nfirst", "Перші 30 хв."),
        ("nsecond","Другі 30 хв."),
        ("maybe",  "Можливе відкл."),
    ]
    SWATCH_W, SWATCH_H = 24, 18
    x = ox

    for state, label in items:
        # Swatch (small cell preview)
        hw = SWATCH_W // 2
        if state in ("nfirst",):
            draw.rectangle([x, oy, x + hw - 1, oy + SWATCH_H - 1], fill=CELL_OFF)
            draw.rectangle([x + hw, oy, x + SWATCH_W - 1, oy + SWATCH_H - 1], fill=CELL_ON)
            _draw_bolt(draw, x + SWATCH_W // 2, oy + SWATCH_H // 2, 8, ICON_ON_DARK)
        elif state in ("nsecond",):
            draw.rectangle([x, oy, x + hw - 1, oy + SWATCH_H - 1], fill=CELL_ON)
            draw.rectangle([x + hw, oy, x + SWATCH_W - 1, oy + SWATCH_H - 1], fill=CELL_OFF)
            _draw_bolt(draw, x + SWATCH_W // 2, oy + SWATCH_H // 2, 8, ICON_ON_DARK)
        elif state == "no":
            draw.rectangle([x, oy, x + SWATCH_W - 1, oy + SWATCH_H - 1], fill=CELL_OFF)
            _draw_bolt(draw, x + SWATCH_W // 2, oy + SWATCH_H // 2, 8, ICON_ON_DARK)
        elif state == "maybe":
            draw.rectangle([x, oy, x + SWATCH_W - 1, oy + SWATCH_H - 1], fill=CELL_MAYBE)
            _draw_bolt(draw, x + SWATCH_W // 2, oy + SWATCH_H // 2, 8, ICON_ON_GRAY)
        else:  # "on"
            draw.rectangle([x, oy, x + SWATCH_W - 1, oy + SWATCH_H - 1], fill=CELL_ON)
            draw.rectangle([x, oy, x + SWATCH_W - 1, oy + SWATCH_H - 1], outline=C_BORDER)

        x += SWATCH_W + 5
        lth = _th(draw, label, fonts["legend"])
        draw.text((x, oy + (SWATCH_H - lth) // 2), label, font=fonts["legend"], fill=C_TEXT_MID)
        x += _tw(draw, label, fonts["legend"]) + 20


# ── Main public API ───────────────────────────────────────────────────────────

def _generate_sync(region: str, queue: str, schedule_data: dict) -> bytes | None:
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        logger.warning("Pillow not installed — chart generation unavailable")
        return None

    try:
        fonts = _load_fonts()
        now = datetime.now(KYIV_TZ)
        today_start    = now.replace(hour=0, minute=0, second=0, microsecond=0)
        tomorrow_start = today_start + timedelta(days=1)
        day_after      = tomorrow_start + timedelta(days=1)

        events = schedule_data.get("events", [])
        has_data = schedule_data.get("hasData", False)

        today_ev    = [e for e in events if today_start    <= _parse_dt(e["start"]) < tomorrow_start]
        tomorrow_ev = [e for e in events if tomorrow_start <= _parse_dt(e["start"]) < day_after]

        region_label = REGIONS[region].name if region in REGIONS else region

        # ── Image height ──────────────────────────────────────────────────────
        badge_sec  = PAD_Y + BADGE_H
        table_sec  = GAP + HEADER_H + 2 * ROW_H
        legend_sec = GAP + LEGEND_H + PAD_Y
        total_h    = badge_sec + table_sec + legend_sec

        img  = Image.new("RGB", (IMG_W, total_h), C_BG)
        draw = ImageDraw.Draw(img)

        y = PAD_Y

        # ── Header badges ─────────────────────────────────────────────────────
        update_txt = f"Оновлення від {now.strftime('%H:%M')} {now.strftime('%d.%m')}"
        queue_txt  = f"{region_label}, Черга {queue}"

        bp, bpv = 14, 7  # badge horizontal / vertical padding

        # Left badge
        btw_l = _tw(draw, update_txt, fonts["badge"])
        bth   = _th(draw, update_txt, fonts["badge"])
        bh    = bth + bpv * 2
        draw.rounded_rectangle(
            [PAD_X, y, PAD_X + btw_l + bp * 2, y + bh],
            radius=8, fill=C_BADGE_L_BG, outline=C_BADGE_L_BD, width=1,
        )
        draw.text((PAD_X + bp, y + bpv), update_txt, font=fonts["badge"], fill=C_TEXT_MID)

        # Right badge
        btw_r = _tw(draw, queue_txt, fonts["badge_b"])
        bth_r = _th(draw, queue_txt, fonts["badge_b"])
        bh_r  = bth_r + bpv * 2
        rx    = IMG_W - PAD_X - btw_r - bp * 2
        draw.rounded_rectangle(
            [rx, y, IMG_W - PAD_X, y + bh_r],
            radius=8, fill=C_BADGE_R_BG, outline=C_BADGE_R_BG, width=1,
        )
        draw.text((rx + bp, y + bpv), queue_txt, font=fonts["badge_b"], fill=C_TEXT)

        y += BADGE_H + GAP

        # ── Table ─────────────────────────────────────────────────────────────
        _draw_table(
            img, draw,
            ox=PAD_X, oy=y,
            today_ev=today_ev,
            tomorrow_ev=tomorrow_ev,
            today_start=today_start,
            tomorrow_start=tomorrow_start,
            has_data=has_data,
            fonts=fonts,
        )
        y += HEADER_H + 2 * ROW_H + GAP

        # ── Legend ────────────────────────────────────────────────────────────
        legend_y = y + (LEGEND_H - 18) // 2
        _draw_legend(draw, PAD_X, legend_y, fonts)

        buf = io.BytesIO()
        img.save(buf, "PNG", optimize=True)
        return buf.getvalue()

    except Exception as e:
        logger.warning("Chart render error for %s/%s: %s", region, queue, e)
        return None


async def generate_schedule_chart(region: str, queue: str, schedule_data: dict) -> bytes | None:
    """Generate a PNG schedule chart.

    Drawing is CPU-bound and runs in the default thread-pool executor so the
    asyncio event loop is never blocked.
    """
    try:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, _generate_sync, region, queue, schedule_data)
    except Exception as e:
        logger.warning("Chart generation failed for %s/%s: %s", region, queue, e)
        return None
