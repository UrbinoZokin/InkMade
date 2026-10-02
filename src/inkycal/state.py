from __future__ import annotations
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any
import json

STATE_PATH_DEFAULT = "/var/lib/inkycal/state.json"

VIEW_MODES = ("daily", "weekly")


def toggle_view_mode(current: str) -> str:
    """The view the view-toggle button switches to from `current`."""
    return "weekly" if current != "weekly" else "daily"


@dataclass
class State:
    last_hash: str = ""
    last_rendered_iso: str = ""
    # The night the sleep banner was last painted for, as the YYYY-MM-DD its
    # sleep window started on: the evening's date, even after midnight.
    last_sleep_banner_date: str = ""
    view_mode: str = "daily"  # one of VIEW_MODES; set by the view-toggle button

def load_state(path: str) -> State:
    """The saved state, or a blank one when it cannot be read.

    Nothing in here may raise. run_once() loads the state before it does
    anything else, so an exception at this point takes the whole refresh with
    it -- and because e-ink holds its last image and every subsequent run dies
    in the same place, the panel then sits on a stale day forever with no sign
    of why. A damaged state file is not hypothetical on this device:
    /var/lib/inkycal is on the SD card and the power can go mid-write, leaving
    a truncated or empty file behind (save_state's atomic rename closes that
    window for writes made since, not for a file already torn by an older
    version, and the same file is also written by button presses).

    Falling back to a blank State() is what makes that self-healing: an empty
    last_hash reads as "nothing on the panel is mine", so the next run
    repaints unconditionally and writes a clean file over the damaged one.
    """
    p = Path(path)
    if not p.exists():
        return State()

    try:
        raw = p.read_text(encoding="utf-8")
    except OSError as e:
        print(f"Could not read state at {path}: {e}; starting from a blank state")
        return State()

    try:
        data: Any = json.loads(raw)
    except ValueError as e:
        print(f"State at {path} is not valid JSON ({e}); starting from a blank state")
        return State()

    if not isinstance(data, dict):
        print(
            f"State at {path} holds {type(data).__name__}, not an object; "
            "starting from a blank state"
        )
        return State()

    view_mode = str(data.get("view_mode", "daily"))
    if view_mode not in VIEW_MODES:
        view_mode = "daily"
    return State(
        last_hash=str(data.get("last_hash", "")),
        last_rendered_iso=str(data.get("last_rendered_iso", "")),
        last_sleep_banner_date=str(data.get("last_sleep_banner_date", "")),
        view_mode=view_mode,
    )

def save_state(path: str, state: State) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    # Write-then-rename so a writer racing another (e.g. a button press
    # overlapping the periodic timer) can't leave a torn/corrupted file.
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(asdict(state), indent=2), encoding="utf-8")
    tmp.replace(p)


def invalidate_render_hash(path: str) -> None:
    """Force the next scheduled render to actually repaint the panel.

    run_once skips the refresh when the content hash matches what's already on
    screen -- but what's on screen now is something else: a press notice
    (inkycal.feedback) or the setup-mode code (inkycal.setupscreen). Without
    clearing the hash, one whose follow-up never repaints (an OTA check that
    finds nothing, a crash mid-fetch, a setup session that dies) would stay up
    until the content itself happened to change.
    """
    state = load_state(path)
    if not state.last_hash:
        return
    state.last_hash = ""
    try:
        save_state(path, state)
    except OSError as e:
        print(f"Could not clear render hash at {path}: {e}")
