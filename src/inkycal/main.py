from __future__ import annotations

import hashlib
import json
import os
import re
import unicodedata
from dataclasses import dataclass, field, replace
from datetime import date, datetime, time, timedelta
from typing import Callable, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from PIL import Image

from .calendar_common import clip_events_to_range
from .calendar_google import CONTACTS_BIRTHDAY_CALENDAR_ID, fetch_google_events
from .calendar_icloud import fetch_icloud_events
from .config import CONFIG_PATH_DEFAULT, load_config
from .display_inky import show_on_inky
from .fetchnotice import GOOGLE, ICLOUD, WEATHER, WEATHER_ALERTS, FetchProblem, describe_error, http_status
from .models import Event, Reminder
from .network import get_ups_status, get_wifi_status
from .reminders_google import fetch_google_tasks
from .render import render_daily_schedule, render_weekly_schedule
from .setupmode import SetupModeActive
from .geocode import CACHE_FILE_NAME as GEOCODE_CACHE_FILE_NAME, Geocoder, distance_miles
from .weather import WeatherAlert, WeatherForecastResolver, forecasts_for_places
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


def _sleep_window_start_date(now: datetime, start: time, end: time) -> date:
    """The date the sleep window `now` falls in started on.

    This is what keys the once-a-night sleep banner. An overnight window
    (22:30 -> 06:30) spans two calendar dates, and its small hours belong to
    the window that started the evening before. Keyed on the calendar date
    instead, the banner was painted a second time at midnight, and the next
    evening's window then looked as if it already had one, so that night's
    banner waited until midnight too.
    """
    t = now.timetz().replace(tzinfo=None)
    if start > end and t < end:
        return now.date() - timedelta(days=1)
    return now.date()


def _today_range(now: datetime, tz: ZoneInfo):
    local = now.astimezone(tz)
    day_start = local.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = day_start + timedelta(days=1)
    return day_start, day_end


def _week_range(now: datetime, tz: ZoneInfo, days: int = 7):
    local = now.astimezone(tz)
    day_start = local.replace(hour=0, minute=0, second=0, microsecond=0)
    return day_start, day_start + timedelta(days=days)


# How far ahead the daily view's "Upcoming birthdays" line looks, counting
# today: two weeks gives time to get a card in the post. It's also how far
# ahead every run fetches, since the weekly view's seven days fall inside it.
BIRTHDAY_LOOKAHEAD_DAYS = 14


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




# Marks a temperature that's the forecast where the event is, not at home.
ELSEWHERE_MARK = "*"


def _event_place_forecasts(
    events: List[Event],
    cfg,
    geocoder: Optional[Geocoder],
) -> Dict[str, WeatherForecastResolver]:
    """A forecast for each event address far enough from home for its weather to differ.

    Keyed by the event's location text, as _apply_weather_forecast looks it
    up. Within weather.event_location_min_miles of home the forecast is home's
    anyway (Open-Meteo's grid is a few miles across), so those addresses are
    left out, along with any the geocoder can't place. Every place left is
    forecast in one download; if that fails, the result is empty and every
    event gets home's weather, as it would with this turned off.
    """
    weather_cfg = cfg.weather
    if geocoder is None or not getattr(weather_cfg, "event_locations", True):
        return {}
    home = (weather_cfg.latitude, weather_cfg.longitude)
    min_miles = getattr(weather_cfg, "event_location_min_miles", 10.0)

    places: Dict[str, Tuple[float, float]] = {}
    seen = set()
    for event in events:
        location = (event.location or "").strip()
        if event.all_day or not location or location in seen:
            continue
        seen.add(location)
        coords = geocoder.locate(location)
        if coords is not None and distance_miles(home, coords) > min_miles:
            # Rounded to two decimals, within half a mile of the address:
            # finer than the forecast grid, and addresses a street apart
            # then share one forecast.
            places[location] = (round(coords[0], 2), round(coords[1], 2))
    geocoder.save()
    if not places:
        return {}

    distinct = sorted(set(places.values()))
    try:
        resolvers = dict(zip(distinct, forecasts_for_places(cfg.timezone, distinct)))
    except Exception as e:
        print(f"Forecast for events away from home failed; giving them home weather. Error: {e}")
        return {}
    print(f"Weather for {len(places)} event address(es) away from home, from {len(distinct)} forecast place(s)")
    return {location: resolvers[coords] for location, coords in places.items()}


def _event_weather(
    lookup: Callable[[WeatherForecastResolver], object],
    place_resolver: Optional[WeatherForecastResolver],
    home_resolver: WeatherForecastResolver,
    what: str,
):
    """(weather, elsewhere): the forecast where the event is when there is one, else home's.

    elsewhere is True only when the weather really is the event's place's,
    so the asterisk never marks home weather that stood in for it.
    """
    if place_resolver is not None:
        try:
            weather = lookup(place_resolver)
        except Exception as e:
            print(f"Weather lookup at {what}'s address failed; using home weather. Error: {e}")
            weather = None
        if weather:
            return weather, True
    try:
        return lookup(home_resolver), False
    except Exception as e:
        print(f"Weather lookup failed for {what}; continuing without weather. Error: {e}")
        return None, False


def _apply_weather_forecast(
    events: List[Event],
    timezone: str,
    latitude: float,
    longitude: float,
    include_end_weather_for_long_events: bool = True,
    resolver: Optional[WeatherForecastResolver] = None,
    place_resolvers: Optional[Dict[str, WeatherForecastResolver]] = None,
) -> List[Event]:
    # Pass the run's resolver in so every lookup shares its one forecast download.
    # place_resolvers (see _event_place_forecasts) gives events away from home
    # the forecast where they are instead.
    if resolver is None:
        resolver = WeatherForecastResolver(timezone=timezone, latitude=latitude, longitude=longitude)
    place_resolvers = place_resolvers or {}
    processed: List[Event] = []
    for event in events:
        if event.all_day:
            processed.append(event)
            continue

        place_resolver = place_resolvers.get((event.location or "").strip())
        weather_text = None
        weather_icon = None
        weather_temperature_f = None
        weather_end_text = None
        weather_end_icon = None
        weather_end_temperature_f = None
        weather, elsewhere = _event_weather(
            lambda r: r.forecast_for_event_start(event.start), place_resolver, resolver, f"'{event.title}'"
        )
        if weather:
            weather_text = f"{weather.temperature_f}°F" + (ELSEWHERE_MARK if elsewhere else "")
            weather_icon = weather.icon
            weather_temperature_f = weather.temperature_f

        if include_end_weather_for_long_events and (event.end - event.start) > timedelta(minutes=60):
            end_weather, end_elsewhere = _event_weather(
                lambda r: r.forecast_for_datetime(event.end), place_resolver, resolver, f"end of '{event.title}'"
            )
            if end_weather:
                weather_end_text = f"{end_weather.temperature_f}°F" + (ELSEWHERE_MARK if end_elsewhere else "")
                weather_end_icon = end_weather.icon
                weather_end_temperature_f = end_weather.temperature_f

        processed.append(
            replace(
                event,
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


def _google_calendar_problem(
    calendar_ids: List[str], failures: List[Tuple[str, Exception]]
) -> Optional[FetchProblem]:
    """What to tell the screen about the Google calendars that couldn't be read.

    fetch_google_events skips an unreadable calendar and carries on, so a
    network that drops mid-run, or one stale calendar id, used to leave no
    trace but the log. The contacts birthday calendar is the exception: it's
    added for everyone, and an account without one answers 404 on every run,
    which isn't news.
    """
    failures = [
        (cal_id, e)
        for cal_id, e in failures
        if not (cal_id == CONTACTS_BIRTHDAY_CALENDAR_ID and http_status(e) == 404)
    ]
    if not failures:
        return None
    if len(failures) == len(calendar_ids):
        source = GOOGLE
    else:
        source = f"{GOOGLE} ({len(failures)} calendar{'s' if len(failures) > 1 else ''})"
    return FetchProblem(source, describe_error(failures[0][1]))


def _fetch_raw_events(
    cfg,
    range_start: datetime,
    range_end: datetime,
    tz: ZoneInfo,
    problems: Optional[List[FetchProblem]] = None,
) -> List[Event]:
    """Every calendar's events in the range. A source that can't be fetched is
    left out, and added to `problems` (when given) for the screen to report."""
    if problems is None:
        problems = []
    events: List[Event] = []
    if cfg.google.enabled:
        token_path = os.environ.get("GOOGLE_TOKEN_JSON", "")
        if token_path:
            calendar_ids = _google_calendar_ids(cfg)
            failures: List[Tuple[str, Exception]] = []
            try:
                events.extend(
                    fetch_google_events(calendar_ids, range_start, range_end, tz, token_path, failures=failures)
                )
            except Exception as e:
                print(f"Google Calendar fetch failed; continuing without Google events. Error: {e}")
                problems.append(FetchProblem(GOOGLE, describe_error(e)))
            else:
                problem = _google_calendar_problem(calendar_ids, failures)
                if problem:
                    problems.append(problem)
        else:
            print("Google enabled but GOOGLE_TOKEN_JSON not set; skipping Google. Generate it off-device with scripts/google_auth.py.")
            problems.append(FetchProblem(GOOGLE, "not set up"))

    if cfg.icloud.enabled:
        try:
            user = os.environ.get("ICLOUD_USERNAME", "")
            pw = os.environ.get("ICLOUD_APP_PASSWORD", "")
            if user and pw:
                events.extend(fetch_icloud_events(range_start, range_end, tz, user, pw, cfg.icloud.calendar_name_allowlist))
            else:
                print("iCloud enabled but ICLOUD_USERNAME/ICLOUD_APP_PASSWORD not set; skipping iCloud.")
                problems.append(FetchProblem(ICLOUD, "not set up"))
        except Exception as e:
            print(f"iCloud fetch failed; continuing without iCloud. Error: {e}")
            problems.append(FetchProblem(ICLOUD, describe_error(e)))

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
    # Birthdays from the day after tomorrow to BIRTHDAY_LOOKAHEAD_DAYS out,
    # for the daily view's "Upcoming birthdays" line.
    upcoming_birthdays: List[Event] = field(default_factory=list)


def _upcoming_birthdays(events: List[Event], now: datetime, tz: ZoneInfo) -> List[Event]:
    """The birthdays in `events` from the day after tomorrow to
    BIRTHDAY_LOOKAHEAD_DAYS out, soonest first.

    Today's and tomorrow's already have a "Birthdays" row of their own on the
    daily view; these are the ones still far enough off to post a card for.
    Each is named the way that row names it ("Jane Doe", not "Jane Doe's
    birthday"), and listed once however many calendars carry it.
    """
    today = now.astimezone(tz).date()
    first_day = today + timedelta(days=2)
    end_day = today + timedelta(days=BIRTHDAY_LOOKAHEAD_DAYS)
    seen = set()
    upcoming: List[Event] = []
    for e in sorted(events, key=lambda e: (e.start, e.title.lower())):
        if not e.birthday:
            continue
        day = e.start.astimezone(tz).date()
        name = _birthday_label(e.title)
        key = (day, name.lower())
        if not first_day <= day < end_day or key in seen:
            continue
        seen.add(key)
        upcoming.append(replace(e, title=name))
    return upcoming


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
        # all-day events from different days into a single row). The fetch
        # runs past its seven days for the birthdays; what's beyond them is
        # cut here, or a change next week would repaint this week's view.
        week=_dedupe_events(clip_events_to_range(raw_events, *_week_range(now, tz), tz)),
        upcoming_birthdays=_upcoming_birthdays(raw_events, now, tz),
    )


def _fetch_view_events(
    cfg, now: datetime, tz: ZoneInfo, problems: Optional[List[FetchProblem]] = None
) -> _ViewEvents:
    # Today, tomorrow and the weekly view's seven days all fall within the
    # birthday lookahead, so one fetch of that span feeds both views. A backend
    # takes the same round trips to answer for two weeks as for one day, and
    # this replaces the separate today and tomorrow fetches the daily view used
    # to make on its own.
    fetch_start, fetch_end = _week_range(now, tz, days=BIRTHDAY_LOOKAHEAD_DAYS)
    return _split_for_views(_fetch_raw_events(cfg, fetch_start, fetch_end, tz, problems=problems), now, tz)


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
    upcoming_birthdays: Optional[List[Event]] = None,
    fetch_problems: Optional[List[FetchProblem]] = None,
) -> str:
    # Only include fields that affect rendering. Weather and travel times are
    # left out: they're looked up only when a frame is drawn, weather changes
    # by the hour regardless (the hourly repaint picks it up), and a travel
    # time follows from the locations, which are already in here. Whether the
    # forecast could be fetched at all *is* in here, as one of fetch_problems:
    # a frame drawn while it was down repaints, with its weather, as soon as
    # it's back, instead of waiting out the hour with neither.
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
        "upcoming_birthdays": [_event_payload(e) for e in (upcoming_birthdays or [])],
        "fetch_problems": [str(p) for p in (fetch_problems or [])],
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
    # What couldn't be fetched, for the notice at the bottom of either view.
    fetch_problems: List[FetchProblem] = field(default_factory=list)


def _view_signature(view_mode: str, snap: _Snapshot, tz: ZoneInfo) -> str:
    """The content hash of `view_mode` as `snap` would draw it (see _events_signature)."""
    if view_mode == "weekly":
        return _events_signature(
            tz, [], [], snap.weather_alerts, snap.header_date, snap.show_banner,
            snap.wifi_status, snap.ups_status,
            update_pending=snap.update_pending,
            view_mode="weekly",
            week_events=snap.events.week,
            fetch_problems=snap.fetch_problems,
        )
    return _events_signature(
        tz, snap.events.today, snap.events.tomorrow, snap.weather_alerts, snap.header_date,
        snap.show_banner, snap.wifi_status, snap.ups_status, snap.reminders,
        update_pending=snap.update_pending,
        view_mode="daily",
        upcoming_birthdays=snap.events.upcoming_birthdays,
        fetch_problems=snap.fetch_problems,
    )


def _render_view(
    view_mode: str,
    snap: _Snapshot,
    cfg,
    tz: ZoneInfo,
    weather_resolver: WeatherForecastResolver,
    geocoder: Optional[Geocoder] = None,
) -> Image.Image:
    if view_mode == "weekly":
        # Each day's high, low and any rain or snow, from the same download
        # as the daily view's per-event weather.
        try:
            day_forecasts = weather_resolver.daily_forecasts()
        except Exception as e:
            print(f"Weather forecast lookup failed; drawing the week without it. Error: {e}")
            day_forecasts = {}
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
            day_forecasts=day_forecasts,
            fetch_problems=snap.fetch_problems,
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
    # Both days' addresses, so a place on each is looked up and forecast once.
    place_resolvers = _event_place_forecasts([*today, *tomorrow], cfg, geocoder)
    today = _apply_weather_forecast(
        today,
        cfg.timezone,
        cfg.weather.latitude,
        cfg.weather.longitude,
        resolver=weather_resolver,
        place_resolvers=place_resolvers,
    )
    tomorrow = _apply_weather_forecast(
        tomorrow,
        cfg.timezone,
        cfg.weather.latitude,
        cfg.weather.longitude,
        include_end_weather_for_long_events=False,
        resolver=weather_resolver,
        place_resolvers=place_resolvers,
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
        upcoming_birthdays=snap.events.upcoming_birthdays,
        fetch_problems=snap.fetch_problems,
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
    # If we just entered tonight's sleep window and haven't applied banner yet, we will render once with banner.
    # Past midnight, tonight is still the window that started yesterday (see _sleep_window_start_date).
    night = _sleep_window_start_date(now, sleep_start, sleep_end).isoformat()
    should_apply_sleep_banner = False
    if cfg.sleep.enabled and in_sleep:
        # Apply banner once per night when in sleep window
        if state.last_sleep_banner_date != night:
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
    # Whatever can't be fetched is drawn without, and listed at the bottom of
    # the screen so it doesn't pass for an empty day (see inkycal.fetchnotice).
    fetch_problems: List[FetchProblem] = []
    # The forecast is downloaded on every run, not just for a frame being
    # drawn, so that its failing and its coming back both change the content
    # hash. A failure is kept by the resolver, so the lookups at draw time
    # don't each wait out the timeout again.
    try:
        weather_resolver.load()
    except Exception as e:
        print(f"Weather forecast download failed; drawing without weather. Error: {e}")
        fetch_problems.append(FetchProblem(WEATHER, describe_error(e)))
    try:
        weather_alerts = weather_resolver.active_alerts()
    except Exception as e:
        print(f"NWS alert lookup failed; continuing without alerts. Error: {e}")
        fetch_problems.append(FetchProblem(WEATHER_ALERTS, describe_error(e)))
        weather_alerts = []

    # Everything both views show, fetched once. The view on the panel is
    # checked against what's there; the other is kept drawn for the view
    # button (see _keep_frames_current).
    _, day_end = _today_range(now, tz)
    events = _fetch_view_events(cfg, now, tz, problems=fetch_problems)
    if fetch_problems:
        print("Fetch problems shown on screen: " + "; ".join(str(p) for p in fetch_problems))
    snap = _Snapshot(
        now=now,
        events=events,
        reminders=_fetch_reminders_for_day(cfg, day_end, tz),
        weather_alerts=weather_alerts,
        header_date=now.strftime("%A, %B %-d, %Y"),
        show_banner=in_sleep and cfg.sleep.enabled,
        wifi_status=get_wifi_status(),
        ups_status=get_ups_status(),
        update_pending=update_pending,
        fetch_problems=fetch_problems,
    )
    signatures = {mode: _view_signature(mode, snap, tz) for mode in VIEW_MODES}
    sig = signatures[view_mode]

    # Event addresses are only looked up for a daily frame being drawn, and
    # each is remembered next to state.json (see inkycal.geocode).
    geocoder = None
    if cfg.weather.event_locations:
        geocoder = Geocoder(
            os.path.join(os.path.dirname(state_path) or ".", GEOCODE_CACHE_FILE_NAME),
            near=(cfg.weather.latitude, cfg.weather.longitude),
        )

    def render(mode: str) -> Image.Image:
        return _render_view(mode, snap, cfg, tz, weather_resolver, geocoder)

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
        try:
            show_on_inky(img, rotate_degrees=cfg.display.rotate_degrees, border=cfg.display.border)
        except SetupModeActive:
            # The panel is showing the setup code for the companion app. Record
            # nothing: the setup screen cleared the render hash, so the first
            # run after setup mode ends repaints whatever this one would have.
            print("Setup mode is on; leaving its code on the panel")
            return
        # Keep a copy of what's on the panel so a button press can redraw it with a
        # "working on it" bar instead of blanking the screen (see inkycal.feedback).
        frames.save_frame(state_path, view_mode, img, sig, now)

        state.last_hash = sig
        state.last_rendered_iso = now.isoformat()
        if should_apply_sleep_banner:
            state.last_sleep_banner_date = night
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
