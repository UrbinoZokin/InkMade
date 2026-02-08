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

def _format_header(now: datetime) -> tuple[str, str]:
    # Example: Thursday / February 5, 2026
    return now.strftime("%A"), now.strftime("%B %-d, %Y")

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
    wifi_status: str = "connected",
    ups_status: Optional[dict] = None,
    tomorrow_events: Optional[List[Event]] = None,
) -> Image.Image:
    img = Image.new("RGB", (canvas_w, canvas_h), "white")
    d = ImageDraw.Draw(img)

    font_header = _load_font(72)
    font_tomorrow_header = _load_font(38)
    font_time = _load_font(46)
    font_title = _load_font(52)
    font_small = _load_font(30)
    font_time_small = _load_font(30)
    font_title_small = _load_font(34)

    padding = 40
    y = padding

    header_day, header_date = _format_header(now.astimezone(tz))
    header_gap = 8
    header_bottom_gap = 12
    header_line_h = font_header.size + 6
    header_day_w = d.textlength(header_day, font=font_header)
    header_day_x = (canvas_w - header_day_w) / 2
    d.text((header_day_x, y), header_day, fill="black", font=font_header)
    y += header_line_h + header_gap
    header_date_w = d.textlength(header_date, font=font_header)
    header_date_x = (canvas_w - header_date_w) / 2
    d.text((header_date_x, y), header_date, fill="black", font=font_header)
    y += header_line_h + header_bottom_gap

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
    banner_h = 70
    updated_gap = 10
    updated_text_h = font_small.size + 6
    updated_block_h = updated_text_h + updated_gap
    max_y = canvas_h - padding - (banner_h if show_sleep_banner else 0) - updated_block_h

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

        row_start_y = y
        content_y = row_start_y + title_line_h * len(lines) + 6

        if e.location:
            loc = e.location.strip()
            if loc:
                d.text((x_title, content_y), loc, fill="black", font=font_small)
                content_y += font_small.size + 8

        row_h = max(min_row_h, content_y - row_start_y + 8)
        y = row_start_y + row_h

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

            time_strings = [
                "All day" if e.all_day else f"{_fmt_time(e.start)}–{_fmt_time(e.end)}"
                for e in tomorrow_sorted
            ]
            max_time_w = max(
                (d.textlength(s, font=font_time_small) for s in time_strings), default=0
            )
            gap = int(font_time_small.size * 0.6)
            time_col_w = max_time_w
            for e in tomorrow_sorted:
                if y > max_y:
                    d.text((padding, y), "…", fill="black", font=font_tomorrow_header)
                    break

                if e.all_day:
                    time_str = "All day"
                else:
                    time_str = f"{_fmt_time(e.start)}–{_fmt_time(e.end)}"

                d.text((padding, y), time_str, fill="black", font=font_time_small)

                x_title = padding + time_col_w + gap
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

                row_start_y = y
                content_y = row_start_y + 32 * len(lines) + 4

                if e.location:
                    loc = e.location.strip()
                    if loc:
                        d.text((x_title, content_y), loc, fill="black", font=font_small)
                        content_y += font_small.size + 6

                row_h = max(55, content_y - row_start_y + 6)
                y = row_start_y + row_h

                d.line((padding, y, canvas_w - padding, y), fill="black", width=1)
                y += 14
    updated_text = f"Updated: {now.astimezone(tz).strftime('%-I:%M %p').lower()}"
    updated_y = canvas_h - padding - (banner_h if show_sleep_banner else 0) - updated_text_h
    d.text((padding, updated_y), updated_text, fill="black", font=font_small)
    usable_canvas_h = canvas_h - (banner_h if show_sleep_banner else 0)
    _draw_wifi_status(d, canvas_w, usable_canvas_h, padding, wifi_status, font_small)
    
    if show_sleep_banner:
        y0 = canvas_h - padding - banner_h
        d.rectangle((padding, y0, canvas_w - padding, y0 + banner_h), outline="black", width=2)
        d.text((padding + 20, y0 + 18), sleep_banner_text, fill="black", font=font_small)

    return img

def _draw_wifi_status(
    draw: ImageDraw.ImageDraw,
    canvas_w: int,
    canvas_h: int,
    padding: int,
    status: str,
    font: ImageFont.FreeTypeFont,
) -> None:
    if not status:
        return

    status = status.lower().strip()
    icon_size = max(18, int(font.size * 0.9))
    right = canvas_w - padding
    bottom = canvas_h - padding
    left = right - icon_size
    top = bottom - icon_size
    center_x = (left + right) / 2
    center_y = bottom

    arc_count = 3
    arc_step = icon_size * 0.18
    for i in range(arc_count):
        inset = i * arc_step
        bbox = (left + inset, top + inset, right - inset, bottom - inset)
        draw.arc(bbox, start=200, end=340, fill="black", width=2)

    dot_r = max(2, int(icon_size * 0.08))
    draw.ellipse(
        (center_x - dot_r, center_y - dot_r - 2, center_x + dot_r, center_y + dot_r - 2),
        fill="black",
    )

    if status == "disconnected":
        draw.line((left, top, right, bottom), fill="black", width=3)
        draw.line((left, bottom, right, top), fill="black", width=3)
