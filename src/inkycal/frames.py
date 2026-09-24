"""A finished frame of each view, kept on disk next to state.json.

Every render is its own short-lived process (a timer tick or a button press),
so nothing it draws is still in memory by the next one. These files are what
carries over, one per view:

  - the view on the panel, so a button press can draw its "working on it"
    notice over the schedule instead of blanking it (inkycal.feedback)
  - the view that isn't, drawn ahead of time so the view button can put it
    straight up instead of fetching and drawing it first (inkycal.viewswap)

Each file records in its own PNG text chunks which view it is, a hash of the
content it was drawn from (main._events_signature) and when it was drawn. A
frame can then be judged on its own, without trusting state.json to still
agree with it after a crash, a power cut or two renders racing each other.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional, Tuple

from PIL import Image, PngImagePlugin

FRAME_FILE_NAMES = {"daily": "frame_daily.png", "weekly": "frame_weekly.png"}

# How long a saved frame may stand in for a fresh render: the same hour the
# panel itself is held to (main._should_force_hourly_refresh repaints it at
# least hourly, so its "Updated" time is never further behind than this).
FRESH_FOR = timedelta(hours=1)

# Renders come every quarter hour (systemd/inkycal.timer), each landing up to
# a minute or so off schedule. Redrawing the view that isn't on screen once
# it's 40 minutes old -- a quarter hour for the gap between renders, and five
# minutes' slack for their drift -- means the third render after a redraw
# always catches it, so it never nears FRESH_FOR waiting for the next one.
REDRAW_AFTER = FRESH_FOR - timedelta(minutes=20)

_KEY_VIEW = "inkycal-view"
_KEY_HASH = "inkycal-content-hash"
_KEY_RENDERED = "inkycal-rendered"


@dataclass(frozen=True)
class FrameInfo:
    view_mode: str
    content_hash: str  # main._events_signature of what was drawn
    rendered_at: datetime  # timezone-aware; the frame's "Updated" time
    size: Tuple[int, int]


def frame_path(state_path: str, view_mode: str) -> str:
    return os.path.join(os.path.dirname(state_path) or ".", FRAME_FILE_NAMES[view_mode])


def save_frame(
    state_path: str,
    view_mode: str,
    img: Image.Image,
    content_hash: str,
    rendered_at: datetime,
) -> bool:
    """Keep `img` as `view_mode`'s frame. Returns False when it couldn't be.

    Best effort: a render that can't keep its frame is still a good render, so
    a failure here only costs the next button press its shortcut. The file is
    written under a temporary name and renamed into place, so a reader never
    sees half a frame. That name carries the pid because the timer's render
    and a button press's can be saving the same view at once.
    """
    path = frame_path(state_path, view_mode)
    tmp = f"{path}.{os.getpid()}.tmp"
    meta = PngImagePlugin.PngInfo()
    meta.add_text(_KEY_VIEW, view_mode)
    meta.add_text(_KEY_HASH, content_hash)
    meta.add_text(_KEY_RENDERED, rendered_at.isoformat())
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        img.convert("RGB").save(tmp, format="PNG", pnginfo=meta)
        os.replace(tmp, path)
        return True
    except (OSError, ValueError) as e:
        print(f"Could not save the {view_mode} frame at {path}: {e}")
        try:
            os.unlink(tmp)
        except OSError:
            pass
        return False


def _frame_info(img: Image.Image, view_mode: str) -> Optional[FrameInfo]:
    text = img.info
    try:
        rendered_at = datetime.fromisoformat(str(text[_KEY_RENDERED]))
    except (KeyError, ValueError):
        return None
    content_hash = str(text.get(_KEY_HASH, ""))
    # A frame from before these files carried their view (or one renamed by
    # hand) can't vouch for what it shows, and neither can one with no hash.
    if text.get(_KEY_VIEW) != view_mode or not content_hash or rendered_at.tzinfo is None:
        return None
    return FrameInfo(view_mode=view_mode, content_hash=content_hash, rendered_at=rendered_at, size=img.size)


def read_frame_info(state_path: str, view_mode: str) -> Optional[FrameInfo]:
    """What `view_mode`'s saved frame was drawn from, or None if there isn't a usable one.

    Reads only the PNG header and text chunks; the pixels are never decoded.
    """
    try:
        with Image.open(frame_path(state_path, view_mode)) as img:
            return _frame_info(img, view_mode)
    except (OSError, ValueError):
        return None


def load_frame(state_path: str, view_mode: str) -> Optional[Tuple[Image.Image, FrameInfo]]:
    """`view_mode`'s saved frame and what it was drawn from, or None."""
    try:
        with Image.open(frame_path(state_path, view_mode)) as img:
            info = _frame_info(img, view_mode)
            if info is None:
                return None
            img.load()
            return img.convert("RGB"), info
    except (OSError, ValueError):
        return None


def is_fresh(info: FrameInfo, now: datetime, max_age: timedelta = FRESH_FOR) -> bool:
    """Drawn today, less than `max_age` ago, and not stamped in the future.

    "Today" matters as much as the age: a frame drawn at 23:50 still reads as
    yesterday at 00:05 -- its header, and the weekly view's seven days.
    """
    age = now - info.rendered_at
    return timedelta(0) <= age < max_age and info.rendered_at.astimezone(now.tzinfo).date() == now.date()
