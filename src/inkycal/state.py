from __future__ import annotations
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional, Dict, Any
import json

@dataclass
class State:
    last_hash: str = ""
    last_rendered_iso: str = ""
    last_sleep_banner_date: str = ""  # YYYY-MM-DD when banner was last applied
    view_mode: str = "daily"  # "daily" or "weekly"; set by the view-toggle button

def load_state(path: str) -> State:
    p = Path(path)
    if not p.exists():
        return State()
    data: Dict[str, Any] = json.loads(p.read_text(encoding="utf-8"))
    view_mode = str(data.get("view_mode", "daily"))
    if view_mode not in ("daily", "weekly"):
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
