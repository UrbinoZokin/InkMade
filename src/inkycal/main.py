from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, time, timedelta
from typing import List
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

from .calendar_google import fetch_google_events
from .calendar_icloud import fetch_icloud_events
from .config import load_config
from .display_inky import show_on_inky
from .models import Event
from .network import get_ups_status, get_wifi_status
from .render import render_daily_schedule
from .state import State, load_state, save_state
from .travel import TravelTimeResolver

STATE_PATH_DEFAULT = "/var/lib/inkycal/state.json"
CONFIG_PATH_DEFAULT = "/opt/inkycal/config.yaml"


def _parse_hhmm(s: str) -> time:
    hh, mm = s.split(":")
    return time(hour=int(hh), minute=int(mm))


def _is_in_sleep_window(now: datetime, start: time, end: time) -> bool:
    # Handles overnight windows (e.g., 22:30 -> 06:30)
    t = now.timetz().replace(tzinfo=None)
    if start < end:
        return start <= t < end
    return (t >= start) or (t < end)


def _today_range(now: datetime, tz: ZoneInfo):
    local = now.astimezone(tz)
    day_start = local.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = day_start + timedelta(days=1)
    return day_start, day_end


def _normalize_text(value: str | None) -> str:
    if not value:
        return ""
    return " ".join(value.strip().lower().split())


def _event_sort_key(e: Event):
    return (0 if e.all_day else 1, e.start, e.title.lower())


def _dedupe_events(events: List[Event]) -> List[Event]:
    deduped: List[Event] = []
    seen = set()
    for e in sorted(events, key=_event_sort_key):
        key = (
            _normalize_text(e.title),
            e.start.isoformat(),
            e.end.isoformat(),
            bool(e.all_day),
            _normalize_text(e.location),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(e)
    return deduped


def _merge_all_day_events(events: List[Event]) -> List[Event]:
    all_day_events = [e for e in events if e.all_day]
    timed_events = [e for e in events if not e.all_day]
    if not all_day_events:
        return timed_events

    sorted_titles = sorted(e.title.strip() for e in all_day_events if e.title.strip())
    if not sorted_titles:
        summary_title = "All-day events"
    elif len(sorted_titles) == 1:
        summary_title = f"All-day: {sorted_titles[0]}"
    elif len(sorted_titles) == 2:
        summary_title = f"All-day: {sorted_titles[0]}, {sorted_titles[1]}"
    else:
        summary_title = f"All-day: {sorted_titles[0]}, {sorted_titles[1]}, +{len(sorted_titles) - 2} more"

    merged = Event(
        source="merged",
        title=summary_title,
        start=min(e.start for e in all_day_events),
        end=max(e.end for e in all_day_events),
        all_day=True,
    )
    return [merged, *sorted(timed_events, key=_event_sort_key)]


def _apply_travel_times(events: List[Event], origin_address: str, back_to_back_window_minutes: int) -> List[Event]:
    if not origin_address:
        return events

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


def _process_events(events: List[Event], travel_enabled: bool, origin_address: str, back_to_back_window_minutes: int) -> List[Event]:
    processed = _dedupe_events(events)
    processed = _merge_all_day_events(processed)
    if travel_enabled:
        processed = _apply_travel_times(processed, origin_address, back_to_back_window_minutes)
    return processed


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
    header_date: str,
    sleep_banner: bool,
    wifi_status: str,
    ups_status: dict,
) -> str:
    # Only include fields that affect rendering.
    def _event_payload(e: Event) -> dict:
        return {
            "source": e.source,
            "title": e.title,
            "start": e.start.astimezone(tz).isoformat(),
            "end": e.end.astimezone(tz).isoformat(),
            "all_day": e.all_day,
            "location": e.location or "",
            "travel_time_text": e.travel_time_text or "",
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
    }
    b = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(b).hexdigest()


def run_once(
    config_path: str = CONFIG_PATH_DEFAULT,
    state_path: str = STATE_PATH_DEFAULT,
    force: bool = False,
    deep_clean: bool = False,
) -> None:
    load_dotenv()
    cfg = load_config(config_path)
    tz = ZoneInfo(cfg.timezone)

    state = load_state(state_path)
    now = datetime.now(tz=tz)

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

    # Fetch events (only needed if we're not just placing a banner)
    day_start, day_end = _today_range(now, tz)
    tomorrow_start = day_start + timedelta(days=1)
    tomorrow_end = day_end + timedelta(days=1)
    events: List[Event] = []
    tomorrow_events: List[Event] = []
    if cfg.google.enabled:
        creds_path = os.environ.get("GOOGLE_CREDENTIALS_JSON", "")
        token_path = os.environ.get("GOOGLE_TOKEN_JSON", "")
        if creds_path and token_path:
            events.extend(
                fetch_google_events(cfg.google.calendar_ids, day_start, day_end, tz, creds_path, token_path)
            )
            tomorrow_events.extend(
                fetch_google_events(cfg.google.calendar_ids, tomorrow_start, tomorrow_end, tz, creds_path, token_path)
            )

    if cfg.icloud.enabled:
        try:
            user = os.environ.get("ICLOUD_USERNAME", "")
            pw = os.environ.get("ICLOUD_APP_PASSWORD", "")
            if user and pw:
                events.extend(
                    fetch_icloud_events(day_start, day_end, tz, user, pw, cfg.icloud.calendar_name_allowlist)
                )
                tomorrow_events.extend(
                    fetch_icloud_events(
                        tomorrow_start,
                        tomorrow_end,
                        tz,
                        user,
                        pw,
                        cfg.icloud.calendar_name_allowlist,
                    )
                )
            else:
                print("iCloud enabled but ICLOUD_USERNAME/ICLOUD_APP_PASSWORD not set; skipping iCloud.")
        except Exception as e:
            print(f"iCloud fetch failed; continuing without iCloud. Error: {e}")

    events = _process_events(
        events,
        travel_enabled=cfg.travel.enabled,
        origin_address=cfg.travel.origin_address,
        back_to_back_window_minutes=cfg.travel.back_to_back_window_minutes,
    )
    tomorrow_events = _process_events(
        tomorrow_events,
        travel_enabled=cfg.travel.enabled,
        origin_address=cfg.travel.origin_address,
        back_to_back_window_minutes=cfg.travel.back_to_back_window_minutes,
    )

    # Render signature includes whether we show the sleep banner
    header_date = now.strftime("%A, %B %-d, %Y")
    show_banner = in_sleep and cfg.sleep.enabled
    wifi_status = get_wifi_status()
    ups_status = get_ups_status()
    sig = _events_signature(tz, events, tomorrow_events, header_date, show_banner, wifi_status, ups_status)
    should_force_hourly = _should_force_hourly_refresh(state, now, timedelta(hours=1))
    print(
        f"Fetched {len(events)} events total; in_sleep={in_sleep}, show_banner={show_banner}, "
        f"force={force}, deep_clean={deep_clean}, hourly_refresh={should_force_hourly}"
    )
    if (
        (not force)
        and (not deep_clean)
        and (not should_apply_sleep_banner)
        and (not should_force_hourly)
        and (sig == state.last_hash)
    ):
        print("No schedule change; skipping display refresh")
        return

    img = render_daily_schedule(
        canvas_w=cfg.display.width,
        canvas_h=cfg.display.height,
        now=now,
        events=events,
        tz=tz,
        show_sleep_banner=show_banner,
        sleep_banner_text=cfg.sleep.banner_text,
        wifi_status=wifi_status,
        ups_status=ups_status,
        tomorrow_events=tomorrow_events,
    )

    show_on_inky(img, rotate_degrees=cfg.display.rotate_degrees, border=cfg.display.border)

    state.last_hash = sig
    state.last_rendered_iso = now.isoformat()
    if should_apply_sleep_banner:
        state.last_sleep_banner_date = today_str
    save_state(state_path, state)


def main():
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=CONFIG_PATH_DEFAULT)
    ap.add_argument("--state", default=STATE_PATH_DEFAULT)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--deep-clean", action="store_true")
    args = ap.parse_args()

    run_once(config_path=args.config, state_path=args.state, force=args.force, deep_clean=args.deep_clean)


if __name__ == "__main__":
    main()
