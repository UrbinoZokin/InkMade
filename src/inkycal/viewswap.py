"""The view button's fast path: put the other view's saved frame straight up.

Switching views used to cost two full-panel refreshes with a fetch between
them: a "Switching view... please wait" notice (inkycal.feedback), then the
10-60 s of fetching calendars, weather and travel times, then the new view.
Every render now also keeps the view that isn't on screen drawn and saved
(inkycal.frames), so a press can usually go straight to it: one refresh,
starting a few seconds after the press, and the new view is its own
acknowledgement.

A saved frame is only used when it was drawn today and less than an hour ago
-- the same hour the panel itself is held to. Otherwise this exits with
NO_FRESH_FRAME having touched nothing, and inkycal.buttons falls back to the
notice-then-render path.

A frame that passes can still be up to a quarter hour behind the calendars,
so the button handler follows it with an ordinary inkycal.main run, which
repaints only if something changed since the frame was drawn.

Runs as its own entrypoint, like inkycal.feedback, so the press pays for PIL
and the config loader rather than the Google/CalDAV import chain behind
inkycal.main.
"""
from __future__ import annotations

import sys
from datetime import datetime
from zoneinfo import ZoneInfo

from .config import CONFIG_PATH_DEFAULT, load_config
from .display_inky import show_on_inky
from .frames import is_fresh, load_frame
from .state import STATE_PATH_DEFAULT, load_state, save_state, toggle_view_mode

# Exit status for "no fresh saved frame, nothing touched", so the button
# handler can tell it apart from a failure part-way through.
NO_FRESH_FRAME = 3


def show_other_view(config_path: str, state_path: str) -> bool:
    """Switch to the other view from its saved frame. False if there isn't a fresh one."""
    cfg = load_config(config_path)
    tz = ZoneInfo(cfg.timezone)
    now = datetime.now(tz=tz)
    target = toggle_view_mode(load_state(state_path).view_mode)

    saved = load_frame(state_path, target)
    if saved is None:
        print(f"No saved {target} frame to switch to")
        return False
    img, info = saved
    if img.size != (cfg.display.width, cfg.display.height):
        print(f"Saved {target} frame is {img.size[0]}x{img.size[1]}, not the display's size")
        return False
    if not is_fresh(info, now):
        print(f"Saved {target} frame from {info.rendered_at.astimezone(tz):%a %H:%M} is too old to show")
        return False

    print(f"Showing the {target} frame saved at {info.rendered_at.astimezone(tz):%H:%M}")
    show_on_inky(img, rotate_degrees=cfg.display.rotate_degrees, border=cfg.display.border)

    # Re-read rather than reuse the state loaded above: the panel can be busy
    # for minutes with another render, which saves its own changes meanwhile.
    state = load_state(state_path)
    state.view_mode = target
    # The panel now shows that frame's content as of its own time, so the next
    # run compares against it and times the hourly repaint from it.
    state.last_hash = info.content_hash
    state.last_rendered_iso = info.rendered_at.isoformat()
    save_state(state_path, state)
    return True


def main() -> None:
    import argparse

    ap = argparse.ArgumentParser(description="Switch the display to the other view's saved frame.")
    ap.add_argument("--config", default=CONFIG_PATH_DEFAULT)
    ap.add_argument("--state", default=STATE_PATH_DEFAULT)
    args = ap.parse_args()

    if not show_other_view(config_path=args.config, state_path=args.state):
        sys.exit(NO_FRESH_FRAME)


if __name__ == "__main__":
    main()
