"""Running part of InkyCal as the app's own user, from a daemon that runs as root.

The button handler (GPIO, starting units) and the provisioning agent
(NetworkManager, BlueZ) both need root, but anything they start that touches
the panel or state.json should act exactly like the quarter-hour timer: as the
owner of the app directory, with that user's own groups (gpio/spi/i2c), so the
files it leaves behind stay writable by every run after it.
"""
from __future__ import annotations

import os
import pwd
import subprocess
from typing import Mapping, Optional, Sequence


def owner_ids(app_dir: str) -> tuple[int, int]:
    st = os.stat(app_dir)
    return st.st_uid, st.st_gid


def owner_groups(uid: int, gid: int) -> list[int]:
    # subprocess.run(user=, group=) alone does not call setgroups(); without
    # this, the child keeps the daemon's (root's) supplementary groups
    # instead of the app user's real ones (gpio/spi/i2c/video), unlike
    # systemd's own User=/Group= handling used by the periodic timer.
    try:
        username = pwd.getpwuid(uid).pw_name
        return os.getgrouplist(username, gid)
    except (KeyError, OSError):
        return [gid]


def run_module(
    app_dir: str,
    module: str,
    args: Sequence[str],
    *,
    env: Optional[Mapping[str, str]] = None,
    input: Optional[str] = None,
    timeout: Optional[float] = None,
) -> subprocess.CompletedProcess:
    """Run `python -m <module>` from the app's venv as the app directory's owner.

    `input` goes to the child's stdin, the one place to hand it something no
    other user on the Pi may see: arguments show up in the process list.
    """
    uid, gid = owner_ids(app_dir)
    venv_python = os.path.join(app_dir, "venv", "bin", "python")
    return subprocess.run(
        [venv_python, "-m", module, *args],
        cwd=app_dir,
        user=uid,
        group=gid,
        extra_groups=owner_groups(uid, gid),
        env=dict(env) if env is not None else None,
        input=input,
        text=True,
        check=False,
        timeout=timeout,
    )
