from __future__ import annotations
from dataclasses import asdict
from datetime import datetime
from typing import List, Optional
from zoneinfo import ZoneInfo
from PIL import Image, ImageDraw, ImageFont

from .models import Event

def _load_font(size: int) -> ImageFont.FreeTypeFont:
    # DejaVu is commonly available on Raspberry Pi; install via apt in scripts/install.sh
    return ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", size)

def _format_header(now: datetime) -> str:
    # Example: Thursday, February 5, 2026
    return now.strftime("%A, %B %-d, %Y")

def _fmt_time(dt: datetime) -> str:
    return dt.strftime("%-I:%M %p").lower()

def _event_sort_key(e: Event):
    # all-day first, then start time, then title
    return (0 if e.all_day else 1, e.start, e.title.lower())

def render_daily_schedule(
    canvas_w: int,
    canvas_h: int,
    now: datetime,
    events: List[Event],
    tz: ZoneInfo,
    show_sleep_banner: bool,
    sleep_banner_text: str,
    tomorrow_events: Optional[List[Event]] = None,
) -> Image.Image:
    img = Image.new("RGB", (canvas_w, canvas_h), "white")
    d = ImageDraw.Draw(img)

    font_header = _load_font(60)
    font_tomorrow_header = _load_font(32)
    font_time = _load_font(36)
    font_title = _load_font(40)
    font_small = _load_font(30)
    font_time_small = _load_font(24)
    font_title_small = _load_font(28)

    padding = 40
    y = padding

    header = _format_header(now.astimezone(tz))
    d.text((padding, y), header, fill="black", font=font_header)
    y += 80

    d.text((padding, y), f"Updated: {now.astimezone(tz).strftime('%-I:%M %p').lower()}", fill="black", font=font_small)
    y += 45

    # Divider
    d.line((padding, y, canvas_w - padding, y), fill="black", width=2)
    y += 25

    events_sorted = sorted(events, key=_event_sort_key)

    time_strings = [
        "All day" if e.all_day else f"{_fmt_time(e.start)}–{_fmt_time(e.end)}"
        for e in events_sorted
    ]
    max_time_w = max((d.textlength(s, font=font_time) for s in time_strings), default=0)
    gap = int(font_time.size * 0.6)
    time_col_w = max_time_w
    title_line_h = font_title.size + 8
    min_row_h = 80
    max_y = canvas_h - padding - (70 if show_sleep_banner else 0)

    for e in events_sorted:
        if y > max_y:
            d.text((padding, y), "…", fill="black", font=font_header)
            break

        if e.all_day:
            time_str = "All day"
        else:
            time_str = f"{_fmt_time(e.start)}–{_fmt_time(e.end)}"

        # Time column
        d.text((padding, y), time_str, fill="black", font=font_time)
        time_w = d.textlength(time_str, font=font_time)
        x_time = padding + max(0, time_col_w - time_w)
        d.text((x_time, y), time_str, fill="black", font=font_time)
        # Title (wrap)
        x_title = padding + time_col_w + gap
        title = e.title

        # Basic wrapping
        max_width = canvas_w - padding - x_title
        words = title.split()
        lines = []
        cur = ""
        for w in words:
            test = (cur + " " + w).strip()
            if d.textlength(test, font=font_title) <= max_width:
                cur = test
            else:
                if cur:
                    lines.append(cur)
                cur = w
        if cur:
            lines.append(cur)
        lines = lines[:2]  # keep it tidy

        for i, line in enumerate(lines):
            d.text((x_title, y + i * title_line_h), line, fill="black", font=font_title)

        y += max(min_row_h, title_line_h * len(lines) + 12)

        if e.location:
            loc = e.location.strip()
            if loc:
                d.text((x_title, y - 12), loc, fill="black", font=font_small)
                y += font_small.size + 10

        # subtle separator
        d.line((padding, y, canvas_w - padding, y), fill="black", width=1)
        y += 18
    if tomorrow_events:
        tomorrow_sorted = sorted(tomorrow_events, key=_event_sort_key)
        header_gap = 10
        tomorrow_header_h = 38
        if y + header_gap + tomorrow_header_h < max_y:
            y += header_gap
            d.text((padding, y), "Tomorrow", fill="black", font=font_tomorrow_header)
            y += tomorrow_header_h
            d.line((padding, y, canvas_w - padding, y), fill="black", width=1)
            y += 16

            time_col_w = 170
            for e in tomorrow_sorted:
                if y > max_y:
                    d.text((padding, y), "…", fill="black", font=font_tomorrow_header)
                    break

                if e.all_day:
                    time_str = "All day"
                else:
                    time_str = f"{_fmt_time(e.start)}–{_fmt_time(e.end)}"

                d.text((padding, y), time_str, fill="black", font=font_time_small)

                x_title = padding + time_col_w
                title = e.title
                max_width = canvas_w - padding - x_title
                words = title.split()
                lines = []
                cur = ""
                for w in words:
                    test = (cur + " " + w).strip()
                    if d.textlength(test, font=font_title_small) <= max_width:
                        cur = test
                    else:
                        if cur:
                            lines.append(cur)
                        cur = w
                if cur:
                    lines.append(cur)
                lines = lines[:2]

                for i, line in enumerate(lines):
                    d.text((x_title, y + i * 32), line, fill="black", font=font_title_small)

                y += max(55, 32 * len(lines) + 8)

                if e.location:
                    loc = e.location.strip()
                    if loc:
                        d.text((x_title, y - 8), loc, fill="black", font=font_small)
                        y += 22

                d.line((padding, y, canvas_w - padding, y), fill="black", width=1)
                y += 14
    if show_sleep_banner:
        banner_h = 70
        y0 = canvas_h - padding - banner_h
        d.rectangle((padding, y0, canvas_w - padding, y0 + banner_h), outline="black", width=2)
        d.text((padding + 20, y0 + 18), sleep_banner_text, fill="black", font=font_small)

    return img
