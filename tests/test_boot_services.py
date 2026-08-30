"""What the Pi brings up on its own when it is powered on.

These are wiring checks, not behaviour checks: a unit that never gets enabled,
or a User= line the installer forgets to rewrite, fails silently on the device
and shows up only as a display that stopped updating. Cheap to assert here.
"""
import configparser
import os
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SYSTEMD_DIR = REPO / "systemd"
INSTALL_SH = REPO / "scripts" / "install.sh"
OTA_SH = REPO / "scripts" / "ota_update.sh"
PROVISIONING_SH = REPO / "scripts" / "install_provisioning.sh"

BOOT_UNIT = "inkycal-boot.service"
# Installed by scripts/install_provisioning.sh instead: it pulls in Bluetooth
# and NetworkManager packages, so it stays opt-in.
OPT_IN_UNITS = {"inkycal-provisioning.service"}


def _unit(name: str) -> configparser.ConfigParser:
    parser = configparser.ConfigParser(strict=False, allow_no_value=True)
    parser.optionxform = str  # systemd keys are case-sensitive
    parser.read(SYSTEMD_DIR / name, encoding="utf-8")
    return parser


def _unit_names():
    return sorted(p.name for p in SYSTEMD_DIR.iterdir() if p.suffix in (".service", ".timer"))


def _enable_lines(script: Path):
    """The `systemctl enable` invocations in a script, line continuations joined."""
    text = re.sub(r"\\\n\s*", " ", script.read_text(encoding="utf-8"))
    return [line for line in text.splitlines() if "systemctl enable" in line]


def _boot_started_unit(name: str) -> str:
    """The unit that has to be enabled for `name` to run at boot.

    A service with a sibling timer is started by that timer, so the timer is
    what carries the [Install] that matters.
    """
    timer = name.replace(".service", ".timer")
    if name.endswith(".service") and (SYSTEMD_DIR / timer).exists():
        return timer
    return name


@pytest.mark.parametrize("name", _unit_names())
def test_every_unit_is_enabled_by_an_installer(name):
    """Nothing ships that no installer ever turns on."""
    wanted = _boot_started_unit(name)
    script = PROVISIONING_SH if wanted in OPT_IN_UNITS else INSTALL_SH

    assert any(wanted in line for line in _enable_lines(script)), (
        f"{wanted} is never enabled by {script.name}, so it would not start on a fresh device"
    )


@pytest.mark.parametrize("name", _unit_names())
def test_every_unit_declares_how_it_gets_pulled_in(name):
    """`systemctl enable` needs an [Install] section to have anything to link."""
    unit = _unit(name)
    if _boot_started_unit(name) != name:
        return  # started by its timer, not by a target

    assert unit.has_section("Install"), f"{name} has no [Install]; enabling it is a no-op"
    assert unit.get("Install", "WantedBy", fallback=""), f"{name} has no WantedBy"


@pytest.mark.parametrize("script", [INSTALL_SH, OTA_SH], ids=lambda p: p.name)
@pytest.mark.parametrize("key", ["User", "Group"])
def test_units_running_as_the_app_user_get_rewritten(script, key):
    """install.sh and ota_update.sh repoint the display units at whoever owns
    the checkout. Group matters as much as User: since Bookworm the username is
    chosen at first boot, and a unit left on the packaged `pi` names a group
    that need not exist -- systemd then refuses to start it at all.
    """
    text = re.sub(r"\\\n\s*", " ", script.read_text(encoding="utf-8"))
    rewrite = [line for line in text.splitlines() if re.search(rf"sed .*\^{key}=", line)]
    assert rewrite, f"{script.name} no longer rewrites {key}= at all"
    rewritten = " ".join(rewrite)

    for name in _unit_names():
        if _unit(name).get("Service", key, fallback="") != "pi":
            continue
        assert name in rewritten, f"{script.name} does not rewrite {key}= in {name}"


def test_boot_unit_starts_at_power_on():
    unit = _unit(BOOT_UNIT)

    assert unit.get("Install", "WantedBy", fallback="") == "multi-user.target"
    assert unit.get("Service", "Type", fallback="") == "oneshot"


def test_boot_unit_waits_for_the_network_before_rendering():
    """The render fetches calendars, weather and travel times off the wire."""
    unit = _unit(BOOT_UNIT)

    assert "network-online.target" in unit.get("Unit", "Wants", fallback="")
    assert "network-online.target" in unit.get("Unit", "After", fallback="")


def test_boot_unit_runs_an_executable_script_that_exists():
    exec_start = _unit(BOOT_UNIT).get("Service", "ExecStart", fallback="")
    script = REPO / exec_start.replace("/opt/inkycal/", "").lstrip("/")

    assert script.is_file(), f"{BOOT_UNIT} points at {exec_start}, which is not in the repo"
    assert os.access(script, os.X_OK), f"{script.name} is not executable; systemd would refuse it"


def test_boot_unit_gives_the_render_longer_than_its_own_waits():
    """TimeoutStartSec has to cover both bounded waits plus a full repaint, or
    systemd kills the refresh part-drawn."""
    unit = _unit(BOOT_UNIT)
    timeout = int(unit.get("Service", "TimeoutStartSec"))
    script = (REPO / "scripts" / "boot_refresh.sh").read_text(encoding="utf-8")
    waits = [int(m) for m in re.findall(r"_WAIT_S:-(\d+)\}", script)]

    assert len(waits) == 2, "expected a bounded network wait and a bounded clock wait"
    assert timeout > sum(waits), f"TimeoutStartSec={timeout} leaves no room to render after {sum(waits)}s of waiting"


def test_boot_refresh_forces_the_repaint():
    """Without --force the render skips the panel when the schedule hash still
    matches -- which is exactly the stale screen this unit exists to clear."""
    script = (REPO / "scripts" / "boot_refresh.sh").read_text(encoding="utf-8")

    assert "-m inkycal.main" in script
    assert "--force" in script


def test_installer_triggers_a_refresh_through_the_boot_unit():
    """Install once and the panel paints; no manual first run needed."""
    text = INSTALL_SH.read_text(encoding="utf-8")

    assert re.search(rf"systemctl start .*{re.escape(BOOT_UNIT)}", text), (
        "install.sh should kick the same unit a power-on uses, so the install proves itself"
    )


def test_ota_arms_the_boot_unit_for_devices_that_never_rerun_install():
    """A device that gets this over the air must still boot-refresh next time."""
    assert any(BOOT_UNIT in line for line in _enable_lines(OTA_SH))
