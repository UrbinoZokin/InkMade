"""Immediate on-display acknowledgement that a button press was received.

The Inky Impression has no partial refresh: every update repaints the whole
panel, and on the 13.3" model that takes the better part of a minute. A
button press has to fetch calendars, weather and travel times before it has
anything to draw, so the screen sits perfectly still for 10-60 s and there is
no way to tell whether the press registered at all.

This module paints a short "working on it" frame *before* that work starts.
The panel begins its visible flash a few seconds after the press, which is
the acknowledgement; the real content lands when the fetch finishes. It costs
one extra full-panel refresh, so the content arrives roughly twice as slowly
as before -- that trade is what `buttons.press_feedback` in config.yaml
selects:

    banner - re-show the last rendered frame with a notice bar on top (default)
    wipe   - clear the panel to white with the notice centred
    none   - no acknowledgement; the display stays put until content is ready

Rendering the calendar again is not an option here (that's the slow part we
are covering for), so `banner` redraws the last frame that main.run_once
cached next to state.json. If that file is missing or stale-shaped, it falls
back to `wipe`.

Runs as its own entrypoint (`python -m inkycal.feedback --message ...`) so a
press pays only for PIL and the config loader, not the Google/CalDAV import
chain that inkycal.main pulls in.
"""
from __future__ import annotations

import os
from typing import Optional

from PIL import Image, ImageDraw

from .config import load_config
from .display_inky import show_on_inky
from .render import _load_bold_font, _load_font, _wrap_text
from .state import load_state, save_state

STYLE_BANNER = "banner"
STYLE_WIPE = "wipe"
STYLE_NONE = "none"
VALID_STYLES = (STYLE_BANNER, STYLE_WIPE, STYLE_NONE)

# Cached copy of the last frame pushed to the panel, written by
# main.run_once and read back here to draw the banner over.
LAST_FRAME_NAME = "last_frame.png"


def last_frame_path(state_path: str) -> str:
    return os.path.join(os.path.dirname(state_path) or ".", LAST_FRAME_NAME)


def save_last_frame(state_path: str, img: Image.Image) -> None:
    """Cache the frame just shown, for the banner style to draw over.

    Best effort: a render that can't cache its frame is still a good render,
    so failures here only cost the next press its banner.
    """
    path = last_frame_path(state_path)
    tmp = path + ".tmp"
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        img.convert("RGB").save(tmp, format="PNG")
        os.replace(tmp, path)
    except (OSError, ValueError) as e:
        print(f"Could not cache last frame at {path}: {e}")
        try:
            os.unlink(tmp)
        except OSError:
            pass


def load_last_frame(state_path: str, canvas_w: int, canvas_h: int) -> Optional[Image.Image]:
    """The cached frame, or None if it is missing, unreadable or a different size."""
    path = last_frame_path(state_path)
    try:
        with Image.open(path) as img:
            img.load()
            frame = img.convert("RGB")
    except (OSError, ValueError):
        return None
    if frame.size != (canvas_w, canvas_h):
        return None
    return frame


def _fitted_font(draw: ImageDraw.ImageDraw, text: str, max_width: float, start_size: int, bold: bool = True):
    """Largest font (down to a floor) at which `text` fits on one line."""
    loader = _load_bold_font if bold else _load_font
    size = start_size
    while size > 24:
        font = loader(size)
        if draw.textlength(text, font=font) <= max_width:
            return font
        size -= 4
    return loader(size)


def render_notice(
    message: str,
    canvas_w: int,
    canvas_h: int,
    base: Optional[Image.Image] = None,
) -> Image.Image:
    """A frame announcing `message`.

    With `base`, the message goes in a black bar across the top of that frame:
    the schedule stays readable, and a solid bar is unmissable even from across
    the room. Without one, the panel is cleared to white and the message is
    centred -- the "wipe" the same press would otherwise get no sign of.
    """
    padding = 40

    if base is not None:
        img = base.copy()
        d = ImageDraw.Draw(img)
        font = _fitted_font(d, message, canvas_w - (2 * padding), start_size=64)
        bar_h = int(font.size * 2.2)
        d.rectangle((0, 0, canvas_w, bar_h), fill="black")
        text_w = d.textlength(message, font=font)
        d.text(((canvas_w - text_w) / 2, (bar_h - font.size) / 2 - 4), message, fill="white", font=font)
        return img

    img = Image.new("RGB", (canvas_w, canvas_h), "white")
    d = ImageDraw.Draw(img)
    font = _load_bold_font(72)
    lines = _wrap_text(d, message, font, canvas_w - (2 * padding), max_lines=3)
    line_h = font.size + 16
    y = (canvas_h - (line_h * len(lines))) / 2
    for line in lines:
        d.text(((canvas_w - d.textlength(line, font=font)) / 2, y), line, fill="black", font=font)
        y += line_h
    return img


def _invalidate_render_hash(state_path: str) -> None:
    """Force the next scheduled render to actually repaint the panel.

    run_once skips the refresh when the content hash matches what's already on
    screen -- but what's on screen is now this notice, not that content. Without
    clearing the hash, a notice whose follow-up work never repaints (an OTA check
    that finds nothing, a crash mid-fetch) would stay up until the content itself
    happened to change.
    """
    try:
        state = load_state(state_path)
    except (OSError, ValueError) as e:
        print(f"Could not clear render hash at {state_path}: {e}")
        return
    if not state.last_hash:
        return
    state.last_hash = ""
    try:
        save_state(state_path, state)
    except OSError as e:
        print(f"Could not clear render hash at {state_path}: {e}")


def resolve_style(configured: str, requested: Optional[str] = None) -> str:
    style = (requested or configured or STYLE_BANNER).strip().lower()
    return style if style in VALID_STYLES else STYLE_BANNER


def show_notice(
    message: str,
    config_path: str,
    state_path: str,
    style: Optional[str] = None,
) -> bool:
    """Paint `message` on the panel. Returns False when nothing was shown."""
    cfg = load_config(config_path)
    style = resolve_style(cfg.buttons.press_feedback, style)
    if style == STYLE_NONE:
        print("Press feedback disabled (buttons.press_feedback: none); not showing a notice.")
        return False

    base = None
    if style == STYLE_BANNER:
        base = load_last_frame(state_path, cfg.display.width, cfg.display.height)
        if base is None:
            print("No cached frame to draw the notice over; clearing the panel instead.")

    img = render_notice(message, cfg.display.width, cfg.display.height, base=base)
    show_on_inky(img, rotate_degrees=cfg.display.rotate_degrees, border=cfg.display.border)
    _invalidate_render_hash(state_path)
    return True


def main() -> None:
    import argparse

    from .main import CONFIG_PATH_DEFAULT, STATE_PATH_DEFAULT

    ap = argparse.ArgumentParser(description="Show a short notice on the Inky display.")
    ap.add_argument("--message", required=True)
    ap.add_argument("--config", default=CONFIG_PATH_DEFAULT)
    ap.add_argument("--state", default=STATE_PATH_DEFAULT)
    ap.add_argument("--style", choices=VALID_STYLES, default=None, help="Overrides buttons.press_feedback")
    args = ap.parse_args()

    show_notice(args.message, config_path=args.config, state_path=args.state, style=args.style)


if __name__ == "__main__":
    main()
