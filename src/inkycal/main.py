from __future__ import annotations

import hashlib
import json
import os
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Callable, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from PIL import Image

from .calendar_common import clip_events_to_range
from .calendar_google import CONTACTS_BIRTHDAY_CALENDAR_ID, fetch_google_events
from .calendar_icloud import fetch_icloud_events
from .config import CONFIG_PATH_DEFAULT, load_config
from .display_inky import show_on_inky
from .models import Event, Reminder
from .network import get_ups_status, get_wifi_status
from .reminders_google import fetch_google_tasks
from .render import render_daily_schedule, render_weekly_schedule
from .weather import WeatherAlert, WeatherForecastResolver
from .state import STATE_PATH_DEFAULT, VIEW_MODES, State, load_state, save_state, toggle_view_mode
from .travel import TravelTimeResolver
from . import frames, updates


def _parse_hhmm(s: str) -> time:
    hh, mm = s.split(":")
    return time(hour=int(hh), minute=int(mm))


def _is_in_sleep_window(now: datetime, start: time, end: time) -> bool:
    # Handles overnight windows (e.g., 22:30 -> 06:30)
    if start == end:
        # An empty window is no window at all. Without this the overnight
        # branch below reads "at or after start, or before end" as always
        # true, so a config written to mean "never sleep" (start and end both
        # 00:00, say) would instead skip every refresh, around the clock,
        # leaving the panel frozen on whatever it last painted.
        return False
    t = now.timetz().replace(tzinfo=None)
    if start < end:
        return start <= t < end
    return (t >= start) or (t < end)


def _today_range(now: datetime, tz: ZoneInfo):
    local = now.astimezone(tz)
    day_start = local.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = day_start + timedelta(days=1)
    return day_start, day_end


def _week_range(now: datetime, tz: ZoneInfo, days: int = 7):
    local = now.astimezone(tz)
    day_start = local.replace(hour=0, minute=0, second=0, microsecond=0)
    return day_start, day_start + timedelta(days=days)


def _normalize_text(value: str | None) -> str:
    if not value:
        return ""
    return " ".join(value.strip().lower().split())


def _fingerprint_text(value: str | None) -> str:
    normalized = unicodedata.normalize("NFKC", _normalize_text(value)).casefold()
    return re.sub(r"[^\w]", "", normalized, flags=re.UNICODE)


def _event_quality_score(event: Event) -> tuple[int, int]:
    return (1 if _fingerprint_text(event.location) else 0, len(event.title.strip()))


def _event_sort_key(e: Event):
    return (0 if e.all_day else 1, e.start, e.title.lower())


def _dedupe_events(events: List[Event]) -> List[Event]:
    deduped: List[Event] = []
    seen_by_base_key: dict[tuple[str, str, str, bool], list[int]] = {}

    for e in sorted(events, key=_event_sort_key):
        base_key = (
            _fingerprint_text(e.title),
            e.start.isoformat(),
            e.end.isoformat(),
            bool(e.all_day),
        )

        location_fingerprint = _fingerprint_text(e.location)
        duplicate_index: int | None = None
        for idx in seen_by_base_key.get(base_key, []):
            existing_location_fingerprint = _fingerprint_text(deduped[idx].location)
            if (
                location_fingerprint == existing_location_fingerprint
                or not location_fingerprint
                or not existing_location_fingerprint
            ):
                duplicate_index = idx
                break

        if duplicate_index is not None:
            if _event_quality_score(e) > _event_quality_score(deduped[duplicate_index]):
                deduped[duplicate_index] = e
            continue

        seen_by_base_key.setdefault(base_key, []).append(len(deduped))
        deduped.append(e)

    return deduped


_BIRTHDAY_TITLE_RE = re.compile(r"^(.*?)['\u2019]s\s+birthday$", re.IGNORECASE)


def _birthday_label(title: str) -> str:
    # "Jane Doe's birthday" reads better as just "Jane Doe" once the row itself
    # is labeled "Birthdays"; anything shaped differently is left alone.
    stripped = title.strip()
    match = _BIRTHDAY_TITLE_RE.match(stripped)
    if match and match.group(1).strip():
        return match.group(1).strip()
    return stripped


def _merge_group(events: List[Event], prefix: str, empty_title: str) -> Event:
    labels = [t for t in (e.title.strip() for e in events) if t]
    labels.sort(key=str.lower)
    title = (f"{prefix}: " + " • ".join(labels)) if labels else empty_title
    return Event(
        source="merged",
        title=title,
        start=min(e.start for e in events),
        end=max(e.end for e in events),
        all_day=True,
        birthday=all(e.birthday for e in events),
    )


def _merge_all_day_events(events: List[Event]) -> List[Event]:
    all_day_events = [e for e in events if e.all_day]
    timed_events = [e for e in events if not e.all_day]
    if not all_day_events:
        return sorted(timed_events, key=_event_sort_key)

    birthdays = [e for e in all_day_events if e.birthday]
    others = [e for e in all_day_events if not e.birthday]

    merged: List[Event] = []
    if others:
        merged.append(_merge_group(others, "All-day", "All-day events"))
    if birthdays:
        named = [
            Event(
                source=e.source,
                title=_birthday_label(e.title),
                start=e.start,
                end=e.end,
                all_day=True,
                birthday=True,
            )
            for e in birthdays
        ]
        merged.append(_merge_group(named, "Birthdays", "Birthdays"))

    return [*merged, *sorted(timed_events, key=_event_sort_key)]


def _apply_travel_times(
    events: List[Event],
    origin_address: str,
    back_to_back_window_minutes: int,
    resolver: Optional[TravelTimeResolver] = None,
) -> List[Event]:
    if not origin_address:
        return events

    if resolver is None:
        resolver = TravelTimeResolver()
    processed: List[Event] = []
    previous_timed_event: Event | None = None
    for event in events:
        if event.all_day:
            processed.append(event)
            continue

        origin = origin_address
        if previous_timed_event is not None:
            gap = event.start - previous_timed_event.end
            if gap <= timedelta(minutes=back_to_back_window_minutes) and previous_timed_event.location:
                origin = previous_timed_event.location

        travel_text = None
        if event.location:
            estimate = resolver.estimate(origin, event.location)
            if estimate:
                travel_text = f"Travel: {estimate.text}"

        processed.append(
            Event(
                source=event.source,
                title=event.title,
                start=event.start,
                end=event.end,
                all_day=event.all_day,
                location=event.location,
                travel_time_text=travel_text,
            )
        )
        previous_timed_event = event

    return processed




def _apply_weather_forecast(
    events: List[Event],
    timezone: str,
    latitude: float,
    longitude: float,
    include_end_weather_for_long_events: bool = True,
    resolver: Optional[WeatherForecastResolver] = None,
) -> List[Event]:
    # Pass the run's resolver in so every lookup shares its one forecast download.
    if resolver is None:
        resolver = WeatherForecastResolver(timezone=timezone, latitude=latitude, longitude=longitude)
    processed: List[Event] = []
    for event in events:
        if event.all_day:
            processed.append(event)
            continue

        weather_text = None
        weather_icon = None
        weather_temperature_f = None
        weather_end_text = None
        weather_end_icon = None
        weather_end_temperature_f = None
        try:
            weather = resolver.forecast_for_event_start(event.start)
        except Exception as e:
            print(f"Weather lookup failed for '{event.title}'; continuing without weather. Error: {e}")
            weather = None

        if weather:
            weather_text = f"{weather.temperature_f}°F"
            weather_icon = weather.icon
            weather_temperature_f = weather.temperature_f

        if include_end_weather_for_long_events and (event.end - event.start) > timedelta(minutes=60):
            try:
                end_weather = resolver.forecast_for_datetime(event.end)
            except Exception as e:
                print(f"Weather lookup failed for end of '{event.title}'; continuing without end weather. Error: {e}")
                end_weather = None
            if end_weather:
                weather_end_text = f"{end_weather.temperature_f}°F"
                weather_end_icon = end_weather.icon
                weather_end_temperature_f = end_weather.temperature_f

        processed.append(
            Event(
                source=event.source,
                title=event.title,
                start=event.start,
                end=event.end,
                all_day=event.all_day,
                location=event.location,
                travel_time_text=event.travel_time_text,
                weather_icon=weather_icon,
                weather_text=weather_text,
                weather_temperature_f=weather_temperature_f,
                weather_end_icon=weather_end_icon,
                weather_end_text=weather_end_text,
                weather_end_temperature_f=weather_end_temperature_f,
            )
        )
    return processed

def _process_events(events: List[Event]) -> List[Event]:
    # Travel times and weather are added later, and only to a frame that is
    # actually being drawn (see _render_view).
    return _merge_all_day_events(_dedupe_events(events))


def _google_calendar_ids(cfg) -> List[str]:
    ids = list(cfg.google.calendar_ids)
    if getattr(cfg.google, "birthdays_enabled", True) and CONTACTS_BIRTHDAY_CALENDAR_ID not in ids:
        ids.append(CONTACTS_BIRTHDAY_CALENDAR_ID)
    return ids


def _fetch_raw_events(cfg, range_start: datetime, range_end: datetime, tz: ZoneInfo) -> List[Event]:
    events: List[Event] = []
    if cfg.google.enabled:
        token_path = os.environ.get("GOOGLE_TOKEN_JSON", "")
        if token_path:
            try:
                events.extend(fetch_google_events(_google_calendar_ids(cfg), range_start, range_end, tz, token_path))
            except Exception as e:
                print(f"Google Calendar fetch failed; continuing without Google events. Error: {e}")
        else:
            print("Google enabled but GOOGLE_TOKEN_JSON not set; skipping Google. Generate it off-device with scripts/google_auth.py.")

    if cfg.icloud.enabled:
        try:
            user = os.environ.get("ICLOUD_USERNAME", "")
            pw = os.environ.get("ICLOUD_APP_PASSWORD", "")
            if user and pw:
                events.extend(fetch_icloud_events(range_start, range_end, tz, user, pw, cfg.icloud.calendar_name_allowlist))
            else:
                print("iCloud enabled but ICLOUD_USERNAME/ICLOUD_APP_PASSWORD not set; skipping iCloud.")
        except Exception as e:
            print(f"iCloud fetch failed; continuing without iCloud. Error: {e}")

    # Both backends hand back all-day events that merely touch the requested
    # window (see calendar_common.event_overlaps_range), which is what made a
    # one-day all-day event show up on two days. Clip to the window we asked for.
    return clip_events_to_range(events, range_start, range_end, tz)


def _fetch_events_for_range(cfg, range_start: datetime, range_end: datetime, tz: ZoneInfo) -> List[Event]:
    return _process_events(_fetch_raw_events(cfg, range_start, range_end, tz))


@dataclass(frozen=True)
class _ViewEvents:
    """The events each view lists, all cut from one fetch."""

    today: List[Event]
    tomorrow: List[Event]
    week: List[Event]


def _split_for_views(raw_events: List[Event], now: datetime, tz: ZoneInfo) -> _ViewEvents:
    day_start, day_end = _today_range(now, tz)
    one_day = timedelta(days=1)
    return _ViewEvents(
        today=_process_events(clip_events_to_range(raw_events, day_start, day_end, tz)),
        tomorrow=_process_events(
            clip_events_to_range(raw_events, day_start + one_day, day_end + one_day, tz)
        ),
        # The weekly view only lists event names grouped by day, so it skips
        # the all-day merge the daily view applies (merging would collapse
        # all-day events from different days into a single row).
        week=_dedupe_events(raw_events),
    )


def _fetch_view_events(cfg, now: datetime, tz: ZoneInfo) -> _ViewEvents:
    # Today and tomorrow are the first two of the weekly view's seven days, so
    # one fetch of the week feeds both views. A backend takes the same round
    # trips to answer for seven days as for one, and this replaces the separate
    # today and tomorrow fetches the daily view used to make on its own.
    week_start, week_end = _week_range(now, tz)
    return _split_for_views(_fetch_raw_events(cfg, week_start, week_end, tz), now, tz)


def _reminder_sort_key(r: Reminder):
    # Overdue first, then by due date, then title.
    return (0 if r.overdue else 1, r.due or datetime.max.replace(tzinfo=None), r.title.lower())


def _fetch_reminders_for_day(cfg, day_end: datetime, tz: ZoneInfo) -> List[Reminder]:
    reminders: List[Reminder] = []
    if cfg.google.enabled and cfg.google.tasks_enabled:
        token_path = os.environ.get("GOOGLE_TOKEN_JSON", "")
        if token_path:
            try:
                reminders.extend(
                    fetch_google_tasks(token_path, tz, day_end, cfg.google.task_list_allowlist)
                )
            except Exception as e:
                print(f"Google Tasks fetch failed; continuing without reminders. Error: {e}")
        else:
            print("Google Tasks enabled but GOOGLE_TOKEN_JSON not set; skipping reminders.")

    return sorted(reminders, key=_reminder_sort_key)


def print_long_events_weather_report(config_path: str = CONFIG_PATH_DEFAULT) -> None:
    load_dotenv()
    cfg = load_config(config_path)
    tz = ZoneInfo(cfg.timezone)
    now = datetime.now(tz=tz)
    day_start, day_end = _today_range(now, tz)
    events = _fetch_events_for_range(cfg, day_start, day_end, tz)
    resolver = WeatherForecastResolver(timezone=cfg.timezone, latitude=cfg.weather.latitude, longitude=cfg.weather.longitude)

    filtered = [
        e for e in events if (not e.all_day) and ((e.end - e.start) > timedelta(minutes=60))
    ]

    if not filtered:
        print("No timed events longer than 60 minutes found for today.")
        return

    for event in filtered:
        start_weather = resolver.forecast_for_datetime(event.start)
        end_weather = resolver.forecast_for_datetime(event.end)
        start_text = "unavailable" if not start_weather else f"{start_weather.temperature_f}°F {start_weather.icon}"
        end_text = "unavailable" if not end_weather else f"{end_weather.temperature_f}°F {end_weather.icon}"
        print(f"- {event.start.strftime('%H:%M')}-{event.end.strftime('%H:%M')} {event.title}")
        print(f"  start weather: {start_text}")
        print(f"  end weather:   {end_text}")


def _should_force_hourly_refresh(state: State, now: datetime, threshold: timedelta) -> bool:
    if not state.last_rendered_iso:
        return False
    try:
        last_rendered = datetime.fromisoformat(state.last_rendered_iso)
    except ValueError:
        return False
    if last_rendered.tzinfo is None:
        last_rendered = last_rendered.replace(tzinfo=now.tzinfo)
    return (now - last_rendered) >= threshold


def _events_signature(
    tz: ZoneInfo,
    events: List[Event],
    tomorrow_events: List[Event],
    weather_alerts: List[WeatherAlert],
    header_date: str,
    sleep_banner: bool,
    wifi_status: str,
    ups_status: dict,
    reminders: Optional[List[Reminder]] = None,
    update_pending: bool = False,
    view_mode: str = "daily",
    week_events: Optional[List[Event]] = None,
) -> str:
    # Only include fields that affect rendering. Weather and travel times are
    # left out: they're looked up only when a frame is drawn, weather changes
    # by the hour regardless (the hourly repaint picks it up), and a travel
    # time follows from the locations, which are already in here.
    def _event_payload(e: Event) -> dict:
        return {
            "source": e.source,
            "title": e.title,
            "start": e.start.astimezone(tz).isoformat(),
            "end": e.end.astimezone(tz).isoformat(),
            "all_day": e.all_day,
            "location": e.location or "",
        }

    def _reminder_payload(r: Reminder) -> dict:
        return {
            "source": r.source,
            "title": r.title,
            "due": r.due.astimezone(tz).isoformat() if r.due else "",
            "overdue": r.overdue,
        }

    ups_payload = {
        "present": ups_status.get("present", False),
        "status": ups_status.get("status", ""),
        "capacity": ups_status.get("capacity"),
        "online": ups_status.get("online"),
    }
    payload = {
        "header_date": header_date,
        "sleep_banner": sleep_banner,
        "wifi_status": wifi_status,
        "ups_status": ups_payload,
        "events": [_event_payload(e) for e in events],
        "tomorrow_events": [_event_payload(e) for e in tomorrow_events],
        "weather_alerts": [a.headline for a in weather_alerts],
        "reminders": [_reminder_payload(r) for r in (reminders or [])],
        "update_pending": update_pending,
        "view_mode": view_mode,
        "week_events": [_event_payload(e) for e in (week_events or [])],
    }
    b = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(b).hexdigest()


@dataclass(frozen=True)
class _Snapshot:
    """Everything one run knows that either view is drawn from."""

    now: datetime
    events: _ViewEvents
    reminders: List[Reminder]
    weather_alerts: List[WeatherAlert]
    header_date: str
    show_banner: bool
    wifi_status: str
    ups_status: dict
    update_pending: bool


def _view_signature(view_mode: str, snap: _Snapshot, tz: ZoneInfo) -> str:
    """The content hash of `view_mode` as `snap` would draw it (see _events_signature)."""
    if view_mode == "weekly":
        return _events_signature(
            tz, [], [], snap.weather_alerts, snap.header_date, snap.show_banner,
            snap.wifi_status, snap.ups_status,
            update_pending=snap.update_pending,
            view_mode="weekly",
            week_events=snap.events.week,
        )
    return _events_signature(
        tz, snap.events.today, snap.events.tomorrow, snap.weather_alerts, snap.header_date,
        snap.show_banner, snap.wifi_status, snap.ups_status, snap.reminders,
        update_pending=snap.update_pending,
        view_mode="daily",
    )


def _render_view(
    view_mode: str,
    snap: _Snapshot,
    cfg,
    tz: ZoneInfo,
    weather_resolver: WeatherForecastResolver,
) -> Image.Image:
    if view_mode == "weekly":
        return render_weekly_schedule(
            canvas_w=cfg.display.width,
            canvas_h=cfg.display.height,
            now=snap.now,
            week_events=snap.events.week,
            tz=tz,
            show_sleep_banner=snap.show_banner,
            sleep_banner_text=cfg.sleep.banner_text,
            wifi_status=snap.wifi_status,
            ups_status=snap.ups_status,
            weather_alerts=snap.weather_alerts,
            update_pending=snap.update_pending,
        )

    # Travel times and weather are looked up here, for a frame that's actually
    # being drawn, rather than on every run: neither is part of the content
    # hash, so a run that finds nothing changed never needs them.
    today = snap.events.today
    tomorrow = snap.events.tomorrow
    if cfg.travel.enabled:
        # One resolver for both days, so a place visited on each is looked up once.
        travel_resolver = TravelTimeResolver()
        origin = cfg.travel.origin_address
        window = cfg.travel.back_to_back_window_minutes
        today = _apply_travel_times(today, origin, window, resolver=travel_resolver)
        tomorrow = _apply_travel_times(tomorrow, origin, window, resolver=travel_resolver)
    today = _apply_weather_forecast(
        today,
        cfg.timezone,
        cfg.weather.latitude,
        cfg.weather.longitude,
        resolver=weather_resolver,
    )
    tomorrow = _apply_weather_forecast(
        tomorrow,
        cfg.timezone,
        cfg.weather.latitude,
        cfg.weather.longitude,
        include_end_weather_for_long_events=False,
        resolver=weather_resolver,
    )

    return render_daily_schedule(
        canvas_w=cfg.display.width,
        canvas_h=cfg.display.height,
        now=snap.now,
        events=today,
        tz=tz,
        show_sleep_banner=snap.show_banner,
        sleep_banner_text=cfg.sleep.banner_text,
        wifi_status=snap.wifi_status,
        ups_status=snap.ups_status,
        tomorrow_events=tomorrow,
        weather_alerts=snap.weather_alerts,
        reminders=snap.reminders,
        update_pending=snap.update_pending,
    )


def _keep_frames_current(
    state_path: str,
    view_mode: str,
    signatures: Dict[str, str],
    now: datetime,
    canvas_size: Tuple[int, int],
    render: Callable[[str], Image.Image],
    painted: bool,
) -> None:
    """Leave each view a saved frame of what it would show now (see inkycal.frames).

    The view that isn't on the panel is the point. It's redrawn whenever its
    content has changed since it was saved, and once it's getting old, so the
    view button can put it straight up instead of fetching and drawing it
    first (inkycal.viewswap). That costs no fetch -- this run already has
    everything it shows -- and it comes after the panel has been dealt with,
    so it never holds the display up.

    The view on the panel is saved as it's painted, so it only needs drawing
    here when its saved frame is missing or doesn't match: a fresh install,
    the first run after the update that introduced these files, or a save
    that failed.

    Nothing in here may fail the run: the panel is already right, and a view
    without a saved frame just takes the slow way when the button is pressed.
    """
    for mode in VIEW_MODES:
        on_panel = mode == view_mode
        if on_panel and painted:
            continue
        info = frames.read_frame_info(state_path, mode)
        if (
            info is not None
            and info.content_hash == signatures[mode]
            and info.size == canvas_size
            and (on_panel or frames.is_fresh(info, now, frames.REDRAW_AFTER))
        ):
            continue
        try:
            img = render(mode)
        except Exception as e:
            print(f"Could not draw the {mode} view ahead of time; the view button will fetch it instead. Error: {e}")
            continue
        if frames.save_frame(state_path, mode, img, signatures[mode], now):
            if on_panel:
                print(f"Saved a copy of the {mode} view on the panel")
            else:
                print(f"Drew the {mode} view ahead of time for the view button")


def run_once(
    config_path: str = CONFIG_PATH_DEFAULT,
    state_path: str = STATE_PATH_DEFAULT,
    force: bool = False,
    deep_clean: bool = False,
    toggle_view: bool = False,
) -> None:
    load_dotenv()
    cfg = load_config(config_path)
    tz = ZoneInfo(cfg.timezone)

    state = load_state(state_path)
    now = datetime.now(tz=tz)

    if toggle_view:
        state.view_mode = toggle_view_mode(state.view_mode)
        save_state(state_path, state)
        force = True
        print(f"View toggled to '{state.view_mode}'")

    # load_state() and toggle_view_mode() both already guarantee one of VIEW_MODES.
    view_mode = state.view_mode

    sleep_start = _parse_hhmm(cfg.sleep.start)
    sleep_end = _parse_hhmm(cfg.sleep.end)

    in_sleep = cfg.sleep.enabled and _is_in_sleep_window(now, sleep_start, sleep_end)

    # Sleep-start banner logic:
    # If we just entered sleep window today and haven't applied banner yet, we will render once with banner.
    today_str = now.strftime("%Y-%m-%d")
    should_apply_sleep_banner = False
    if cfg.sleep.enabled and in_sleep:
        # Apply banner once per day when in sleep window
        if state.last_sleep_banner_date != today_str:
            should_apply_sleep_banner = True

    # During sleep: do nothing unless we need to apply the banner refresh
    if in_sleep and not should_apply_sleep_banner and not force and not deep_clean:
        print("In sleep window; skipping poll/refresh")
        return

    # Over-the-air update check. We only *look* here (fetch + compare) so the
    # status bar can show that an update is pending; scripts/ota_update.sh is
    # what actually pulls and applies.
    update_pending = False
    if cfg.auto_update.enabled:
        update_status = updates.check_for_update(branch=cfg.auto_update.branch)
        update_pending = update_status.available
        if update_status.error:
            print(f"Update check: {update_status.error}")
        else:
            print(
                f"Update check: behind={update_status.behind} "
                f"local={update_status.local} remote={update_status.remote}"
            )

    # One resolver for the whole run: the alerts, and a single forecast download
    # shared by every event that gets weather drawn next to it.
    weather_resolver = WeatherForecastResolver(
        timezone=cfg.timezone,
        latitude=cfg.weather.latitude,
        longitude=cfg.weather.longitude,
    )
    try:
        weather_alerts = weather_resolver.active_alerts()
    except Exception as e:
        print(f"NWS alert lookup failed; continuing without alerts. Error: {e}")
        weather_alerts = []

    # Everything both views show, fetched once. The view on the panel is
    # checked against what's there; the other is kept drawn for the view
    # button (see _keep_frames_current).
    _, day_end = _today_range(now, tz)
    snap = _Snapshot(
        now=now,
        events=_fetch_view_events(cfg, now, tz),
        reminders=_fetch_reminders_for_day(cfg, day_end, tz),
        weather_alerts=weather_alerts,
        header_date=now.strftime("%A, %B %-d, %Y"),
        show_banner=in_sleep and cfg.sleep.enabled,
        wifi_status=get_wifi_status(),
        ups_status=get_ups_status(),
        update_pending=update_pending,
    )
    signatures = {mode: _view_signature(mode, snap, tz) for mode in VIEW_MODES}
    sig = signatures[view_mode]

    def render(mode: str) -> Image.Image:
        return _render_view(mode, snap, cfg, tz, weather_resolver)

    should_force_hourly = _should_force_hourly_refresh(state, now, timedelta(hours=1))
    print(
        f"view_mode={view_mode}; fetched {len(snap.events.week)} events for the week "
        f"({len(snap.events.today)} today); in_sleep={in_sleep}, show_banner={snap.show_banner}, "
        f"force={force}, deep_clean={deep_clean}, hourly_refresh={should_force_hourly}"
    )
    painted = False
    if (
        (not force)
        and (not deep_clean)
        and (not should_apply_sleep_banner)
        and (not should_force_hourly)
        and (sig == state.last_hash)
    ):
        print("No schedule change; skipping display refresh")
    else:
        img = render(view_mode)
        show_on_inky(img, rotate_degrees=cfg.display.rotate_degrees, border=cfg.display.border)
        # Keep a copy of what's on the panel so a button press can redraw it with a
        # "working on it" bar instead of blanking the screen (see inkycal.feedback).
        frames.save_frame(state_path, view_mode, img, sig, now)

        state.last_hash = sig
        state.last_rendered_iso = now.isoformat()
        if should_apply_sleep_banner:
            state.last_sleep_banner_date = today_str
        save_state(state_path, state)
        painted = True

    _keep_frames_current(
        state_path,
        view_mode,
        signatures,
        now,
        (cfg.display.width, cfg.display.height),
        render,
        painted=painted,
    )


def main():
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=CONFIG_PATH_DEFAULT)
    ap.add_argument("--state", default=STATE_PATH_DEFAULT)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--deep-clean", action="store_true")
    ap.add_argument("--long-events-weather-report", action="store_true")
    ap.add_argument(
        "--toggle-view",
        action="store_true",
        help="Toggle between the daily and weekly view before rendering",
    )
    args = ap.parse_args()

    if args.long_events_weather_report:
        print_long_events_weather_report(config_path=args.config)
        return

    run_once(
        config_path=args.config,
        state_path=args.state,
        force=args.force,
        deep_clean=args.deep_clean,
        toggle_view=args.toggle_view,
    )


if __name__ == "__main__":
    main()
