"""The companion app's half of setup: the code, and the sealed traffic it keys.

The app ships to a laptop and the agent to the Pi, so their protocol constants
and setup crypto are duplicated rather than shared -- and a mismatch fails
only on a real device, as a code that's "wrong" whatever anyone types. So the
app is driven here against the Pi's real side: its HTTP server, and its half
of the key exchange behind a stand-in for the Bluetooth radio.
"""
import asyncio
import io
import json
import sys
import types
from pathlib import Path

import pytest

pytest.importorskip("spake2")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "companion"))

from inkycal.provisioning import httpserver, wifi  # noqa: E402
from inkycal.provisioning import protocol as pi_protocol  # noqa: E402
from inkycal.provisioning import setupcrypto as pi_crypto  # noqa: E402
from inkycal.provisioning.session import SetupSession  # noqa: E402
from inkycal_companion import ble_client, cli, pi_client, workflow  # noqa: E402
from inkycal_companion import protocol as app_protocol  # noqa: E402
from inkycal_companion.discovery import PiDevice  # noqa: E402

CODE = "482913"
TOKEN = {
    "token": "ya29.short-lived",
    "refresh_token": "1//long-lived-refresh",
    "client_id": "abc.apps.googleusercontent.com",
    "client_secret": "secret",
}


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


# --- over WiFi: the app's client against the Pi's server -------------------


@pytest.fixture
def pi(tmp_path, monkeypatch):
    """The Pi's real HTTP API on localhost. Yields (device, session, token_path)."""
    token_path = tmp_path / "secrets" / "google_token.json"
    monkeypatch.setenv("GOOGLE_TOKEN_JSON", str(token_path))
    monkeypatch.setattr(
        wifi, "status", lambda: {"connected": True, "ssid": "Home", "ip": "127.0.0.1", "hostname": "inkycal"}
    )
    # The app uses plain requests calls; keep a configured proxy out of the way.
    for var in ("HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy"):
        monkeypatch.delenv(var, raising=False)
    session = SetupSession(CODE, max_wrong=5)
    httpd = httpserver.serve(session, port=0, host="127.0.0.1")
    try:
        yield PiDevice(name="inkycal", host="127.0.0.1", port=httpd.server_address[1]), session, token_path
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_the_app_delivers_the_token_with_the_right_code(pi):
    device, session, token_path = pi

    reply = pi_client.PiClient(device, setup_code=CODE).upload_token(json.dumps(TOKEN))

    assert reply == {"ok": True}
    assert json.loads(token_path.read_text(encoding="utf-8"))["refresh_token"] == TOKEN["refresh_token"]
    assert session.end_reason == "Google token delivered"


def test_the_app_reports_a_wrong_code_and_delivers_nothing(pi):
    device, session, token_path = pi

    with pytest.raises(RuntimeError, match="wrong"):
        pi_client.PiClient(device, setup_code="000000").upload_token(json.dumps(TOKEN))

    assert not token_path.exists()
    assert session.wrong_codes_left == 4


def test_the_app_never_sends_the_code_or_the_token_in_the_clear(pi, monkeypatch):
    device, _session, _token_path = pi
    sent = []
    real_post = pi_client.requests.post

    def recording_post(url, **kw):
        sent.append(json.dumps(kw.get("json")))
        return real_post(url, **kw)

    monkeypatch.setattr(pi_client.requests, "post", recording_post)

    pi_client.PiClient(device, setup_code=CODE).upload_token(json.dumps(TOKEN))

    wire = " ".join(sent)
    assert CODE not in wire
    assert TOKEN["refresh_token"] not in wire
    assert TOKEN["client_secret"] not in wire


def test_the_app_refuses_an_inkycal_that_cant_encrypt(monkeypatch):
    """Falling back to the clear is exactly what an eavesdropper would ask for."""
    sent = []

    class _NotFound:
        status_code = 404
        text = "not found"

        def json(self):
            return {"error": "not found"}

    monkeypatch.setattr(pi_client.requests, "post", lambda url, **kw: sent.append(url) or _NotFound())
    client = pi_client.PiClient(PiDevice(name="inkycal", host="192.168.1.50", port=8338), setup_code=CODE)

    with pytest.raises(RuntimeError, match="too old"):
        client.upload_token(json.dumps(TOKEN))

    assert sent == ["http://192.168.1.50:8338/pair"], "nothing but the key exchange was sent"


# --- over Bluetooth: the app against the Pi's half of the exchange ----------


def _fake_bleak(monkeypatch, *, pi_code=CODE, pi_supports_pairing=True) -> dict:
    """A BleakClient whose Pi end runs the real key exchange and opens what it's sent."""
    pi_end = {"writes": [], "joined": []}

    def _unframe(data: bytes) -> bytes:
        size = int.from_bytes(data[:2], "big")
        assert len(data) == 2 + size, "the app frames every write with its length"
        return data[2:]

    class _Services:
        def get_characteristic(self, uuid):
            if pi_supports_pairing or uuid not in (app_protocol.BLE_CHAR_PAIR_UUID, app_protocol.BLE_CHAR_WIFI_UUID):
                return object()
            return None

    class _Client:
        def __init__(self, address, timeout=30.0):
            self.is_connected = True
            self.services = _Services()
            self._on_status = None
            self._answer = b""
            self._channel = None

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def write_gatt_char(self, uuid, data, response=None):
            data = bytes(data)
            pi_end["writes"].append((uuid, data))
            if uuid == app_protocol.BLE_CHAR_PAIR_UUID:
                self._answer, self._channel = pi_crypto.pi_handshake(pi_code, _unframe(data))
            elif uuid == app_protocol.BLE_CHAR_WIFI_UUID:
                try:
                    settings = json.loads(self._channel.open(_unframe(data), pi_crypto.WIFI))
                    pi_end["joined"].append((settings["ssid"], settings["psk"]))
                    status = {"state": "connected", "ip": "192.168.1.50"}
                except pi_crypto.BadSeal:
                    status = {"state": "failed", "message": "That setup code is wrong."}
                if self._on_status:
                    self._on_status(None, bytearray(json.dumps(status).encode("utf-8")))

        async def read_gatt_char(self, uuid):
            if uuid == app_protocol.BLE_CHAR_PAIR_UUID:
                return bytearray(self._answer)
            return bytearray(b"{}")

        async def start_notify(self, uuid, callback):
            self._on_status = callback

        async def stop_notify(self, uuid):
            pass

    module = types.ModuleType("bleak")
    module.BleakClient = _Client
    monkeypatch.setitem(sys.modules, "bleak", module)
    return pi_end


def test_bluetooth_sends_wifi_settings_the_pi_can_open(monkeypatch):
    pi_end = _fake_bleak(monkeypatch)

    status = asyncio.run(ble_client.provision_wifi("AA:BB", "Home", "hunter22", CODE))

    assert status["ip"] == "192.168.1.50"
    assert pi_end["joined"] == [("Home", "hunter22")]
    over_the_air = b"".join(data for _uuid, data in pi_end["writes"])
    assert b"hunter22" not in over_the_air
    assert CODE.encode() not in over_the_air


def test_bluetooth_with_a_wrong_code_reports_it(monkeypatch):
    pi_end = _fake_bleak(monkeypatch, pi_code="000000")

    with pytest.raises(ble_client.BleError, match="wrong"):
        asyncio.run(ble_client.provision_wifi("AA:BB", "Home", "hunter22", CODE))

    assert pi_end["joined"] == []


def test_bluetooth_refuses_an_inkycal_that_cant_encrypt(monkeypatch):
    pi_end = _fake_bleak(monkeypatch, pi_supports_pairing=False)

    with pytest.raises(ble_client.BleError, match="too old"):
        asyncio.run(ble_client.provision_wifi("AA:BB", "Home", "hunter22", CODE))

    assert pi_end["writes"] == [], "nothing was sent to it, least of all the passphrase"


# --- the command line --------------------------------------------------------


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
