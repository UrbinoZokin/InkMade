from __future__ import annotations
from datetime import datetime
from typing import List, Optional
from zoneinfo import ZoneInfo
from PIL import Image, ImageDraw, ImageFont

from .models import Event
from .weather import WeatherAlert

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


def _weather_label(e: Event) -> str:
    start_label = " ".join(part for part in [e.weather_icon, e.weather_text] if part).strip()
    end_label = " ".join(part for part in [e.weather_end_icon, e.weather_end_text] if part).strip()
    if start_label and end_label:
        return f"{start_label} → {end_label}"
    return start_label or end_label



def _lerp_color(start: tuple[int, int, int], end: tuple[int, int, int], ratio: float) -> tuple[int, int, int]:
    return tuple(int(round(s + (e - s) * ratio)) for s, e in zip(start, end))


def _temperature_color(temp_f: Optional[int]) -> tuple[int, int, int]:
    if temp_f is None:
        return (0, 0, 0)

    # Classic cold->hot weather palette.
    anchors = [
        (-20, (49, 54, 149)),
        (32, (66, 165, 245)),
        (50, (38, 198, 218)),
        (68, (102, 187, 106)),
        (80, (255, 241, 118)),
        (92, (255, 167, 38)),
        (110, (229, 57, 53)),
    ]

    if temp_f <= anchors[0][0]:
        return anchors[0][1]
    if temp_f >= anchors[-1][0]:
        return anchors[-1][1]

    for (left_temp, left_color), (right_temp, right_color) in zip(anchors, anchors[1:]):
        if left_temp <= temp_f <= right_temp:
            span = right_temp - left_temp
            ratio = 0.0 if span == 0 else (temp_f - left_temp) / span
            return _lerp_color(left_color, right_color, ratio)

    return anchors[-1][1]


def _draw_weather_text(
    draw: ImageDraw.ImageDraw,
    x: float,
    y: float,
    event: Event,
    font: ImageFont.FreeTypeFont,
) -> None:
    icon = event.weather_icon or ""
    temp_text = event.weather_text or ""
    if not icon and not temp_text:
        return

    if event.weather_end_icon or event.weather_end_text:
        if icon:
            draw.text((x, y), icon, fill="black", font=font)
            x += draw.textlength(icon, font=font)

        if icon and temp_text:
            spacer = " "
            draw.text((x, y), spacer, fill="black", font=font)
            x += draw.textlength(spacer, font=font)

        if temp_text:
            draw.text((x, y), temp_text, fill=_temperature_color(event.weather_temperature_f), font=font)
            x += draw.textlength(temp_text, font=font)

        arrow = " → "
        draw.text((x, y), arrow, fill="black", font=font)
        x += draw.textlength(arrow, font=font)

        if event.weather_end_icon:
            draw.text((x, y), event.weather_end_icon, fill="black", font=font)
            x += draw.textlength(event.weather_end_icon, font=font)

        if event.weather_end_icon and event.weather_end_text:
            spacer = " "
            draw.text((x, y), spacer, fill="black", font=font)
            x += draw.textlength(spacer, font=font)

        if event.weather_end_text:
            draw.text(
                (x, y),
                event.weather_end_text,
                fill=_temperature_color(event.weather_end_temperature_f),
                font=font,
            )
        return

    if icon:
        draw.text((x, y), icon, fill="black", font=font)
        x += draw.textlength(icon, font=font)

    if icon and temp_text:
        spacer = " "
        draw.text((x, y), spacer, fill="black", font=font)
        x += draw.textlength(spacer, font=font)

    if temp_text:
        draw.text((x, y), temp_text, fill=_temperature_color(event.weather_temperature_f), font=font)


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


def _today_event_layout(
    draw: ImageDraw.ImageDraw,
    event: Event,
    canvas_w: int,
    padding: int,
    time_col_w: float,
    column_gap: int,
    font_time: ImageFont.FreeTypeFont,
    font_title: ImageFont.FreeTypeFont,
    font_small: ImageFont.FreeTypeFont,
    font_today_weather: ImageFont.FreeTypeFont,
    title_line_h: int,
    min_row_h: int,
) -> dict:
    time_str = "" if event.all_day else f"{_fmt_time(event.start)}–{_fmt_time(event.end)}"
    x_title = padding if event.all_day else padding + time_col_w + column_gap
    max_width = (canvas_w - (2 * padding)) if event.all_day else (canvas_w - padding - x_title)
    max_lines = None if event.all_day else 2
    lines = _wrap_text(draw, event.title, font_title, max_width, max_lines=max_lines)

    content_h = title_line_h * len(lines) + 6
    detail_text = (event.travel_time_text or "").strip()
    if detail_text:
        content_h += font_small.size + 8

    left_col_h = 0
    if time_str:
        left_col_h = font_time.size
        if _weather_label(event):
            left_col_h += 4 + font_today_weather.size

    row_h = max(min_row_h, content_h + 8, left_col_h + 8)
    return {
        "event": event,
        "time_str": time_str,
        "x_title": x_title,
        "lines": lines,
        "detail_text": detail_text,
        "row_h": row_h,
        "total_row_h": row_h + 18,
    }


def _prepare_weather_alert_lines(
    draw: ImageDraw.ImageDraw,
    alerts: List[WeatherAlert],
    font: ImageFont.FreeTypeFont,
    max_width: float,
) -> List[str]:
    if not alerts:
        return []

    lines: List[str] = []
    for alert in alerts:
        wrapped = _wrap_text(draw, f"• {alert.headline}", font, max_width, max_lines=2)
        lines.extend(wrapped)
    return lines

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
    weather_alerts: Optional[List[WeatherAlert]] = None,
) -> Image.Image:
    img = Image.new("RGB", (canvas_w, canvas_h), "white")
    d = ImageDraw.Draw(img)

    font_header = _load_font(72)
    font_tomorrow_header = _load_font(38)
    font_time = _load_font(46)
    font_title = _load_font(52)
    font_small = _load_font(30)
    font_alert_header = _load_font(34)
    font_today_weather = _load_font(38)

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
    weather_strings = [_weather_label(e) for e in events_sorted if not e.all_day and _weather_label(e)]
    max_time_w = max((d.textlength(s, font=font_time) for s in time_strings), default=0)
    max_weather_w = max((d.textlength(s, font=font_today_weather) for s in weather_strings), default=0)
    time_col_w = max(max_time_w, max_weather_w)
    column_gap = 20
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

    weather_alert_lines = _prepare_weather_alert_lines(
        d,
        weather_alerts or [],
        font_small,
        canvas_w - (2 * padding),
    )
    weather_alert_line_h = font_small.size + 4
    weather_alert_header_h = font_alert_header.size + 6
    weather_alert_block_h = 0
    if weather_alert_lines:
        weather_alert_block_h = weather_alert_header_h + (len(weather_alert_lines) * weather_alert_line_h) + 24

    max_y = canvas_h - padding - (banner_h if show_sleep_banner else 0) - updated_block_h - weather_alert_block_h

    today_layouts = [
        _today_event_layout(
            d,
            e,
            canvas_w,
            padding,
            time_col_w,
            column_gap,
            font_time,
            font_title,
            font_small,
            font_today_weather,
            title_line_h,
            min_row_h,
        )
        for e in events_sorted
    ]
    overflow_mode = y + sum(layout["total_row_h"] for layout in today_layouts) > max_y

    if overflow_mode:
        now_local = now.astimezone(tz)
        pending_layouts = [
            layout for layout in today_layouts if layout["event"].all_day or layout["event"].end > now_local
        ]
        overflow_notice_h = font_small.size + 16
        visible_layouts = []
        test_y = y
        for idx, layout in enumerate(pending_layouts):
            has_more_hidden = idx < len(pending_layouts) - 1
            reserve_notice = overflow_notice_h if has_more_hidden else 0
            if test_y + layout["total_row_h"] + reserve_notice > max_y:
                break
            visible_layouts.append(layout)
            test_y += layout["total_row_h"]

        hidden_count = len(pending_layouts) - len(visible_layouts)
    else:
        visible_layouts = today_layouts
        hidden_count = 0

    for idx, layout in enumerate(visible_layouts):
        e = layout["event"]
        time_str = layout["time_str"]
        x_title = layout["x_title"]
        lines = layout["lines"]
        detail_text = layout["detail_text"]
        row_h = layout["row_h"]

        row_start_y = y
        content_y = row_start_y + title_line_h * len(lines) + 6

        if not overflow_mode and y + layout["total_row_h"] > max_y:
            d.text((padding, y), "…", fill="black", font=font_header)
            break

        # Time column
        if time_str:
            time_w = d.textlength(time_str, font=font_time)
            x_time = padding + max(0, time_col_w - time_w)
            d.text((x_time, y), time_str, fill="black", font=font_time)
            weather_text = _weather_label(e)
            if weather_text:
                weather_w = d.textlength(weather_text, font=font_today_weather)
                x_weather = padding + max(0, (time_col_w - weather_w) / 2)
                _draw_weather_text(d, x_weather, y + font_time.size + 4, e, font_today_weather)

            divider_x = padding + time_col_w + (column_gap // 2)
            d.line((divider_x, y, divider_x, row_start_y + row_h), fill="black", width=1)

        for i, line in enumerate(lines):
            d.text((x_title, y + i * title_line_h), line, fill="black", font=font_title)

        if detail_text:
            d.text((x_title, content_y), detail_text, fill="black", font=font_small)
            content_y += font_small.size + 8

        y = row_start_y + row_h

        # subtle separator
        is_last_today_event = idx == len(visible_layouts) - 1 and hidden_count == 0
        if is_last_today_event and tomorrow_events:
            d.line((padding, y, canvas_w - padding, y), fill="black", width=2)
            d.line((padding, y + 6, canvas_w - padding, y + 6), fill="black", width=2)
        else:
            d.line((padding, y, canvas_w - padding, y), fill="black", width=1)
        y += 18

    if overflow_mode and hidden_count > 0 and y + font_small.size + 6 <= max_y:
        d.text((padding, y), f"Plus {hidden_count} more events", fill="black", font=font_small)
        y += font_small.size + 8
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
                profile_weather_strings = [_weather_label(e) for e in tomorrow_sorted if not e.all_day and _weather_label(e)]
                profile_time_w = max(
                    (d.textlength(s, font=profile_time_font) for s in profile_time_strings),
                    default=0,
                )
                profile_weather_w = max((d.textlength(s, font=font_small) for s in profile_weather_strings), default=0)
                profile_gap = int(profile_time_font.size * 0.45)
                profile_lines = [
                    _wrap_text(
                        d,
                        e.title,
                        profile_title_font,
                        (canvas_w - (2 * padding))
                        if e.all_day
                        else (canvas_w - padding - (padding + profile_time_w + profile_weather_w + (profile_gap * 2))),
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
                fallback_weather_strings = [_weather_label(e) for e in tomorrow_sorted if not e.all_day and _weather_label(e)]
                fallback_weather_w = max((d.textlength(s, font=font_small) for s in fallback_weather_strings), default=0)
                fallback_gap = int(time_font.size * 0.45)
                chosen_lines = [
                    _wrap_text(
                        d,
                        e.title,
                        title_font,
                        (canvas_w - (2 * padding))
                        if e.all_day
                        else (canvas_w - padding - (padding + fallback_time_w + fallback_weather_w + (fallback_gap * 2))),
                        max_lines=None if e.all_day else 2,
                    )
                    for e in tomorrow_sorted
                ]

            time_col_w = max(
                (d.textlength(s, font=time_font) for s in chosen_time_strings),
                default=0,
            )
            weather_col_w = max(
                (d.textlength(_weather_label(e), font=font_small) for e in tomorrow_sorted if not e.all_day and _weather_label(e)),
                default=0,
            )
            gap = int(time_font.size * 0.45)

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
                    time_w = d.textlength(time_str, font=time_font)
                    d.text((padding + max(0, time_col_w - time_w), y), time_str, fill="black", font=time_font)
                    weather_text = _weather_label(e)
                    if weather_text:
                        _draw_weather_text(d, padding + time_col_w + gap, y, e, font_small)

                    first_divider_x = padding + time_col_w + (gap // 2)
                    second_divider_x = padding + time_col_w + gap + weather_col_w + (gap // 2)
                    d.line((first_divider_x, y, first_divider_x, row_start_y + row_h), fill="black", width=1)
                    d.line((second_divider_x, y, second_divider_x, row_start_y + row_h), fill="black", width=1)

                x_title = padding if e.all_day else padding + time_col_w + weather_col_w + (gap * 2)
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
    alert_bottom_y = bottom_y - updated_block_h
    if weather_alert_lines:
        alert_top = alert_bottom_y - weather_alert_block_h
        alert_bottom = alert_bottom_y - 6
        d.rectangle((padding, alert_top, canvas_w - padding, alert_bottom), outline="red", width=3)
        alert_header_y = alert_top + 8
        d.text((padding + 12, alert_header_y), "NATIONAL WEATHER SERVICE ALERT", fill="red", font=font_alert_header)

        line_start_y = alert_header_y + weather_alert_header_h
        d.line((padding + 10, line_start_y - 4, canvas_w - padding - 10, line_start_y - 4), fill="red", width=2)
        for line in weather_alert_lines:
            d.text((padding + 12, line_start_y), line, fill="black", font=font_small)
            line_start_y += weather_alert_line_h

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
