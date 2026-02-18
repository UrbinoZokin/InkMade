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


def _wrap_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont,
    max_width: float,
    max_lines: Optional[int] = 2,
) -> List[str]:
    words = text.split()
    lines: List[str] = []
    cur = ""
    for w in words:
        test = (cur + " " + w).strip()
        if draw.textlength(test, font=font) <= max_width:
            cur = test
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines if max_lines is None else lines[:max_lines]

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

    time_strings = [f"{_fmt_time(e.start)}–{_fmt_time(e.end)}" for e in events_sorted if not e.all_day]
    max_time_w = max((d.textlength(s, font=font_time) for s in time_strings), default=0)
    gap = int(font_time.size * 0.6)
    time_col_w = max_time_w
    title_line_h = font_title.size + 8
    min_row_h = 80
    banner_h = 70
    ups_text = _format_ups_status(ups_status)
    updated_gap = 10
    updated_text_h = font_small.size + 6
    updated_text = f"Updated: {now.astimezone(tz).strftime('%-I:%M %p').lower()}"
    updated_text_w = d.textlength(updated_text, font=font_small)
    updated_block_h = updated_text_h + updated_gap
    ups_on_second_line = False
    ups_text_h = font_small.size + 6
    wifi_icon_size = max(18, int(font_small.size * 0.9))
    wifi_left = canvas_w - padding - wifi_icon_size
    if ups_text:
        ups_text_w = d.textlength(ups_text, font=font_small)
        ups_right = wifi_left - 10
        min_ups_x = padding + updated_text_w + 10
        if ups_right - ups_text_w < min_ups_x:
            ups_on_second_line = True
            updated_block_h += ups_text_h + 8
    max_y = canvas_h - padding - (banner_h if show_sleep_banner else 0) - updated_block_h

    for e in events_sorted:
        time_str = "" if e.all_day else f"{_fmt_time(e.start)}–{_fmt_time(e.end)}"

        x_title = padding + time_col_w + gap
        max_width = canvas_w - padding - x_title
        max_lines = None if e.all_day else 2
        lines = _wrap_text(d, e.title, font_title, max_width, max_lines=max_lines)

        row_start_y = y
        content_y = row_start_y + title_line_h * len(lines) + 6
        detail_text = (e.travel_time_text or "").strip()
        if detail_text:
            content_y += font_small.size + 8
        row_h = max(min_row_h, content_y - row_start_y + 8)
        total_row_h = row_h + 18

        if y + total_row_h > max_y:
            d.text((padding, y), "…", fill="black", font=font_header)
            break

        # Time column
        if time_str:
            d.text((padding, y), time_str, fill="black", font=font_time)
            time_w = d.textlength(time_str, font=font_time)
            x_time = padding + max(0, time_col_w - time_w)
            d.text((x_time, y), time_str, fill="black", font=font_time)

        for i, line in enumerate(lines):
            d.text((x_title, y + i * title_line_h), line, fill="black", font=font_title)

        if detail_text:
            d.text((x_title, content_y), detail_text, fill="black", font=font_small)
            content_y += font_small.size + 8

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

            tomorrow_profiles = [
                {"time": 30, "title": 34, "title_line_h": 32, "min_row_h": 55, "sep": 14},
                {"time": 28, "title": 32, "title_line_h": 30, "min_row_h": 52, "sep": 12},
                {"time": 26, "title": 30, "title_line_h": 28, "min_row_h": 48, "sep": 10},
                {"time": 24, "title": 28, "title_line_h": 26, "min_row_h": 44, "sep": 8},
                {"time": 22, "title": 26, "title_line_h": 24, "min_row_h": 42, "sep": 8},
            ]

            chosen_profile = tomorrow_profiles[-1]
            chosen_lines: List[List[str]] = []
            chosen_time_strings: List[str] = []
            for profile in tomorrow_profiles:
                profile_time_font = _load_font(profile["time"])
                profile_title_font = _load_font(profile["title"])
                profile_time_strings = [
                    f"{_fmt_time(e.start)}–{_fmt_time(e.end)}"
                    for e in tomorrow_sorted
                    if not e.all_day
                ]
                profile_time_w = max(
                    (d.textlength(s, font=profile_time_font) for s in profile_time_strings),
                    default=0,
                )
                profile_gap = int(profile_time_font.size * 0.6)
                x_title = padding + profile_time_w + profile_gap
                max_width = canvas_w - padding - x_title
                profile_lines = [
                    _wrap_text(
                        d,
                        e.title,
                        profile_title_font,
                        max_width,
                        max_lines=None if e.all_day else 2,
                    )
                    for e in tomorrow_sorted
                ]
                test_y = y
                fits = True
                for e, lines in zip(tomorrow_sorted, profile_lines):
                    content_y = test_y + profile["title_line_h"] * len(lines) + 4
                    if (e.travel_time_text or "").strip():
                        content_y += font_small.size + 6
                    row_h = max(profile["min_row_h"], content_y - test_y + 6)
                    total_h = row_h + profile["sep"]
                    if test_y + total_h > max_y:
                        fits = False
                        break
                    test_y += total_h
                if fits:
                    chosen_profile = profile
                    chosen_lines = profile_lines
                    chosen_time_strings = profile_time_strings
                    break

            time_font = _load_font(chosen_profile["time"])
            title_font = _load_font(chosen_profile["title"])
            if not chosen_lines:
                chosen_time_strings = [
                    f"{_fmt_time(e.start)}–{_fmt_time(e.end)}"
                    for e in tomorrow_sorted
                    if not e.all_day
                ]
                fallback_time_w = max(
                    (d.textlength(s, font=time_font) for s in chosen_time_strings),
                    default=0,
                )
                fallback_gap = int(time_font.size * 0.6)
                x_title = padding + fallback_time_w + fallback_gap
                max_width = canvas_w - padding - x_title
                chosen_lines = [
                    _wrap_text(
                        d,
                        e.title,
                        title_font,
                        max_width,
                        max_lines=None if e.all_day else 2,
                    )
                    for e in tomorrow_sorted
                ]

            time_col_w = max(
                (d.textlength(s, font=time_font) for s in chosen_time_strings),
                default=0,
            )
            gap = int(time_font.size * 0.6)

            for e, lines in zip(tomorrow_sorted, chosen_lines):
                time_str = "" if e.all_day else f"{_fmt_time(e.start)}–{_fmt_time(e.end)}"
                row_start_y = y
                content_y = row_start_y + chosen_profile["title_line_h"] * len(lines) + 4
                detail_text = (e.travel_time_text or "").strip()
                if detail_text:
                    content_y += font_small.size + 6
                row_h = max(chosen_profile["min_row_h"], content_y - row_start_y + 6)
                total_h = row_h + chosen_profile["sep"]

                if y + total_h > max_y:
                    d.text((padding, y), "…", fill="black", font=font_tomorrow_header)
                    break

                if time_str:
                    d.text((padding, y), time_str, fill="black", font=time_font)

                x_title = padding + time_col_w + gap
                for i, line in enumerate(lines):
                    d.text(
                        (x_title, y + i * chosen_profile["title_line_h"]),
                        line,
                        fill="black",
                        font=title_font,
                    )

                if detail_text:
                    d.text(
                        (x_title, row_start_y + chosen_profile["title_line_h"] * len(lines) + 4),
                        detail_text,
                        fill="black",
                        font=font_small,
                    )

                y = row_start_y + row_h
                d.line((padding, y, canvas_w - padding, y), fill="black", width=1)
                y += chosen_profile["sep"]
    bottom_y = canvas_h - padding - (banner_h if show_sleep_banner else 0)
    updated_y = bottom_y - updated_text_h
    if ups_text:
        ups_text_w = d.textlength(ups_text, font=font_small)
        ups_right = wifi_left - 10
        if ups_on_second_line:
            ups_x = padding
            ups_y = updated_y - ups_text_h - 8
        else:
            ups_x = max(padding, ups_right - ups_text_w)
            ups_y = updated_y
        d.text((ups_x, ups_y), ups_text, fill="black", font=font_small)
    d.text((padding, updated_y), updated_text, fill="black", font=font_small)
    usable_canvas_h = canvas_h - (banner_h if show_sleep_banner else 0)
    _draw_wifi_status(d, canvas_w, usable_canvas_h, padding, wifi_status, font_small)

    if show_sleep_banner:
        y0 = canvas_h - padding - banner_h
        d.rectangle((padding, y0, canvas_w - padding, y0 + banner_h), outline="black", width=2)
        d.text((padding + 20, y0 + 18), sleep_banner_text, fill="black", font=font_small)

    return img

def _format_ups_status(ups_status: Optional[dict]) -> Optional[str]:
    if not ups_status:
        return None

    percent_value = (
        ups_status.get("battery_percent")
        or ups_status.get("battery_percentage")
        or ups_status.get("battery")
    )
    power_source = (
        ups_status.get("power_source")
        or ups_status.get("source")
        or ups_status.get("status")
    )
    if percent_value is None or not power_source:
        return None

    try:
        percent = float(percent_value)
    except (TypeError, ValueError):
        return None

    if percent <= 1:
        percent *= 100
    percent = int(round(percent))
    return f"Battery {percent}% · {power_source}"

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
