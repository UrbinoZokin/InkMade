"""The companion app's half of the setup code.

The app ships to a laptop and the agent to the Pi, so their protocol constants
are duplicated rather than shared -- and a mismatch fails only on a real
device, as a code the Pi never receives.
"""
import asyncio
import io
import json
import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "companion"))

from inkycal.provisioning import protocol as pi_protocol  # noqa: E402
from inkycal_companion import ble_client, cli, pi_client, workflow  # noqa: E402
from inkycal_companion import protocol as app_protocol  # noqa: E402
from inkycal_companion.discovery import PiDevice  # noqa: E402


def test_the_app_and_the_pi_agree_on_the_protocol():
    for name in (n for n in dir(pi_protocol) if n.isupper()):
        assert getattr(app_protocol, name, None) == getattr(pi_protocol, name), name


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("482913", "482913"),
        ("482 913", "482913"),
        ("482-913", "482913"),
        (" 482913 ", "482913"),
        ("48291", None),
        ("4829134", None),
        ("48a913", None),
        ("", None),
        ("４８２９１３", None),
    ],
)
def test_codes_are_read_the_way_the_screen_shows_them(raw, expected):
    assert workflow.normalize_setup_code(raw) == expected


def test_the_code_rides_in_the_header_the_pi_reads(monkeypatch):
    sent = []

    class _Response:
        status_code = 200

        def json(self):
            return {"ok": True}

    monkeypatch.setattr(pi_client.requests, "post", lambda url, **kw: sent.append((url, kw)) or _Response())
    client = pi_client.PiClient(PiDevice(name="inkycal", host="192.168.1.50", port=8338), setup_code="482913")

    client.upload_token('{"refresh_token": "1//x"}')

    url, kw = sent[0]
    assert url == "http://192.168.1.50:8338/google-token"
    assert kw["headers"][pi_protocol.CODE_HEADER] == "482913"
    assert kw["headers"]["Content-Type"] == "application/json"


def _fake_bleak(monkeypatch, *, has_code_characteristic: bool) -> list:
    """A BleakClient for a Pi that reports it joined WiFi when told to connect."""
    writes = []

    class _Services:
        def get_characteristic(self, uuid):
            if has_code_characteristic and uuid == app_protocol.BLE_CHAR_CODE_UUID:
                return object()
            return None

    class _Client:
        def __init__(self, address, timeout=30.0):
            self.is_connected = True
            self.services = _Services()
            self._on_status = None

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def write_gatt_char(self, uuid, data, response=None):
            writes.append((uuid, bytes(data)))
            if uuid == app_protocol.BLE_CHAR_COMMAND_UUID and self._on_status:
                status = {"state": "connected", "ip": "192.168.1.50"}
                self._on_status(None, bytearray(json.dumps(status).encode("utf-8")))

        async def start_notify(self, uuid, callback):
            self._on_status = callback

        async def stop_notify(self, uuid):
            pass

        async def read_gatt_char(self, uuid):
            return bytearray(b"{}")

    module = types.ModuleType("bleak")
    module.BleakClient = _Client
    monkeypatch.setitem(sys.modules, "bleak", module)
    return writes


def test_bluetooth_sends_the_code_before_asking_the_pi_to_connect(monkeypatch):
    writes = _fake_bleak(monkeypatch, has_code_characteristic=True)

    status = asyncio.run(ble_client.provision_wifi("AA:BB", "Home", "hunter22", "482913"))

    uuids = [uuid for uuid, _data in writes]
    assert (app_protocol.BLE_CHAR_CODE_UUID, b"482913") in writes
    assert uuids.index(app_protocol.BLE_CHAR_CODE_UUID) < uuids.index(app_protocol.BLE_CHAR_COMMAND_UUID)
    assert status["ip"] == "192.168.1.50"


def test_bluetooth_skips_the_code_on_a_pi_from_before_setup_mode(monkeypatch):
    writes = _fake_bleak(monkeypatch, has_code_characteristic=False)

    asyncio.run(ble_client.provision_wifi("AA:BB", "Home", "hunter22", "482913"))

    assert app_protocol.BLE_CHAR_CODE_UUID not in [uuid for uuid, _data in writes]


def test_the_cli_takes_the_code_from_its_flag():
    assert cli._setup_code("482 913") == "482913"


def test_the_cli_rejects_a_mistyped_code(capsys):
    assert cli._setup_code("48291") is None
    assert "not a setup code" in capsys.readouterr().out


def test_the_cli_needs_the_flag_without_a_terminal_to_ask_on(monkeypatch, capsys):
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))

    assert cli._setup_code("") is None
    assert "button C" in capsys.readouterr().out


def test_the_cli_asks_for_the_code_when_run_by_hand(monkeypatch):
    class _Terminal(io.StringIO):
        def isatty(self):
            return True

    answers = iter(["oops", "482 913"])
    monkeypatch.setattr(sys, "stdin", _Terminal())
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(answers))

    assert cli._setup_code("") == "482913"


def test_the_cli_still_takes_the_old_pairing_token_flag(monkeypatch):
    uploaded = []
    monkeypatch.setattr(cli.workflow, "run_google_signin", lambda path, log: "{}")
    monkeypatch.setattr(
        cli.workflow, "upload_token", lambda device, token, code, log: uploaded.append((device.host, code))
    )

    assert cli.main(["--credentials", "client.json", "--host", "192.168.1.50", "--pairing-token", "482 913"]) == 0
    assert uploaded == [("192.168.1.50", "482913")]
