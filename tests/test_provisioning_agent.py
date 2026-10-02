"""The provisioning agent's life: when setup mode starts, what it opens, how it ends.

Outside a session the agent must not be listening at all, and however a
session ends, the panel has to be handed back to the calendar. The transports
are stood in for, so these check the order of things rather than the radios.
"""
import json
import os
import threading
import time
from types import SimpleNamespace

import pytest

pytest.importorskip("spake2")

from inkycal import setupmode  # noqa: E402
from inkycal.provisioning import agent, setupcrypto, wifi  # noqa: E402
from inkycal.provisioning.ble import BleProvisioner  # noqa: E402
from inkycal.provisioning.protocol import STATUS_CONNECTED, STATUS_FAILED  # noqa: E402
from inkycal.provisioning.session import SetupSession  # noqa: E402


@pytest.fixture(autouse=True)
def run_dir(tmp_path, monkeypatch):
    run = tmp_path / "run"
    monkeypatch.setattr(setupmode, "MARKER_PATH", str(run / "setup-mode.json"))
    monkeypatch.setattr(setupmode, "REQUEST_PATH", str(run / "setup-requested"))
    return run


def _online():
    return {"connected": True, "ssid": "Home", "ip": "192.168.1.50", "hostname": "inkycal"}


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def transports(monkeypatch):
    """Everything a session starts, replaced by recorders."""
    t = SimpleNamespace(events=[], servers=[], mdns_ips=[], screens=[], marker_at_restore=None)

    class FakeServer:
        closed = False

        def shutdown(self):
            t.events.append("http-stop")

        def server_close(self):
            self.closed = True

    def fake_serve(session, port):
        t.events.append("http-start")
        t.servers.append(FakeServer())
        return t.servers[-1]

    class FakeBle:
        def __init__(self, info_provider, session):
            pass

        def start(self):
            t.events.append("ble-start")
            return True

    class FakeMdns:
        def __init__(self, port, device_id):
            pass

        def start(self, ip):
            t.mdns_ips.append(ip)
            return True

        def stop(self):
            t.events.append("mdns-stop")

    def show_code(session, address):
        t.screens.append((session.code, address, setupmode.is_active()))

    def restore():
        t.events.append("restore")
        t.marker_at_restore = os.path.exists(setupmode.MARKER_PATH)
        return True

    monkeypatch.setattr(agent, "serve", fake_serve)
    monkeypatch.setattr(agent, "BleProvisioner", FakeBle)
    monkeypatch.setattr(agent, "MdnsAdvertiser", FakeMdns)
    monkeypatch.setattr(agent, "_device_id", lambda: "abc123")
    monkeypatch.setattr(agent, "_show_code", show_code)
    monkeypatch.setattr(agent, "_restore_calendar", restore)
    monkeypatch.setattr(agent.wifi, "status", _online)
    monkeypatch.setattr(agent, "POLL_S", 0.01)
    return t


def _wait(condition, timeout=5.0):
    deadline = time.monotonic() + timeout
    while not condition():
        assert time.monotonic() < deadline, "timed out waiting"
        time.sleep(0.01)


# --- a session from start to finish ---------------------------------------


def test_a_session_runs_to_its_deadline_then_puts_the_calendar_back(transports):
    session = SetupSession("482913", seconds=0.3)

    agent.serve_session(session, "button C", threading.Event())

    assert session.end_reason == "timed out"
    # The panel was held before the code went up on it...
    assert transports.screens == [("482913", "192.168.1.50", True)]
    assert transports.mdns_ips == ["192.168.1.50"]
    # ...and everything was closed, and the panel let go, before the calendar
    # was asked back: a repaint finding the marker would be turned away.
    assert transports.events[-1] == "restore"
    assert {"http-stop", "mdns-stop"} <= set(transports.events[:-1])
    assert transports.marker_at_restore is False
    assert transports.servers[0].closed
    assert setupmode.is_active() is False


def test_delivering_the_token_ends_the_session_at_once(transports):
    session = SetupSession("482913", seconds=600)
    threading.Timer(0.05, session.finish, args=("Google token delivered",)).start()
    started = time.monotonic()

    agent.serve_session(session, "no Google token yet", threading.Event())

    assert time.monotonic() - started < 5
    assert transports.events.count("restore") == 1


def test_stopping_the_agent_ends_the_session_and_restores_the_calendar(transports):
    """How buttons A, B and D end setup mode: systemctl stop, i.e. SIGTERM."""
    session = SetupSession("482913", seconds=600)
    stop = threading.Event()
    threading.Timer(0.05, stop.set).start()

    agent.serve_session(session, "button C", stop)

    assert transports.events.count("restore") == 1
    assert setupmode.is_active() is False


def test_button_c_during_a_session_restarts_its_clock(transports):
    clock = _Clock()
    session = SetupSession("482913", seconds=600, clock=clock)
    stop = threading.Event()

    def press_c_near_the_end():
        _wait(lambda: os.path.exists(setupmode.MARKER_PATH))
        clock.now += 500
        setupmode.request()
        _wait(lambda: not setupmode.request_pending())
        stop.set()

    threading.Thread(target=press_c_near_the_end).start()
    agent.serve_session(session, "button C", stop)

    assert session.seconds_left() == 600


def test_a_busy_port_leaves_bluetooth_to_carry_the_session(transports, monkeypatch):
    def port_taken(session, port):
        raise OSError(98, "Address already in use")

    monkeypatch.setattr(agent, "serve", port_taken)

    agent.serve_session(SetupSession("482913", seconds=0.1), "button C", threading.Event())

    assert "ble-start" in transports.events
    assert transports.events[-1] == "restore"


# --- whether a session starts at all --------------------------------------


@pytest.fixture
def served(monkeypatch):
    reasons = []
    monkeypatch.setattr(agent, "serve_session", lambda session, reason, stop: reasons.append(reason))
    return reasons


def test_a_set_up_device_stays_out_of_setup_mode(transports, served, monkeypatch):
    """Booted with its token and WiFi in place, the agent exits: nothing listens."""
    monkeypatch.setattr(agent, "setup_needed", lambda: None)

    assert agent.run(stop=threading.Event()) == 0

    assert served == []
    assert "restore" not in transports.events


def test_button_c_starts_a_session_on_a_set_up_device(transports, served, monkeypatch):
    monkeypatch.setattr(agent, "setup_needed", lambda: None)
    setupmode.request()

    agent.run(stop=threading.Event())

    assert served == ["button C"]
    assert setupmode.request_pending() is False


def test_a_device_that_still_needs_setting_up_starts_one_by_itself(transports, served, monkeypatch):
    monkeypatch.setattr(agent, "setup_needed", lambda: "no Google token yet")

    agent.run(stop=threading.Event())

    assert served == ["no Google token yet"]


def test_a_marker_left_by_a_dead_agent_hands_the_panel_back(transports, served, monkeypatch):
    """An agent killed mid-session left its marker, and its code on the panel."""
    monkeypatch.setattr(agent, "setup_needed", lambda: None)
    setupmode.mark_active(600)

    agent.run(stop=threading.Event())

    assert not os.path.exists(setupmode.MARKER_PATH)
    assert transports.events == ["restore"]


@pytest.fixture
def device(monkeypatch):
    state = SimpleNamespace(google=True, token=True, online=True, saved_wifi=True)
    monkeypatch.setattr(agent, "_google_enabled", lambda: state.google)
    monkeypatch.setattr(agent.tokenstore, "token_present", lambda: state.token)
    monkeypatch.setattr(
        agent.wifi,
        "status",
        lambda: {"connected": state.online, "ip": "192.168.1.50" if state.online else None, "ssid": None, "hostname": "h"},
    )
    monkeypatch.setattr(agent.wifi, "has_saved_wifi_connection", lambda: state.saved_wifi)
    return state


def test_a_set_up_device_needs_nothing(device):
    assert agent.setup_needed() is None


def test_no_google_token_needs_setting_up(device):
    device.token = False

    assert agent.setup_needed() == "no Google token yet"


def test_no_google_token_is_fine_when_google_is_off(device):
    device.token = False
    device.google = False

    assert agent.setup_needed() is None


def test_no_wifi_network_needs_setting_up(device):
    device.online = False
    device.saved_wifi = False

    assert agent.setup_needed() == "no WiFi network set up yet"


def test_a_saved_network_that_is_down_is_not_a_reason(device):
    """After a power cut the Pi usually boots faster than the router. That
    must not put a setup code up on every such boot; a changed WiFi password
    is what button C is for."""
    device.online = False

    assert agent.setup_needed() is None


def test_google_counts_as_enabled_unless_the_config_says_otherwise(tmp_path, monkeypatch):
    monkeypatch.setattr(agent, "CONFIG_PATH", str(tmp_path / "missing.yaml"))
    assert agent._google_enabled() is True

    config = tmp_path / "config.yaml"
    config.write_text("timezone: 'UTC'\ncalendars:\n  google:\n    enabled: false\n", encoding="utf-8")
    monkeypatch.setattr(agent, "CONFIG_PATH", str(config))
    assert agent._google_enabled() is False


# --- handing the code to the panel, and the calendar back -----------------


def test_the_setup_screen_gets_the_code_on_stdin_and_none_of_the_secrets(monkeypatch):
    monkeypatch.setenv("ICLOUD_APP_PASSWORD", "abcd-efgh-ijkl-mnop")
    monkeypatch.setenv("GOOGLE_TOKEN_JSON", "/opt/inkycal/secrets/google_token.json")
    monkeypatch.setenv("INKYCAL_DISPLAY_LOCK", "/tmp/display.lock")
    calls = []
    monkeypatch.setattr(
        agent.appuser,
        "run_module",
        lambda app_dir, module, args, **kw: calls.append((module, list(args), kw)) or SimpleNamespace(returncode=0),
    )

    agent._show_code(SetupSession("482913"), "192.168.1.50")

    module, args, kw = calls[0]
    assert module == "inkycal.setupscreen"
    assert "482913" not in " ".join(args), "arguments show up in the process list"
    assert kw["input"] == "482913\n"
    assert args[args.index("--address") + 1] == "192.168.1.50"
    assert "ICLOUD_APP_PASSWORD" not in kw["env"]
    assert "GOOGLE_TOKEN_JSON" not in kw["env"]
    assert kw["env"]["INKYCAL_DISPLAY_LOCK"] == "/tmp/display.lock"


def test_restoring_prefers_the_repaint_that_ignores_the_sleep_window(monkeypatch):
    calls = []

    def systemctl(cmd, **_kw):
        calls.append(cmd)
        return SimpleNamespace(returncode=0 if cmd[-1] == "inkycal.service" else 5, stdout="", stderr="")

    monkeypatch.setattr(agent.subprocess, "run", systemctl)

    assert agent._restore_calendar() is True
    assert [cmd[-1] for cmd in calls] == ["inkycal-boot.service", "inkycal.service"]
    assert all("--no-block" in cmd for cmd in calls)


# --- Bluetooth: WiFi settings travel sealed --------------------------------


@pytest.fixture
def provisioner(monkeypatch):
    joined = []
    monkeypatch.setattr(wifi, "configure_wifi", lambda ssid, psk: joined.append((ssid, psk)) or (True, "Connected"))
    monkeypatch.setattr(wifi, "status", _online)
    session = SetupSession("482913", max_wrong=5)
    return BleProvisioner(info_provider=dict, session=session), session, joined


def _framed(payload: bytes) -> bytes:
    return len(payload).to_bytes(2, "big") + payload


def _write(callback, data: bytes, piece=None) -> None:
    """Hand `data` to a write callback whole -- or, as BlueZ hands over a long
    write, in pieces of `piece` bytes, each with its offset."""
    if piece is None:
        callback(list(data), {})
        return
    for offset in range(0, len(data), piece):
        callback(list(data[offset:offset + piece]), {"offset": offset})


def _pair(prov, code="482913", piece=None):
    app = setupcrypto.AppHandshake(code)
    _write(prov._on_write_pair, _framed(app.message), piece)
    return app.finish(bytes(prov._read_pair({})))


def _send_wifi(prov, channel, piece=None, ssid="Home", psk="hunter22") -> None:
    sealed = channel.seal(json.dumps({"ssid": ssid, "psk": psk}).encode("utf-8"), setupcrypto.WIFI)
    _write(prov._on_write_wifi, _framed(sealed), piece)


def _status(prov) -> dict:
    return json.loads(bytes(prov._read_status()).decode("utf-8"))


def test_ble_wifi_settings_sealed_with_the_code_are_applied(provisioner):
    prov, session, joined = provisioner

    _send_wifi(prov, _pair(prov))
    _wait(lambda: _status(prov)["state"] == STATUS_CONNECTED)

    assert joined == [("Home", "hunter22")]
    assert session.wrong_codes_left == 5


def test_ble_wifi_settings_under_a_wrong_code_are_refused_and_counted(provisioner):
    prov, session, joined = provisioner

    _send_wifi(prov, _pair(prov, code="000000"))

    assert _status(prov)["state"] == STATUS_FAILED
    assert "wrong" in _status(prov)["message"]
    assert joined == []
    assert session.wrong_codes_left == 4


def test_ble_wifi_settings_without_a_key_exchange_are_refused_uncounted(provisioner):
    prov, session, joined = provisioner
    elsewhere = setupcrypto.AppHandshake("482913")
    _answer, _pi_side = setupcrypto.pi_handshake("482913", elsewhere.message)
    channel = elsewhere.finish(_answer)

    _send_wifi(prov, channel)

    assert _status(prov)["state"] == STATUS_FAILED
    assert joined == []
    assert session.wrong_codes_left == 5


def test_ble_each_exchange_carries_one_message(provisioner):
    """A retry has to start a fresh exchange, so a recorded message can't be
    replayed over the old one."""
    prov, _session, joined = provisioner
    channel = _pair(prov)
    _send_wifi(prov, channel)
    _wait(lambda: _status(prov)["state"] == STATUS_CONNECTED)

    _send_wifi(prov, channel, ssid="Again")

    assert _status(prov)["state"] == STATUS_FAILED
    assert joined == [("Home", "hunter22")]


def test_ble_long_writes_arriving_in_pieces_are_put_back_together(provisioner):
    """A piece opened on its own would fail -- and count as a wrong code."""
    prov, session, joined = provisioner

    _send_wifi(prov, _pair(prov, piece=7), piece=7)
    _wait(lambda: _status(prov)["state"] == STATUS_CONNECTED)

    assert joined == [("Home", "hunter22")]
    assert session.wrong_codes_left == 5


def test_ble_reads_of_the_answer_honour_the_offset(provisioner):
    """BlueZ asks for the rest of a long value from an offset; bluezero hands
    the read callback that offset and returns whatever it gets back."""
    prov, _session, _joined = provisioner
    app = setupcrypto.AppHandshake("482913")
    _write(prov._on_write_pair, _framed(app.message))
    whole = bytes(prov._read_pair({}))

    assert bytes(prov._read_pair({"offset": 10})) == whole[10:]


def test_ble_a_malformed_key_exchange_is_refused_uncounted(provisioner):
    prov, session, _joined = provisioner

    _write(prov._on_write_pair, _framed(b"not a key exchange"))

    assert _status(prov)["state"] == STATUS_FAILED
    assert prov._read_pair({}) == []
    assert session.wrong_codes_left == 5


def test_ble_never_logs_a_secret(provisioner, capsys):
    prov, _session, _joined = provisioner

    _send_wifi(prov, _pair(prov))
    _wait(lambda: _status(prov)["state"] == STATUS_CONNECTED)

    out = capsys.readouterr().out
    assert "hunter22" not in out
    assert "482913" not in out


# --- spotting a device with no WiFi network --------------------------------


@pytest.mark.parametrize(
    "stdout, returncode, expected",
    [
        ("loopback\n802-11-wireless\n", 0, True),
        ("loopback\nwifi\n", 0, True),
        ("loopback\nethernet\n", 0, False),
        ("", 0, False),
        ("", 8, True),  # nmcli couldn't say: assume WiFi is managed elsewhere
    ],
)
def test_saved_wifi_networks_are_read_from_nmcli(monkeypatch, stdout, returncode, expected):
    monkeypatch.setattr(wifi, "_nmcli_available", lambda: True)
    monkeypatch.setattr(wifi, "_run", lambda cmd, timeout=45: SimpleNamespace(returncode=returncode, stdout=stdout))

    assert wifi.has_saved_wifi_connection() is expected


def test_without_nmcli_wifi_is_assumed_set_up(monkeypatch):
    monkeypatch.setattr(wifi, "_nmcli_available", lambda: False)

    assert wifi.has_saved_wifi_connection() is True
