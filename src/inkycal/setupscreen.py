"""What the panel shows while setup mode is on: the one-time setup code.

The provisioning agent (inkycal.provisioning) only accepts a new WiFi network
or Google token that carries this code, and the panel is the only place it is
ever shown -- so whoever pairs the companion app has to be standing in front
of the device. The rest of the time the agent isn't running at all.

Runs as its own entrypoint, like inkycal.feedback, so the agent -- which runs
as root -- can have it drawn as the app user: the panel lock and state.json
stay owned the way every other render leaves them. The code arrives on stdin
rather than on the command line, where any user on the Pi could read it out
of the process list.
"""
from __future__ import annotations

import sys
from typing import List, Optional, Tuple

from PIL import Image, ImageDraw, ImageFont

from .config import CONFIG_PATH_DEFAULT, load_config
from .display_inky import show_on_inky
from .feedback import _fitted_font
from .provisioning.protocol import BLE_LOCAL_NAME
from .render import _load_bold_font, _load_font, _wrap_text
from .state import STATE_PATH_DEFAULT, invalidate_render_hash

# The layout is drawn for the 13.3" panel's 1200 px width and scaled from there.
_DESIGN_WIDTH = 1200


def format_code(code: str) -> str:
    """482913 -> "482 913": two halves are easier to read off a wall and type in."""
    return f"{code[:3]} {code[3:]}" if len(code) == 6 else code


def render_setup_screen(
    code: str,
    canvas_w: int,
    canvas_h: int,
    *,
    minutes: int,
    address: Optional[str] = None,
) -> Image.Image:
    img = Image.new("RGB", (canvas_w, canvas_h), "white")
    d = ImageDraw.Draw(img)
    scale = canvas_w / _DESIGN_WIDTH
    padding = int(60 * scale)
    width = canvas_w - (2 * padding)

    def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
        return (_load_bold_font if bold else _load_font)(max(10, int(size * scale)))

    body = font(48)
    small = font(40)
    shown_code = format_code(code)
    footer = (
        f"Setup mode switches itself off after {minutes} minutes. "
        f"Press C for {minutes} more minutes, or A, B or D to go back to the calendar."
    )
    # (lines, font, space after the paragraph at design scale)
    paragraphs: List[Tuple[List[str], ImageFont.FreeTypeFont, int]] = [
        (["InkyCal setup"], font(80, bold=True), 70),
        (["Setup code"], font(52), 10),
        ([shown_code], _fitted_font(d, shown_code, width, start_size=int(240 * scale)), 80),
        (
            _wrap_text(d, "Open InkyCal Setup on your computer and type in this code when it asks.", body, width, None),
            body,
            60,
        ),
        ([f"Bluetooth: {BLE_LOCAL_NAME}", f"WiFi: {address or 'not connected'}"], small, 60),
        (_wrap_text(d, footer, small, width, None), small, 0),
    ]
    line_gap = int(12 * scale)

    def height(lines: List[str], f: ImageFont.FreeTypeFont) -> int:
        return len(lines) * f.size + (len(lines) - 1) * line_gap

    total_h = sum(height(lines, f) + int(after * scale) for lines, f, after in paragraphs)
    y = max(padding, (canvas_h - total_h) / 2)
    for lines, f, after in paragraphs:
        for text in lines:
            d.text(((canvas_w - d.textlength(text, font=f)) / 2, y), text, fill="black", font=f)
            y += f.size + line_gap
        y += int(after * scale) - line_gap
    return img


def show_setup_screen(
    code: str,
    config_path: str,
    state_path: str,
    *,
    minutes: int,
    address: Optional[str] = None,
) -> None:
    cfg = load_config(config_path)
    img = render_setup_screen(code, cfg.display.width, cfg.display.height, minutes=minutes, address=address)
    show_on_inky(img, rotate_degrees=cfg.display.rotate_degrees, border=cfg.display.border, setup_screen=True)
    # The panel shows the code now, not the schedule the hash describes; the
    # first render after setup mode ends has to repaint, however it ended.
    invalidate_render_hash(state_path)


def main() -> None:
    import argparse

    ap = argparse.ArgumentParser(description="Show the setup-mode code on the Inky display. Reads the code from stdin.")
    ap.add_argument("--config", default=CONFIG_PATH_DEFAULT)
    ap.add_argument("--state", default=STATE_PATH_DEFAULT)
    ap.add_argument("--minutes", type=int, required=True)
    ap.add_argument("--address", default="", help="The Pi's address on WiFi, if it has one")
    args = ap.parse_args()

    code = sys.stdin.readline().strip()
    if not code:
        ap.error("no setup code on stdin")
    show_setup_screen(code, args.config, args.state, minutes=args.minutes, address=args.address or None)


if __name__ == "__main__":
    main()
