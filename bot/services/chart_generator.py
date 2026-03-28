"""Generate schedule PNG charts using Pillow.

CPU-bound drawing runs in a thread pool executor so the event loop is
never blocked.
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
TOTAL_MINUTES = 24 * 60
DAY_NAMES = ["Понеділок", "Вівторок", "Середа", "Четвер", "П'ятниця", "Субота", "Неділя"]

IMG_WIDTH = 800
PAD = 24

# ── Color palette (dark GitHub-inspired) ─────────────────────────────────────
C_BG        = (13,  17,  23)
C_CARD      = (22,  27,  34)
C_BORDER    = (33,  38,  45)
C_TEXT      = (230, 237, 243)
C_MUTED     = (139, 148, 158)
C_DIM       = (72,  79,  104)
C_BRAND     = (240, 180, 41)
C_BLUE      = (88,  166, 255)

SEG_ON      = (30,  70,  32)
SEG_OFF     = (122, 30,  30)
SEG_MAYBE   = (90,  62,  0)

DOT_OFF     = (248, 81,  73)
DOT_MAYBE   = (210, 153, 34)
DOT_OK      = (46,  160, 67)

# ── Font helpers ──────────────────────────────────────────────────────────────

_REGULAR_FONTS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
    "/usr/share/fonts/truetype/ubuntu/Ubuntu-R.ttf",
    "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
]
_BOLD_FONTS = [
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
        "brand":   _font(_BOLD_FONTS,    20),
        "region":  _font(_REGULAR_FONTS, 13),
        "queue":   _font(_BOLD_FONTS,    15),
        "title":   _font(_BOLD_FONTS,    14),
        "event":   _font(_REGULAR_FONTS, 13),
        "event_b": _font(_BOLD_FONTS,    13),
        "dur":     _font(_REGULAR_FONTS, 12),
        "hours":   _font(_REGULAR_FONTS, 10),
        "total":   _font(_REGULAR_FONTS, 12),
        "total_b": _font(_BOLD_FONTS,    12),
        "legend":  _font(_REGULAR_FONTS, 11),
    }


# ── Data helpers ──────────────────────────────────────────────────────────────

def _parse_dt(v) -> datetime:
    if isinstance(v, str):
        return datetime.fromisoformat(v).astimezone(KYIV_TZ)
    return v.astimezone(KYIV_TZ)


def _format_time(dt: datetime) -> str:
    return dt.strftime("%H:%M")


def _format_date(dt: datetime) -> str:
    return dt.strftime("%d.%m.%Y")


def _dur_str(seconds: float) -> str:
    h = int(seconds // 3600)
    m = round((seconds % 3600) / 60)
    if h > 0:
        return f"{h} год {m} хв" if m else f"{h} год"
    return f"{m} хв"


def _total_dur(events: list[dict]) -> str:
    s = sum((_parse_dt(e["end"]) - _parse_dt(e["start"])).total_seconds() for e in events)
    return _dur_str(s)


def _build_minute_map(events: list[dict], day_start: datetime) -> bytearray:
    mm = bytearray(TOTAL_MINUTES)
    for ev in events:
        a = max(0, int((_parse_dt(ev["start"]) - day_start).total_seconds() / 60))
        b = min(TOTAL_MINUTES, int((_parse_dt(ev["end"]) - day_start).total_seconds() / 60))
        state = 2 if ev.get("isPossible") else 1
        for i in range(a, b):
            mm[i] = state
    return mm


# ── Drawing helpers ───────────────────────────────────────────────────────────

def _tw(draw, text: str, font) -> int:
    bb = draw.textbbox((0, 0), text, font=font)
    return bb[2] - bb[0]


def _th(draw, text: str, font) -> int:
    bb = draw.textbbox((0, 0), text, font=font)
    return bb[3] - bb[1]


def _section_height(n_events: int) -> int:
    """Estimated height of a day section card (with extra buffer)."""
    ip = 14
    title_h = 24
    bar_block = 32 + 6 + 16   # bar + gap + hour labels
    events_h = (n_events * 20) if n_events > 0 else 20
    total_line = (10 + 18) if n_events > 0 else 0
    return ip + title_h + bar_block + 8 + events_h + total_line + ip + 10


# ── Section renderer ──────────────────────────────────────────────────────────

def _draw_section(
    draw,
    x: int, y: int, w: int,
    title: str,
    events: list[dict],
    day_start: datetime,
    fonts: dict,
    now: datetime | None,
) -> int:
    """Draw one day card. Returns actual pixel height consumed."""
    est_h = _section_height(len(events))
    draw.rounded_rectangle([x, y, x + w, y + est_h], radius=10, fill=C_CARD, outline=C_BORDER)

    ip = 14
    cx, cy = x + ip, y + ip

    # Title
    draw.text((cx, cy), title, font=fonts["title"], fill=C_TEXT)
    cy += 24

    # ── Timeline bar ─────────────────────────────────────────────────────────
    bar_x = cx
    bar_w = w - ip * 2
    bar_h = 32
    mm = _build_minute_map(events, day_start)

    seg_colors = {0: SEG_ON, 1: SEG_OFF, 2: SEG_MAYBE}
    i = 0
    while i < TOTAL_MINUTES:
        st = mm[i]
        j = i + 1
        while j < TOTAL_MINUTES and mm[j] == st:
            j += 1
        x1 = bar_x + int(i / TOTAL_MINUTES * bar_w)
        x2 = bar_x + int(j / TOTAL_MINUTES * bar_w)
        if x2 > x1:
            draw.rectangle([x1, cy, x2 - 1, cy + bar_h - 1], fill=seg_colors[st])
        i = j

    draw.rectangle([bar_x, cy, bar_x + bar_w - 1, cy + bar_h - 1], outline=C_BORDER, width=1)

    # Now marker — blue vertical line
    if now is not None:
        nm = (now - day_start).total_seconds() / 60
        if 0 <= nm <= TOTAL_MINUTES:
            nx = bar_x + int(nm / TOTAL_MINUTES * bar_w)
            draw.rectangle([nx - 1, cy - 2, nx + 1, cy + bar_h + 1], fill=C_BLUE)

    cy += bar_h + 6

    # Hour labels every 2 h
    for h_val in range(0, 25, 2):
        lx = bar_x + int(h_val / 24 * bar_w)
        lbl = f"{h_val:02d}"
        draw.text((lx - _tw(draw, lbl, fonts["hours"]) // 2, cy), lbl,
                  font=fonts["hours"], fill=C_DIM)
    cy += 16

    # ── Event list ────────────────────────────────────────────────────────────
    cy += 8
    if events:
        for ev in events:
            s = _parse_dt(ev["start"])
            e = _parse_dt(ev["end"])
            secs = (e - s).total_seconds()
            possible = ev.get("isPossible", False)
            dot_c = DOT_MAYBE if possible else DOT_OFF

            # Dot
            draw.ellipse([cx + 1, cy + 5, cx + 9, cy + 13], fill=dot_c)

            # Time (bold)
            time_txt = f"{_format_time(s)} – {_format_time(e)}"
            draw.text((cx + 14, cy + 1), time_txt, font=fonts["event_b"], fill=C_TEXT)
            tw_t = _tw(draw, time_txt, fonts["event_b"])

            # Duration (muted)
            dur_txt = f"  (~{_dur_str(secs)})"
            draw.text((cx + 14 + tw_t, cy + 2), dur_txt, font=fonts["dur"], fill=C_MUTED)

            # Possible label
            if possible:
                tw_d = _tw(draw, dur_txt, fonts["dur"])
                draw.text(
                    (cx + 14 + tw_t + tw_d + 6, cy + 2),
                    "можливе",
                    font=fonts["dur"],
                    fill=DOT_MAYBE,
                )

            cy += 20

        # Separator + total
        draw.line([(cx, cy + 2), (x + w - ip, cy + 2)], fill=C_BORDER, width=1)
        cy += 10
        lbl = "Без світла: "
        val = f"~{_total_dur(events)}"
        draw.text((cx, cy), lbl, font=fonts["total"], fill=C_MUTED)
        draw.text((cx + _tw(draw, lbl, fonts["total"]), cy), val, font=fonts["total_b"], fill=C_TEXT)
        cy += 18
    else:
        draw.ellipse([cx + 1, cy + 4, cx + 9, cy + 12], fill=DOT_OK)
        draw.text((cx + 14, cy + 1), "Відключень не заплановано", font=fonts["event"], fill=DOT_OK)
        cy += 20

    cy += ip
    return cy - y  # actual height


# ── Main entry point ──────────────────────────────────────────────────────────

def _generate_sync(region: str, queue: str, schedule_data: dict) -> bytes | None:
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        logger.warning("Pillow not installed — chart generation unavailable")
        return None

    try:
        fonts = _load_fonts()
        now = datetime.now(KYIV_TZ)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        tomorrow_start = today_start + timedelta(days=1)
        day_after = tomorrow_start + timedelta(days=1)

        events = schedule_data.get("events", [])
        today_ev = [e for e in events if today_start <= _parse_dt(e["start"]) < tomorrow_start]
        tomorrow_ev = [e for e in events if tomorrow_start <= _parse_dt(e["start"]) < day_after]

        region_label = REGIONS[region].name if region in REGIONS else region
        today_title = f"Сьогодні — {_format_date(now)} ({DAY_NAMES[now.weekday()]})"
        tomorrow_title = f"Завтра — {_format_date(tomorrow_start)} ({DAY_NAMES[tomorrow_start.weekday()]})"

        # Estimate total height (sections + header + legend + padding)
        header_h = 66
        sep_gap = 14
        legend_h = 32
        today_h = _section_height(len(today_ev))
        tomorrow_h = _section_height(len(tomorrow_ev))
        total_h = PAD + header_h + sep_gap + today_h + 12 + tomorrow_h + 14 + legend_h + PAD

        img = Image.new("RGB", (IMG_WIDTH, total_h), C_BG)
        draw = ImageDraw.Draw(img)
        cw = IMG_WIDTH - PAD * 2
        y = PAD

        # ── Header ───────────────────────────────────────────────────────────
        draw.text((PAD, y), "ВОЛЬТИК", font=fonts["brand"], fill=C_BRAND)
        draw.text((PAD, y + 28), region_label, font=fonts["region"], fill=C_MUTED)

        q_txt = f"Черга {queue}"
        qtw = _tw(draw, q_txt, fonts["queue"])
        qth = _th(draw, q_txt, fonts["queue"])
        bp = 12
        bx = IMG_WIDTH - PAD - qtw - bp * 2
        by = y + (header_h - qth - 10) // 2
        draw.rounded_rectangle(
            [bx, by, bx + qtw + bp * 2, by + qth + 10],
            radius=14, fill=C_CARD, outline=C_BORDER,
        )
        draw.text((bx + bp, by + 5), q_txt, font=fonts["queue"], fill=C_TEXT)

        y += header_h
        draw.line([(PAD, y), (IMG_WIDTH - PAD, y)], fill=C_BORDER, width=1)
        y += sep_gap

        # ── Today ─────────────────────────────────────────────────────────────
        actual_today_h = _draw_section(
            draw, PAD, y, cw, today_title, today_ev, today_start, fonts, now=now
        )
        y += actual_today_h + 12

        # ── Tomorrow ──────────────────────────────────────────────────────────
        actual_tomorrow_h = _draw_section(
            draw, PAD, y, cw, tomorrow_title, tomorrow_ev, tomorrow_start, fonts, now=None
        )
        y += actual_tomorrow_h + 14

        # ── Legend ────────────────────────────────────────────────────────────
        lx = PAD + 8
        legend_items = [
            (SEG_ON,    "є світло"),
            (SEG_OFF,   "відключення"),
            (SEG_MAYBE, "можливе"),
        ]
        for color, label in legend_items:
            draw.rectangle([lx, y + 5, lx + 12, y + 15], fill=color, outline=C_BORDER)
            lx += 16
            draw.text((lx, y + 3), label, font=fonts["legend"], fill=C_DIM)
            lx += _tw(draw, label, fonts["legend"]) + 18

        # Blue "зараз" indicator
        draw.rectangle([lx, y + 7, lx + 2, y + 13], fill=C_BLUE)
        lx += 6
        draw.text((lx, y + 3), "зараз", font=fonts["legend"], fill=C_DIM)

        # Crop to actual content
        final_h = y + legend_h + PAD
        if final_h < total_h:
            img = img.crop((0, 0, IMG_WIDTH, final_h))

        buf = io.BytesIO()
        img.save(buf, "PNG", optimize=True)
        return buf.getvalue()

    except Exception as e:
        logger.warning("Chart render error for %s/%s: %s", region, queue, e)
        return None


async def generate_schedule_chart(region: str, queue: str, schedule_data: dict) -> bytes | None:
    """Generate a PNG chart for the given schedule.

    Drawing is CPU-bound and runs in the default thread-pool executor so the
    asyncio event loop is never blocked.
    """
    try:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, _generate_sync, region, queue, schedule_data)
    except Exception as e:
        logger.warning("Chart generation failed for %s/%s: %s", region, queue, e)
        return None
