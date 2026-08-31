"""Pushing a finished frame to the Inky Impression panel.

Every panel write in the project funnels through show_on_inky, so the lock it
takes is enough to keep two refreshes off the SPI bus at once. That matters
most at power-on: the boot refresh, the quarter-hour timer and the OTA check
can all want the panel within a couple of minutes of each other, and a button
press can land on top of any of them at any time. Two refreshes interleaved on
the bus leave a torn image on a panel that takes most of a minute to repaint.
"""
from __future__ import annotations

import errno
import fcntl
import os
import time
from contextlib import contextmanager
from typing import Iterator, Optional, TextIO

from PIL import Image

DISPLAY_LOCK_PATH = os.environ.get("INKYCAL_DISPLAY_LOCK", "/var/lib/inkycal/display.lock")

# A full repaint of the 13.3" Impression takes the better part of a minute, and
# a button press can queue an acknowledgement frame in front of one. Wait long
# enough to cover both rather than painting over a refresh in progress.
DISPLAY_LOCK_TIMEOUT_S = 180.0
_POLL_INTERVAL_S = 0.5


def _open_lock_file(path: str) -> Optional[TextIO]:
    """The lock file, creating it if needed, or None if it can't be opened.

    A dev machine or a test run has no /var/lib/inkycal to lock in, and a
    display we cannot lock is still a display we should draw on -- so a lock
    file we cannot open means "render unlocked", never "don't render".
    """
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        return open(path, "a+", encoding="utf-8")
    except (OSError, ValueError) as e:
        # ValueError covers a malformed INKYCAL_DISPLAY_LOCK (an embedded null,
        # say); OSError covers the ordinary read-only or unwritable path.
        print(f"Could not open display lock at {path}: {e}; rendering unlocked")
        return None


def _acquire(handle: TextIO, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    waited = False
    while True:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            if waited:
                print("Display free; refreshing now")
            return True
        except OSError as e:
            if e.errno not in (errno.EACCES, errno.EAGAIN):
                raise
        if time.monotonic() >= deadline:
            print(f"Display still busy after {timeout:.0f}s; refreshing without the lock")
            return False
        if not waited:
            print("Another refresh is using the display; waiting for it to finish")
            waited = True
        time.sleep(_POLL_INTERVAL_S)


@contextmanager
def display_lock(
    path: Optional[str] = None,
    timeout: float = DISPLAY_LOCK_TIMEOUT_S,
) -> Iterator[bool]:
    """Hold the exclusive panel lock for the block. Yields whether we got it.

    The path is resolved per call rather than bound as a default, so setting
    DISPLAY_LOCK_PATH keeps working after import.

    flock() is released by the kernel when the holder exits, so a render killed
    mid-refresh (a power cut, an OTA restart) cannot wedge the next one. If the
    wait does run out we draw anyway: a screen left showing yesterday is the
    failure this lock exists to avoid making worse, so a stuck holder must not
    also cost us the refresh.
    """
    handle = _open_lock_file(path if path is not None else DISPLAY_LOCK_PATH)
    if handle is None:
        yield False
        return
    try:
        yield _acquire(handle, timeout)
    finally:
        # Closing the descriptor drops the flock with it.
        handle.close()


def show_on_inky(img: Image.Image, rotate_degrees: int = 0, border: str = "white") -> None:
    """
    Displays a PIL image on Inky Impressions.
    Assumes the 'inky' library is installed on the Pi and hardware is connected.
    """
    if img.mode != "P":
        img = img.convert("P")

    if rotate_degrees:
        img = img.rotate(rotate_degrees, expand=True)

    from inky.auto import auto  # type: ignore

    # Detection reads the panel's EEPROM and show() drives the reset pin and the
    # SPI bus, so the whole hardware conversation happens under the lock. Only
    # the image work above is left outside it.
    with display_lock():
        disp = auto(ask_user=False, verbose=False)
        if disp is None:
            raise RuntimeError("Could not auto-detect Inky display. Check wiring and SPI enabled.")

        # Convert image to mode expected by inky; many accept RGB directly
        disp.set_border(border)
        disp.set_image(img)
        disp.show()
