from __future__ import annotations
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional
from zoneinfo import ZoneInfo
from PIL import Image, ImageDraw, ImageFont

from .models import Event, Reminder
from .weather import WeatherAlert

def _load_font(size: int) -> ImageFont.FreeTypeFont:
    # DejaVu is commonly available on Raspberry Pi; install via apt in scripts/install.sh
    return ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", size)


def _load_bold_font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", size)

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


# Stroke outline applied to temperature text in _draw_weather_text. It widens the
# rendered glyphs beyond their textlength, so layout measurements must allow for it.
WEATHER_TEMP_STROKE_WIDTH = 2


def _weather_text_width(
    draw: ImageDraw.ImageDraw,
    event: Event,
    font: ImageFont.FreeTypeFont,
    temperature_font: ImageFont.FreeTypeFont,
) -> float:
    """Width of the weather label as actually rendered by _draw_weather_text.

    Temperatures are drawn with the bold ``temperature_font`` and a stroke outline,
    both of which make them wider than the plain ``font``. Measuring the column with
    the plain font (as ``_weather_label`` widths do) underestimates the real width
    and lets the temperature bleed into the title column. Mirroring the draw logic
    here keeps the reserved column wide enough.
    """
    icon = event.weather_icon or ""
    temp_text = event.weather_text or ""
    if not icon and not temp_text:
        return 0.0

    def _temp_width(text: str) -> float:
        if not text:
            return 0.0
        return draw.textlength(text, font=temperature_font) + (2 * WEATHER_TEMP_STROKE_WIDTH)

    width = 0.0
    if event.weather_end_icon or event.weather_end_text:
        if icon:
            width += draw.textlength(icon, font=font)
        if icon and temp_text:
            width += draw.textlength(" ", font=font)
        width += _temp_width(temp_text)
        width += draw.textlength(" → ", font=font)
        if event.weather_end_icon:
            width += draw.textlength(event.weather_end_icon, font=font)
        if event.weather_end_icon and event.weather_end_text:
            width += draw.textlength(" ", font=font)
        width += _temp_width(event.weather_end_text or "")
        return width

    if icon:
        width += draw.textlength(icon, font=font)
    if icon and temp_text:
        width += draw.textlength(" ", font=font)
    width += _temp_width(temp_text)
    return width



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
    temperature_font: ImageFont.FreeTypeFont,
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
            draw.text(
                (x, y),
                temp_text,
                fill=_temperature_color(event.weather_temperature_f),
                font=temperature_font,
                stroke_width=WEATHER_TEMP_STROKE_WIDTH,
                stroke_fill="black",
            )
            x += draw.textlength(temp_text, font=temperature_font) + (2 * WEATHER_TEMP_STROKE_WIDTH)

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
                font=temperature_font,
                stroke_width=WEATHER_TEMP_STROKE_WIDTH,
                stroke_fill="black",
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
        draw.text(
            (x, y),
            temp_text,
            fill=_temperature_color(event.weather_temperature_f),
            font=temperature_font,
            stroke_width=WEATHER_TEMP_STROKE_WIDTH,
            stroke_fill="black",
        )


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

def _draw_reminders_region(
    draw: ImageDraw.ImageDraw,
    reminders: List[Reminder],
    canvas_w: int,
    padding: int,
    y: int,
    max_y: int,
    header_font: ImageFont.FreeTypeFont,
    item_font: ImageFont.FreeTypeFont,
    small_font: ImageFont.FreeTypeFont,
    max_items: int = 6,
) -> int:
    """Draw a "Reminders" region (Google Tasks) and return the new y cursor.

    Rendered as its own block above the schedule so reminders stay visually
    separate from all-day calendar events. Overdue items get a red checkbox.
    Returns ``y`` unchanged when there are no reminders or no room.
    """
    if not reminders:
        return y

    header_h = header_font.size + 12
    # Only start the region if the header plus at least one reminder line fit.
    if y + header_h + item_font.size + 6 > max_y:
        return y

    draw.text((padding, y), "Reminders", fill="black", font=header_font)
    y += header_h

    box = "☐"
    box_w = draw.textlength(box + " ", font=item_font)
    text_x = padding + box_w
    max_text_w = canvas_w - padding - text_x
    item_line_h = item_font.size + 8

    shown = 0
    for reminder in reminders:
        if shown >= max_items:
            break
        lines = _wrap_text(draw, reminder.title, item_font, max_text_w, max_lines=2)
        block_h = item_line_h * len(lines) + 6
        # Always keep at least one event line of breathing room below.
        if y + block_h > max_y:
            break
        draw.text((padding, y), box, fill="red" if reminder.overdue else "black", font=item_font)
        for i, line in enumerate(lines):
            draw.text((text_x, y + i * item_line_h), line, fill="black", font=item_font)
        y += block_h
        shown += 1

    remaining = len(reminders) - shown
    if remaining > 0 and y + small_font.size + 6 <= max_y:
        draw.text((padding, y), f"Plus {remaining} more reminders", fill="black", font=small_font)
        y += small_font.size + 6

    if shown > 0:
        # Divider separating reminders from the schedule below.
        draw.line((padding, y, canvas_w - padding, y), fill="black", width=2)
        y += 18

    return y


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
    reminders: Optional[List[Reminder]] = None,
    update_pending: bool = False,
) -> Image.Image:
    img = Image.new("RGB", (canvas_w, canvas_h), "white")
    d = ImageDraw.Draw(img)

    font_header = _load_font(72)
    font_tomorrow_header = _load_font(38)
    font_time = _load_font(46)
    font_title = _load_font(52)
    font_small = _load_font(30)
    font_alert_header = _load_font(34)
    font_today_weather = _load_font(44)
    font_today_weather_bold = _load_bold_font(44)
    font_tomorrow_weather = _load_font(36)
    font_tomorrow_weather_bold = _load_bold_font(36)
    font_reminder_header = _load_bold_font(40)
    font_reminder = _load_font(38)

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
    max_weather_w = max(
        (
            _weather_text_width(d, e, font_today_weather, font_today_weather_bold)
            for e in events_sorted
            if not e.all_day and _weather_label(e)
        ),
        default=0,
    )
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

    # Over-the-air update status (its own line above the "Updated:" line).
    ota_text = _format_update_status(update_pending)
    ota_text_h = font_small.size + 6
    if ota_text:
        updated_block_h += ota_text_h + 8

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

    # Reminders (Google Tasks) render in their own region above the schedule,
    # kept separate from all-day calendar events.
    y = _draw_reminders_region(
        d,
        reminders or [],
        canvas_w,
        padding,
        y,
        max_y,
        font_reminder_header,
        font_reminder,
        font_small,
    )

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
        title_y = row_start_y
        if len(lines) == 1 and not detail_text:
            single_line_h = title_line_h
            title_y = row_start_y + max(0, int((row_h - single_line_h) / 2))

        content_y = title_y + title_line_h * len(lines) + 6

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
                weather_w = _weather_text_width(d, e, font_today_weather, font_today_weather_bold)
                x_weather = padding + max(0, (time_col_w - weather_w) / 2)
                _draw_weather_text(
                    d,
                    x_weather,
                    y + font_time.size + 4,
                    e,
                    font_today_weather,
                    font_today_weather_bold,
                )

            divider_x = padding + time_col_w + (column_gap // 2)
            d.line((divider_x, y, divider_x, row_start_y + row_h), fill="black", width=1)

        for i, line in enumerate(lines):
            d.text((x_title, title_y + i * title_line_h), line, fill="black", font=font_title)

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
                profile_time_w = max(
                    (d.textlength(s, font=profile_time_font) for s in profile_time_strings),
                    default=0,
                )
                profile_weather_w = max(
                    (
                        _weather_text_width(d, e, font_tomorrow_weather, font_tomorrow_weather_bold)
                        for e in tomorrow_sorted
                        if not e.all_day and _weather_label(e)
                    ),
                    default=0,
                )
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
                    profile_left_col_h = 0
                    if not e.all_day:
                        profile_left_col_h = profile_time_font.size
                        if _weather_label(e):
                            profile_left_col_h += 4 + font_tomorrow_weather.size
                    row_h = max(profile["min_row_h"], content_y - test_y + 6, profile_left_col_h + 6)
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
                fallback_weather_w = max(
                    (
                        _weather_text_width(d, e, font_tomorrow_weather, font_tomorrow_weather_bold)
                        for e in tomorrow_sorted
                        if not e.all_day and _weather_label(e)
                    ),
                    default=0,
                )
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
                (
                    _weather_text_width(d, e, font_tomorrow_weather, font_tomorrow_weather_bold)
                    for e in tomorrow_sorted
                    if not e.all_day and _weather_label(e)
                ),
                default=0,
            )
            gap = int(time_font.size * 0.45)
            weather_divider_padding = 12

            for e, lines in zip(tomorrow_sorted, chosen_lines):
                time_str = "" if e.all_day else f"{_fmt_time(e.start)}–{_fmt_time(e.end)}"
                row_start_y = y
                content_y = row_start_y + chosen_profile["title_line_h"] * len(lines) + 4
                detail_text = (e.travel_time_text or "").strip()
                if detail_text:
                    content_y += font_small.size + 6
                left_col_h = 0
                if time_str:
                    left_col_h = time_font.size
                    if _weather_label(e):
                        left_col_h = max(left_col_h, font_tomorrow_weather.size)
                row_h = max(chosen_profile["min_row_h"], content_y - row_start_y + 6, left_col_h + 6)
                total_h = row_h + chosen_profile["sep"]

                if y + total_h > max_y:
                    d.text((padding, y), "…", fill="black", font=font_tomorrow_header)
                    break

                if time_str:
                    time_w = d.textlength(time_str, font=time_font)
                    d.text((padding + max(0, time_col_w - time_w), y), time_str, fill="black", font=time_font)
                    weather_text = _weather_label(e)
                    if weather_text:
                        _draw_weather_text(
                            d,
                            padding + time_col_w + gap,
                            y,
                            e,
                            font_tomorrow_weather,
                            font_tomorrow_weather_bold,
                        )

                    first_divider_x = padding + time_col_w + (gap // 2)
                    second_divider_x = padding + time_col_w + gap + weather_col_w + weather_divider_padding
                    d.line((first_divider_x, y, first_divider_x, row_start_y + row_h), fill="black", width=1)
                    d.line((second_divider_x, y, second_divider_x, row_start_y + row_h), fill="black", width=1)

                x_title = padding if e.all_day else second_divider_x + (gap // 2)
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
    ota_top_ref = updated_y
    if ups_text:
        ups_text_w = d.textlength(ups_text, font=font_small)
        ups_right = wifi_left - 10
        if ups_on_second_line:
            ups_x = padding
            ups_y = updated_y - ups_text_h - 8
            ota_top_ref = ups_y
        else:
            ups_x = max(padding, ups_right - ups_text_w)
            ups_y = updated_y
        d.text((ups_x, ups_y), ups_text, fill="black", font=font_small)
    d.text((padding, updated_y), updated_text, fill="black", font=font_small)
    if ota_text:
        # Sits above the UPS/updated lines, in red so it stands out.
        ota_y = ota_top_ref - ota_text_h - 8
        d.text((padding, ota_y), ota_text, fill="red", font=font_small)
    usable_canvas_h = canvas_h - (banner_h if show_sleep_banner else 0)
    _draw_wifi_status(d, canvas_w, usable_canvas_h, padding, wifi_status, font_small)

    if show_sleep_banner:
        y0 = canvas_h - padding - banner_h
        d.rectangle((padding, y0, canvas_w - padding, y0 + banner_h), outline="black", width=2)
        d.text((padding + 20, y0 + 18), sleep_banner_text, fill="black", font=font_small)

    return img


def _weekday_header_label(day: date, today: date) -> str:
    label = day.strftime("%A, %B %-d")
    if day == today:
        label += " (Today)"
    return label


def render_weekly_schedule(
    canvas_w: int,
    canvas_h: int,
    now: datetime,
    week_events: List[Event],
    tz: ZoneInfo,
    show_sleep_banner: bool,
    sleep_banner_text: str,
    wifi_status: str = "connected",
    ups_status: Optional[dict] = None,
    weather_alerts: Optional[List[WeatherAlert]] = None,
    update_pending: bool = False,
    days: int = 7,
) -> Image.Image:
    """Weekly overview: the next `days` days, event names only (no times)."""
    img = Image.new("RGB", (canvas_w, canvas_h), "white")
    d = ImageDraw.Draw(img)

    font_header = _load_font(64)
    font_subheader = _load_font(34)
    font_day_header = _load_bold_font(40)
    font_event = _load_font(34)
    font_small = _load_font(28)
    font_alert_header = _load_font(34)

    padding = 40
    y = padding

    now_local = now.astimezone(tz)
    today = now_local.date()
    last_day = today + timedelta(days=days - 1)

    title = "This Week"
    title_w = d.textlength(title, font=font_header)
    d.text(((canvas_w - title_w) / 2, y), title, fill="black", font=font_header)
    y += font_header.size + 10

    subtitle = f"{today.strftime('%B %-d')} – {last_day.strftime('%B %-d, %Y')}"
    subtitle_w = d.textlength(subtitle, font=font_subheader)
    d.text(((canvas_w - subtitle_w) / 2, y), subtitle, fill="black", font=font_subheader)
    y += font_subheader.size + 20

    d.line((padding, y, canvas_w - padding, y), fill="black", width=2)
    y += 25

    events_by_day: Dict[date, List[Event]] = {}
    for e in sorted(week_events, key=_event_sort_key):
        if e.all_day:
            # A multi-day all-day event (e.g. a 3-day trip) is fetched once
            # for the whole week, unlike the daily view's per-day fetch that
            # naturally re-surfaces it on each overlapping day. Expand it
            # across every day of the display range it spans instead of
            # only its start day. `end` is exclusive (matches _today_range).
            span_start = max(e.start.astimezone(tz).date(), today)
            span_end = min(e.end.astimezone(tz).date(), last_day + timedelta(days=1))
            day_cursor = span_start
            while day_cursor < span_end:
                events_by_day.setdefault(day_cursor, []).append(e)
                day_cursor += timedelta(days=1)
        else:
            day_key = e.start.astimezone(tz).date()
            events_by_day.setdefault(day_key, []).append(e)

    # Footer (status bar) sizing, mirrors render_daily_schedule but simpler:
    # a fixed stack of lines rather than dynamic side-by-side wrapping.
    banner_h = 70
    ups_text = _format_ups_status(ups_status)
    ota_text = _format_update_status(update_pending)
    updated_text = f"Updated: {now_local.strftime('%-I:%M %p').lower()}"
    footer_line_h = font_small.size + 6
    footer_block_h = footer_line_h + 10
    if ups_text:
        footer_block_h += footer_line_h
    if ota_text:
        footer_block_h += footer_line_h

    weather_alert_lines = _prepare_weather_alert_lines(
        d, weather_alerts or [], font_small, canvas_w - (2 * padding)
    )
    weather_alert_line_h = font_small.size + 4
    weather_alert_header_h = font_alert_header.size + 6
    weather_alert_block_h = 0
    if weather_alert_lines:
        weather_alert_block_h = weather_alert_header_h + (len(weather_alert_lines) * weather_alert_line_h) + 24

    max_y = canvas_h - padding - (banner_h if show_sleep_banner else 0) - footer_block_h - weather_alert_block_h

    day_header_h = font_day_header.size + 10
    event_line_h = font_event.size + 8
    no_events_h = font_small.size + 8
    day_block_gap = 22
    bullet = "•  "
    bullet_w = d.textlength(bullet, font=font_event)
    max_event_w = canvas_w - (2 * padding) - bullet_w

    hidden_days = 0
    for offset in range(days):
        day = today + timedelta(days=offset)
        day_events = events_by_day.get(day, [])
        event_lines = [_wrap_text(d, e.title, font_event, max_event_w, max_lines=2) for e in day_events]

        first_row_h = (len(event_lines[0]) * event_line_h) if event_lines else no_events_h
        if y + day_header_h + first_row_h > max_y:
            hidden_days = days - offset
            break

        d.text((padding, y), _weekday_header_label(day, today), fill="black", font=font_day_header)
        y += day_header_h
        d.line((padding, y - 4, padding + 220, y - 4), fill="black", width=2)

        if not day_events:
            d.text((padding, y), "No events", fill="black", font=font_small)
            y += no_events_h
        else:
            for idx, (e, lines) in enumerate(zip(day_events, event_lines)):
                needed_h = len(lines) * event_line_h
                has_more_hidden = idx < len(day_events) - 1
                reserve = (font_small.size + 8) if has_more_hidden else 0
                if y + needed_h + reserve > max_y:
                    remaining = len(day_events) - idx
                    d.text((padding, y), f"+{remaining} more", fill="black", font=font_small)
                    y += font_small.size + 8
                    break
                d.text((padding, y), bullet, fill="black", font=font_event)
                for i, line in enumerate(lines):
                    d.text((padding + bullet_w, y + i * event_line_h), line, fill="black", font=font_event)
                y += needed_h

        y += day_block_gap

    if hidden_days > 0 and y + font_small.size + 6 <= max_y:
        suffix = "s" if hidden_days != 1 else ""
        d.text((padding, y), f"Plus {hidden_days} more day{suffix}", fill="black", font=font_small)
        y += font_small.size + 8

    bottom_y = canvas_h - padding - (banner_h if show_sleep_banner else 0)
    alert_bottom_y = bottom_y - footer_block_h
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

    footer_y = bottom_y - footer_block_h + 10
    if ota_text:
        d.text((padding, footer_y), ota_text, fill="red", font=font_small)
        footer_y += footer_line_h
    if ups_text:
        d.text((padding, footer_y), ups_text, fill="black", font=font_small)
        footer_y += footer_line_h
    d.text((padding, footer_y), updated_text, fill="black", font=font_small)

    usable_canvas_h = canvas_h - (banner_h if show_sleep_banner else 0)
    _draw_wifi_status(d, canvas_w, usable_canvas_h, padding, wifi_status, font_small)

    if show_sleep_banner:
        y0 = canvas_h - padding - banner_h
        d.rectangle((padding, y0, canvas_w - padding, y0 + banner_h), outline="black", width=2)
        d.text((padding + 20, y0 + 18), sleep_banner_text, fill="black", font=font_small)

    return img


def _format_update_status(update_pending: bool) -> Optional[str]:
    """Text for the OTA status line, or None when there's no update pending."""
    return "Update pending" if update_pending else None


def _format_ups_status(ups_status: Optional[dict]) -> Optional[str]:
    if not ups_status:
        return None

    percent_value = (
        ups_status.get("battery_percent")
        or ups_status.get("battery_percentage")
        or ups_status.get("battery")
        or ups_status.get("percent")
        or ups_status.get("capacity")
    )
    power_source = ups_status.get("power_source") or ups_status.get("source")
    if not power_source:
        status = str(ups_status.get("status") or "").strip().lower()
        if status == "discharging":
            power_source = "battery"
        elif status in {"charging", "full", "not charging"}:
            power_source = "external"
        elif status:
            power_source = status

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
