"""Joining a WiFi network through nmcli, including when the scan can't say
what security the network uses."""
from types import SimpleNamespace

import pytest

from inkycal.provisioning import wifi

KEY_MGMT_MISSING = "Error: 802-11-wireless-security.key-mgmt: property is missing.\n"
WRONG_PASSWORD = "Error: Connection activation failed: Secrets were required, but not provided.\n"
UUID = "0f5c1a2e-7b3d-4c8e-9a61-2d4f8b7e3c10"
ADDED = f"Connection 'Home' ({UUID}) successfully added.\n"


@pytest.fixture
def nmcli(monkeypatch):
    """A stand-in nmcli: answers per action ("connect", "add", "up", "delete")
    from ``replies`` and records every command it was given."""
    fake = SimpleNamespace(replies={}, calls=[])

    def run(cmd, timeout=45):
        fake.calls.append(cmd)
        action = "connect" if "device" in cmd else cmd[cmd.index("connection") + 1]
        returncode, stdout, stderr = fake.replies.get(action, (0, "", ""))
        return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)

    fake.actions = lambda: ["connect" if "device" in c else c[c.index("connection") + 1] for c in fake.calls]
    monkeypatch.setattr(wifi, "_nmcli_available", lambda: True)
    monkeypatch.setattr(wifi, "_run", run)
    return fake


def test_a_network_that_joins_first_time_needs_nothing_more(nmcli):
    nmcli.replies["connect"] = (0, "Device 'wlan0' successfully activated.\n", "")

    assert wifi.configure_wifi("Home", "hunter22") == (True, "Device 'wlan0' successfully activated.")
    assert nmcli.actions() == ["connect"]


def test_a_network_the_scan_cant_describe_is_joined_as_wpa2(nmcli):
    nmcli.replies["connect"] = (4, "", KEY_MGMT_MISSING)
    nmcli.replies["add"] = (0, ADDED, "")
    nmcli.replies["up"] = (0, "Connection successfully activated.\n", "")

    ok, _message = wifi.configure_wifi("Home", "hunter22")

    assert ok
    assert nmcli.actions() == ["connect", "add", "up"]
    add = nmcli.calls[1]
    assert add[add.index("ssid") + 1] == "Home"
    assert add[add.index("wifi-sec.key-mgmt") + 1] == "wpa-psk"
    assert add[add.index("wifi-sec.psk") + 1] == "hunter22"
    assert nmcli.calls[2][-2:] == ["uuid", UUID]


def test_a_saved_network_that_wont_join_is_deleted_again(nmcli):
    # Left saved, it would count as WiFi being set up and the next boot would
    # skip setup mode, leaving no way to try again.
    nmcli.replies["connect"] = (4, "", KEY_MGMT_MISSING)
    nmcli.replies["add"] = (0, ADDED, "")
    nmcli.replies["up"] = (4, "", WRONG_PASSWORD)

    assert wifi.configure_wifi("Home", "hunter23") == (False, "Couldn't join Home. Check the WiFi password.")
    assert nmcli.actions() == ["connect", "add", "up", "delete"]
    assert nmcli.calls[3][-2:] == ["uuid", UUID]


def test_a_profile_nmcli_wont_save_is_reported_without_joining(nmcli):
    nmcli.replies["connect"] = (4, "", KEY_MGMT_MISSING)
    nmcli.replies["add"] = (2, "", "Error: 802-11-wireless-security.psk: property is invalid.\n")

    ok, message = wifi.configure_wifi("Home", "short")

    assert not ok
    assert message == "Error: 802-11-wireless-security.psk: property is invalid."
    assert nmcli.actions() == ["connect", "add"]


def test_an_open_network_is_never_given_a_password(nmcli):
    nmcli.replies["connect"] = (4, "", KEY_MGMT_MISSING)

    ok, _message = wifi.configure_wifi("Cafe", "")

    assert not ok
    assert nmcli.actions() == ["connect"]


def test_a_network_the_pi_cant_see_is_explained(nmcli):
    nmcli.replies["connect"] = (10, "", "Error: No network with SSID 'Home' found.\n")

    ok, message = wifi.configure_wifi("Home", "hunter22")

    assert not ok
    assert message.startswith("Can't see a network called Home.")
    assert nmcli.actions() == ["connect"]


def test_a_password_nmcli_echoes_is_never_passed_on_or_logged(nmcli, capsys):
    nmcli.replies["connect"] = (2, "", "Error: invalid passphrase 'hunter22' for 'Home'.\n")

    ok, message = wifi.configure_wifi("Home", "hunter22")

    assert not ok
    assert "hunter22" not in message
    logged = capsys.readouterr().out
    assert "hunter22" not in logged
    assert "Home" not in logged
