"""Lightweight helpers for the over-the-air update feature.

The render loop uses these to *check* (never apply) whether the local checkout
is behind the tracked branch on GitHub, and to find when the program was last
updated, so it can show that in the status bar. Applying updates is done
separately by scripts/ota_update.sh. Everything here is best-effort and never
raises into the render path.
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

DEFAULT_APP_DIR = "/opt/inkycal"


def find_repo_dir(app_dir: Optional[str] = None) -> Optional[Path]:
    """Locate the git checkout the program is running from.

    Tries the given app_dir, then the repo root inferred from this file's
    location (editable install: <root>/src/inkycal/updates.py), then the
    default install path. Returns None if no .git is found.
    """
    candidates = []
    if app_dir:
        candidates.append(Path(app_dir))
    candidates.append(Path(__file__).resolve().parents[2])
    candidates.append(Path(DEFAULT_APP_DIR))
    for candidate in candidates:
        try:
            if (candidate / ".git").exists():
                return candidate
        except OSError:
            continue
    return None


@dataclass
class UpdateStatus:
    available: bool = False       # True when the checkout is behind origin/branch
    behind: int = 0               # number of commits behind
    local: str = ""               # short local HEAD sha
    remote: str = ""              # short origin/branch sha
    checked: bool = False         # the fetch succeeded (status reflects the live remote)
    error: str = ""               # populated when something went wrong


def _git(repo: Path, *args: str, timeout: int) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def check_for_update(
    branch: str = "main",
    app_dir: Optional[str] = None,
    fetch: bool = True,
    fetch_timeout: int = 20,
) -> UpdateStatus:
    """Return whether the local checkout is behind origin/<branch>.

    Fetches first (best effort). Even if the fetch fails — e.g. the Pi is
    offline — the comparison still runs against the last-known origin ref, so
    the status degrades gracefully instead of blowing up the render.
    """
    repo = find_repo_dir(app_dir)
    if repo is None:
        return UpdateStatus(error="no git checkout found")

    checked = False
    error = ""
    try:
        if fetch:
            fetched = _git(repo, "fetch", "--quiet", "origin", branch, timeout=fetch_timeout)
            checked = fetched.returncode == 0
            if not checked:
                stderr_lines = (fetched.stderr or "").strip().splitlines()
                error = stderr_lines[-1] if stderr_lines else "git fetch failed"

        local = _git(repo, "rev-parse", "--short", "HEAD", timeout=10)
        remote = _git(repo, "rev-parse", "--short", f"origin/{branch}", timeout=10)
        if local.returncode != 0 or remote.returncode != 0:
            return UpdateStatus(checked=checked, error=error or "could not read git revisions")

        behind_out = _git(repo, "rev-list", "--count", f"HEAD..origin/{branch}", timeout=10)
        behind = int(behind_out.stdout.strip()) if behind_out.returncode == 0 and behind_out.stdout.strip().isdigit() else 0

        return UpdateStatus(
            available=behind > 0,
            behind=behind,
            local=local.stdout.strip(),
            remote=remote.stdout.strip(),
            checked=checked,
            error=error,
        )
    except subprocess.TimeoutExpired:
        return UpdateStatus(checked=checked, error="git timed out")
    except Exception as exc:  # never break the render over an update check
        return UpdateStatus(checked=checked, error=str(exc))


def last_updated_dt(app_dir: Optional[str] = None) -> Optional[datetime]:
    """When the checkout was last moved to a new commit (i.e. last updated).

    Uses the modification time of .git/logs/HEAD, which git appends to every
    time HEAD changes (the initial clone and every ``git reset``/pull the
    updater does). Returns a timezone-aware local datetime, or None if it can't
    be determined.
    """
    repo = find_repo_dir(app_dir)
    if repo is None:
        return None
    for rel in (Path(".git") / "logs" / "HEAD", Path(".git") / "HEAD"):
        path = repo / rel
        try:
            if path.exists():
                return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).astimezone()
        except OSError:
            continue
    return None
