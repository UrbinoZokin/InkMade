"""scripts/ota_update.sh, run the way the Pi runs it.

systemd starts the updater from inkycal-update.service, which has no User=
line, and systemd sets no $HOME for a unit like that (systemd.exec(5)). The
updater used to write root's global git config as its first step, which git
refuses without a $HOME, so every scheduled run died before it fetched
anything. Nothing on the panel showed it: an updater that dies and one waiting
for tonight's apply window both leave "Update pending" on screen.

So these run the real script against a throwaway checkout, with $HOME unset
and systemctl stubbed out.
"""
from __future__ import annotations

import os
import pwd
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import pytest

REPO = Path(__file__).resolve().parent.parent
OTA_SH = REPO / "scripts" / "ota_update.sh"

pytestmark = pytest.mark.skipif(
    sys.platform != "linux", reason="ota_update.sh targets the Pi: bash, GNU stat, runuser"
)

# Records each call, and reports every service inactive so the updater skips
# its restarts. "start --no-block inkycal.service" in the log means it applied.
STUB_SYSTEMCTL = """#!/bin/sh
echo "$*" >> "$(dirname "$0")/systemctl.log"
[ "$1" = "is-active" ] && exit 3
exit 0
"""


def _run(*args: str, user: Optional[str] = None) -> str:
    if user is not None:
        args = ("runuser", "-u", user, "--", *args)
    return subprocess.run(args, check=True, capture_output=True, text=True).stdout.strip()


def _git(repo: Path, *args: str, user: Optional[str] = None) -> str:
    return _run("git", "-C", str(repo), *args, user=user)


@dataclass
class Device:
    root: Path
    origin: Path  # stands in for GitHub
    seed: Path    # where new commits are pushed from
    app: Path     # the checkout: /opt/inkycal on the Pi
    state: Path   # /var/lib/inkycal
    bin: Path     # holds the stub systemctl

    def push(self, text: str) -> str:
        """Push a new commit to "GitHub" and return its sha."""
        (self.seed / "marker.txt").write_text(text + "\n", encoding="utf-8")
        _git(self.seed, "commit", "-qam", text)
        _git(self.seed, "push", "-q", "origin", "main")
        return _git(self.seed, "rev-parse", "HEAD")

    def run_updater(self) -> subprocess.CompletedProcess:
        # What systemd hands inkycal-update.service: a PATH and little else. No HOME.
        env = {
            "PATH": f"{self.bin}{os.pathsep}{os.environ.get('PATH', '/usr/bin:/bin')}",
            "APP_DIR": str(self.app),
            "STATE_DIR": str(self.state),
        }
        return subprocess.run(
            ["bash", str(OTA_SH)], env=env, capture_output=True, text=True, timeout=120
        )

    def systemctl_calls(self) -> str:
        log = self.bin / "systemctl.log"
        return log.read_text(encoding="utf-8") if log.exists() else ""


def _make_device(root: Path) -> Device:
    dev = Device(
        root=root,
        origin=root / "origin.git",
        seed=root / "seed",
        app=root / "app",
        state=root / "state",
        bin=root / "bin",
    )
    _run("git", "init", "-q", "--bare", "--initial-branch=main", str(dev.origin))
    _run("git", "init", "-q", "--initial-branch=main", str(dev.seed))
    _git(dev.seed, "config", "user.email", "t@example.com")
    _git(dev.seed, "config", "user.name", "Tester")
    (dev.seed / "marker.txt").write_text("v1\n", encoding="utf-8")
    _git(dev.seed, "add", "-A")
    _git(dev.seed, "commit", "-qm", "v1")
    _git(dev.seed, "remote", "add", "origin", str(dev.origin))
    _git(dev.seed, "push", "-q", "origin", "main")
    _run("git", "clone", "-q", str(dev.origin), str(dev.app))

    dev.state.mkdir()
    dev.bin.mkdir()
    stub = dev.bin / "systemctl"
    stub.write_text(STUB_SYSTEMCTL, encoding="utf-8")
    stub.chmod(0o755)
    return dev


def _outside_the_apply_window(dev: Device) -> None:
    """Give the checkout a device config whose overnight window is hours away.

    The updater reads config.yaml with the venv's python, so point that at ours.
    """
    venv_bin = dev.app / "venv" / "bin"
    venv_bin.mkdir(parents=True)
    (venv_bin / "python").symlink_to(sys.executable)
    start = (datetime.now(timezone.utc).hour + 2) % 24
    (dev.app / "config.yaml").write_text(
        'timezone: "UTC"\n'
        f'sleep:\n  enabled: true\n  start: "{start:02d}:00"\n  end: "{start:02d}:30"\n'
        'auto_update:\n  enabled: true\n  branch: "main"\n  apply_window: "sleep"\n',
        encoding="utf-8",
    )


def _owned_by_root(top: Path, *, skip: tuple[str, ...] = ()) -> list[str]:
    """What under `top` (itself included) root owns, relative to `top`."""
    paths = [top]
    for dirpath, dirnames, filenames in os.walk(top):
        if Path(dirpath) == top:
            dirnames[:] = [d for d in dirnames if d not in skip]
        paths.extend(Path(dirpath, name) for name in dirnames + filenames)
    return sorted(str(p.relative_to(top)) for p in paths if p.lstat().st_uid == 0)


def test_applies_a_pending_update_without_home(tmp_path):
    """The run systemd actually makes has to get all the way through: fetch,
    reset, and the render that takes "Update pending" off the panel."""
    dev = _make_device(tmp_path)
    new = dev.push("v2")

    result = dev.run_updater()

    assert result.returncode == 0, result.stdout + result.stderr
    assert _git(dev.app, "rev-parse", "HEAD") == new
    assert "start --no-block inkycal.service" in dev.systemctl_calls(), (
        "applied the update but never asked for a render with the new code"
    )


@pytest.fixture
def device_owned_by_nobody():
    """A checkout owned by an ordinary user while the updater runs as root:
    the Pi's arrangement, where 'pi' owns /opt/inkycal."""
    if os.geteuid() != 0:
        pytest.skip("needs root: the updater drops from root to the checkout's owner")
    if shutil.which("runuser") is None:
        pytest.skip("needs runuser (util-linux)")
    try:
        pwd.getpwnam("nobody")
    except KeyError:
        pytest.skip("needs a 'nobody' user to own the checkout")

    # Not tmp_path: that sits under a directory only its creator may enter, and
    # the checkout's owner has to be able to reach the checkout.
    root = Path(tempfile.mkdtemp(prefix="inkycal-ota-"))
    try:
        root.chmod(0o755)
        if subprocess.run(["runuser", "-u", "nobody", "--", "test", "-x", str(root)]).returncode != 0:
            pytest.skip(f"'nobody' cannot reach {root}")
        yield _make_device(root)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_git_runs_as_the_checkout_owner(device_owned_by_nobody):
    """Root's git left root-owned files in .git whenever a daytime check found
    an update and deferred it, and the render -- running git as the owner --
    then couldn't fetch past them. Git now runs as the owner, and the updater
    first hands back anything root left there before (planted here: a
    root-owned .git/objects, which no fetch as the owner can write into)."""
    dev = device_owned_by_nobody
    new = dev.push("v2")
    _outside_the_apply_window(dev)
    _run("chown", "-R", "nobody:", str(dev.root))
    os.chown(dev.app / ".git" / "objects", 0, 0)

    deferred = dev.run_updater()

    assert deferred.returncode == 0, deferred.stdout + deferred.stderr
    assert "outside the apply window" in deferred.stdout, deferred.stdout + deferred.stderr
    assert _git(dev.app, "rev-parse", "origin/main", user="nobody") == new, "the check never fetched"
    assert _owned_by_root(dev.app / ".git") == []

    # What button D leaves: apply now rather than overnight.
    (dev.state / "force_update").touch()
    applied = dev.run_updater()

    assert applied.returncode == 0, applied.stdout + applied.stderr
    assert _git(dev.app, "rev-parse", "HEAD", user="nobody") == new
    assert _owned_by_root(dev.app, skip=("venv",)) == []
