from __future__ import annotations
import hashlib
import json
import os
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo
from typing import List

from dotenv import load_dotenv

from .config import load_config
from .models import Event
from .state import load_state, save_state, State
from .render import render_daily_schedule
from .display_inky import show_on_inky
from .calendar_google import fetch_google_events
from .calendar_icloud import fetch_icloud_events

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

def _events_signature(tz: ZoneInfo, events: List[Event], header_date: str, sleep_banner: bool) -> str:
    # Only include fields that affect rendering.
    payload = {
        "header_date": header_date,
        "sleep_banner": sleep_banner,
        "events": [
            {
                "source": e.source,
                "title": e.title,
                "start": e.start.astimezone(tz).isoformat(),
                "end": e.end.astimezone(tz).isoformat(),
                "all_day": e.all_day,
                "location": e.location or "",
            }
            for e in events
        ],
    }
    b = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(b).hexdigest()

def run_once(config_path: str = CONFIG_PATH_DEFAULT, state_path: str = STATE_PATH_DEFAULT, force: bool = False, deep_clean: bool = False) -> None:
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

    events: List[Event] = []
    if cfg.google.enabled:
        creds_path = os.environ.get("GOOGLE_CREDENTIALS_JSON", "")
        token_path = os.environ.get("GOOGLE_TOKEN_JSON", "")
        if creds_path and token_path:
            events.extend(fetch_google_events(cfg.google.calendar_ids, day_start, day_end, tz, creds_path, token_path))

    # if cfg.icloud.enabled:
    #     user = os.environ.get("ICLOUD_USERNAME", "")
    #     pw = os.environ.get("ICLOUD_APP_PASSWORD", "")
    #     if user and pw:
    #         events.extend(fetch_icloud_events(day_start, day_end, tz, user, pw, cfg.icloud.calendar_name_allowlist))
    
    
    
    # Render signature includes whether we show the sleep banner
    header_date = now.strftime("%A, %B %-d, %Y")
    show_banner = in_sleep and cfg.sleep.enabled
    sig = _events_signature(tz, events, header_date, show_banner)
    print(f"Fetched {len(events)} events total; in_sleep={in_sleep}, show_banner={show_banner}, force={force}, deep_clean={deep_clean}")
    if (not force) and (not deep_clean) and (not should_apply_sleep_banner) and (sig == state.last_hash):
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
    )

    # For deep clean, we still "show" normally; if your driver supports explicit full refresh,
    # you can extend show_on_inky to call it here.
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
