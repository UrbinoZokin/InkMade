"""The provisioning HTTP API, served for real on localhost.

Nothing secret crosses the network in the clear: /pair runs the key exchange
keyed by the setup code, and the token, the WiFi settings and the replies
travel sealed. Every POST also has to be JSON, which keeps web pages out --
a page can send a plain-text POST to any address without asking, but not an
application/json one.
"""
import base64
import json

import pytest
import requests

pytest.importorskip("spake2")

from inkycal.provisioning import httpserver, setupcrypto, wifi  # noqa: E402
from inkycal.provisioning.session import SetupSession  # noqa: E402

CODE = "482913"

# Straight to localhost: a proxy configured in the environment would otherwise
# be asked to fetch these.
http = requests.Session()
http.trust_env = False

TOKEN = {
    "token": "ya29.short-lived",
    "refresh_token": "1//long-lived-refresh",
    "client_id": "abc.apps.googleusercontent.com",
    "client_secret": "secret",
}


@pytest.fixture
def token_path(tmp_path, monkeypatch):
    path = tmp_path / "secrets" / "google_token.json"
    monkeypatch.setenv("GOOGLE_TOKEN_JSON", str(path))
    return path


@pytest.fixture
def api(token_path, monkeypatch):
    """A running server for one session. Yields (base_url, session)."""
    monkeypatch.setattr(
        wifi, "status", lambda: {"connected": True, "ssid": "Home", "ip": "192.168.1.50", "hostname": "inkycal"}
    )
    session = SetupSession(CODE, max_wrong=5)
    httpd = httpserver.serve(session, port=0, host="127.0.0.1")
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}", session
    finally:
        httpd.shutdown()
        httpd.server_close()


def _b64(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


def _pair(base_url, code=CODE):
    app = setupcrypto.AppHandshake(code)
    resp = http.post(f"{base_url}/pair", json={"message": _b64(app.message)}, timeout=10)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    return data["pairing"], app.finish(base64.b64decode(data["message"]))


def _send(base_url, path, payload: bytes, purpose: bytes, code=CODE):
    pairing, channel = _pair(base_url, code)
    body = {"pairing": pairing, "sealed": _b64(channel.seal(payload, purpose))}
    return http.post(f"{base_url}{path}", json=body, timeout=10), channel


def _send_token(base_url, code=CODE, token=None):
    payload = json.dumps(TOKEN if token is None else token).encode("utf-8")
    return _send(base_url, "/google-token", payload, setupcrypto.GOOGLE_TOKEN, code)


def test_info_is_public(api):
    base_url, _session = api

    resp = http.get(f"{base_url}/info", timeout=10)

    assert resp.status_code == 200
    assert resp.json()["ip"] == "192.168.1.50"


def test_no_response_invites_other_websites_in(api):
    base_url, _session = api

    resp, _channel = _send_token(base_url)

    for response in (http.get(f"{base_url}/info", timeout=10), resp):
        assert "Access-Control-Allow-Origin" not in response.headers


def test_the_right_code_delivers_the_token_and_ends_setup_mode(api, token_path):
    base_url, session = api

    resp, channel = _send_token(base_url)

    assert resp.status_code == 200, resp.text
    assert set(resp.json()) == {"sealed"}, "the reply is sealed too"
    reply = json.loads(channel.open(base64.b64decode(resp.json()["sealed"]), setupcrypto.GOOGLE_TOKEN_REPLY))
    assert reply == {"ok": True}
    assert json.loads(token_path.read_text(encoding="utf-8"))["refresh_token"] == TOKEN["refresh_token"]
    assert session.end_reason == "Google token delivered"


def test_a_wrong_code_is_refused_and_counted(api, token_path):
    base_url, session = api

    resp, _channel = _send_token(base_url, code="000000")

    assert resp.status_code == 401
    assert "4 tries left" in resp.json()["error"]
    assert not token_path.exists()
    assert session.wrong_codes_left == 4


def test_five_wrong_codes_end_setup_mode_for_good(api, token_path):
    base_url, session = api

    statuses = [_send_token(base_url, code=f"00000{i}")[0].status_code for i in range(5)]

    assert statuses == [401, 401, 401, 401, 403]
    assert session.ended
    late = http.post(
        f"{base_url}/pair", json={"message": _b64(setupcrypto.AppHandshake(CODE).message)}, timeout=10
    )
    assert late.status_code == 403
    assert "Hold down button C" in late.json()["error"]
    assert not token_path.exists()


def test_a_token_in_the_clear_gets_nowhere_even_with_the_code(api, token_path):
    """The way setup used to work -- the token as the body, the code in a
    header -- must not still be open as a way around the encryption."""
    base_url, session = api

    resp = http.post(
        f"{base_url}/google-token", json=TOKEN, headers={"X-Pairing-Token": CODE}, timeout=10
    )

    assert resp.status_code == 400
    assert not token_path.exists()
    assert session.wrong_codes_left == 5


@pytest.mark.parametrize("path", ["/pair", "/google-token", "/wifi"])
@pytest.mark.parametrize("content_type", ["text/plain", "application/x-www-form-urlencoded", ""])
def test_only_json_is_accepted(api, token_path, path, content_type):
    """The POSTs a web page can send without the browser asking first."""
    base_url, session = api

    resp = http.post(
        f"{base_url}{path}", data=json.dumps({"message": "x"}), headers={"Content-Type": content_type}, timeout=10
    )

    assert resp.status_code == 415
    assert session.wrong_codes_left == 5


def test_a_malformed_key_exchange_is_refused_without_counting(api):
    base_url, session = api

    for body in ({"message": _b64(b"not a key exchange")}, {"message": "not base64!"}, {}):
        assert http.post(f"{base_url}/pair", json=body, timeout=10).status_code == 400

    assert session.wrong_codes_left == 5


def test_a_bad_token_is_rejected_without_ending_setup_mode(api, token_path):
    base_url, session = api

    resp, _channel = _send_token(base_url, token={"token": "no refresh token"})

    assert resp.status_code == 400
    assert not token_path.exists()
    assert not session.ended


def test_wifi_settings_travel_sealed_both_ways(api, monkeypatch):
    base_url, _session = api
    joined = []
    monkeypatch.setattr(wifi, "configure_wifi", lambda ssid, psk: joined.append((ssid, psk)) or (True, "ok"))

    resp, channel = _send(
        base_url, "/wifi", json.dumps({"ssid": "Home", "psk": "hunter22"}).encode(), setupcrypto.WIFI
    )

    assert resp.status_code == 200, resp.text
    reply = json.loads(channel.open(base64.b64decode(resp.json()["sealed"]), setupcrypto.WIFI_REPLY))
    assert reply["ok"] is True
    assert joined == [("Home", "hunter22")]


def test_wifi_with_a_wrong_code_changes_nothing(api, monkeypatch):
    base_url, session = api
    joined = []
    monkeypatch.setattr(wifi, "configure_wifi", lambda ssid, psk: joined.append((ssid, psk)) or (True, "ok"))

    resp, _channel = _send(
        base_url, "/wifi", json.dumps({"ssid": "Evil", "psk": "x"}).encode(), setupcrypto.WIFI, code="000000"
    )

    assert resp.status_code == 401
    assert joined == []
    assert session.wrong_codes_left == 4


def test_unknown_paths_are_not_found(api):
    base_url, _session = api

    assert http.post(f"{base_url}/nope", json={}, timeout=10).status_code == 404
    assert http.get(f"{base_url}/nope", timeout=10).status_code == 404
