"""Tiny HTTP provisioning API, served over WiFi/LAN while setup mode is on.

Endpoints
---------
GET  /info          -> JSON device descriptor (public; used for discovery)
POST /pair          -> {"message": ..} the app's half of the key exchange;
                       answers {"pairing": .., "message": ..}, the Pi's half
POST /google-token  -> {"pairing": .., "sealed": ..} the Google token JSON,
                       sealed; writes it, then ends setup mode
POST /wifi          -> {"pairing": .., "sealed": ..} {"ssid", "psk"}, sealed;
                       configure WiFi over LAN too

Binary fields are base64. Kept deliberately small (stdlib plus the setup
crypto) so the agent's only other extra dependency for the WiFi path is
zeroconf.

Nothing secret crosses the network in the clear, and the setup code doesn't
cross it at all: /pair runs a key exchange keyed by the code
(setupcrypto.py), and everything after it is sealed with the resulting key,
replies included. A message sealed with a key from the wrong code doesn't
open, and counts as a wrong code against the session.

Every POST also has to be JSON. That keeps web pages out: a page can only
send another site a plain-text or form POST without the browser first asking
that site's permission -- which this server never grants -- so a page opened
on the same network can't reach these endpoints at all.
"""
from __future__ import annotations

import base64
import binascii
import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional

from . import setupcrypto, tokenstore, wifi
from .protocol import HTTP_PORT
from .session import CLOSED, OK, SessionClosed, SetupSession, refusal

MAX_BODY_BYTES = 64 * 1024


def _device_id() -> str:
    """Stable-ish identifier derived from the machine-id / hostname."""
    for path in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
        try:
            with open(path, encoding="utf-8") as f:
                mid = f.read().strip()
                if mid:
                    return mid[:12]
        except OSError:
            continue
    return socket.gethostname()


def info_payload() -> dict:
    st = wifi.status()
    return {
        "device": "inkycal",
        "id": _device_id(),
        "hostname": st["hostname"],
        "wifi": "connected" if st["connected"] else "disconnected",
        "ssid": st["ssid"],
        "ip": st["ip"],
        "has_token": tokenstore.token_present(),
    }


def _b64(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


def _unb64(value) -> Optional[bytes]:
    if not isinstance(value, str):
        return None
    try:
        return base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError):
        return None


class _Server(ThreadingHTTPServer):
    session: SetupSession


class _Handler(BaseHTTPRequestHandler):
    server: _Server
    server_version = "InkyCalProvisioning/3.0"

    def log_message(self, fmt: str, *args) -> None:  # quieter logs
        print("[http] " + (fmt % args))

    def _send_json(self, code: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> Optional[dict]:
        try:
            length = int(self.headers.get("Content-Length", 0) or 0)
        except ValueError:
            return None
        if length <= 0 or length > MAX_BODY_BYTES:
            return None
        try:
            data = json.loads(self.rfile.read(length))
        except ValueError:
            return None
        return data if isinstance(data, dict) else None

    def _is_json(self) -> bool:
        content_type = self.headers.get("Content-Type", "")
        return content_type.split(";", 1)[0].strip().lower() == "application/json"

    def do_GET(self) -> None:
        if self.path.rstrip("/") in ("/info", ""):
            self._send_json(200, info_payload())
        else:
            self._send_json(404, {"error": "not found"})

    def do_POST(self) -> None:
        handlers = {
            "/pair": self._handle_pair,
            "/google-token": self._handle_token,
            "/wifi": self._handle_wifi,
        }
        handler = handlers.get(self.path.rstrip("/"))
        if handler is None:
            self._send_json(404, {"error": "not found"})
            return
        if not self._is_json():
            self._send_json(415, {"error": "Send the request as JSON (Content-Type: application/json)."})
            return
        data = self._read_json()
        if data is None:
            self._send_json(400, {"error": "expected a JSON object"})
            return
        handler(data)

    def _handle_pair(self, data: dict) -> None:
        session = self.server.session
        message = _unb64(data.get("message"))
        if message is None:
            self._send_json(400, {"error": "expected the app's key-exchange message"})
            return
        try:
            pairing, answer = session.pair(message)
        except setupcrypto.BadHandshake as exc:
            self._send_json(400, {"error": str(exc)})
            return
        except SessionClosed:
            self._send_json(403, {"error": refusal(CLOSED, session)})
            return
        self._send_json(200, {"pairing": pairing, "message": _b64(answer)})

    def _open(self, data: dict, purpose: bytes) -> Optional[tuple]:
        """The opened request as (plaintext, channel), or None once refused."""
        session = self.server.session
        sealed = _unb64(data.get("sealed"))
        if sealed is None:
            self._send_json(400, {"error": "expected a sealed message"})
            return None
        verdict, plaintext, channel = session.open(data.get("pairing"), sealed, purpose)
        if verdict != OK:
            # 403 once the session can't be used any more, so the app can tell
            # "type it again" from "hold C again".
            self._send_json(403 if session.ended else 401, {"error": refusal(verdict, session)})
            return None
        return plaintext, channel

    def _send_sealed(self, channel: setupcrypto.Channel, payload: dict, purpose: bytes) -> None:
        sealed = channel.seal(json.dumps(payload).encode("utf-8"), purpose)
        self._send_json(200, {"sealed": _b64(sealed)})

    def _handle_token(self, data: dict) -> None:
        opened = self._open(data, setupcrypto.GOOGLE_TOKEN)
        if opened is None:
            return
        plaintext, channel = opened
        try:
            tokenstore.save_token(plaintext)
        except ValueError as exc:
            self._send_json(400, {"error": str(exc)})
            return
        self._send_sealed(channel, {"ok": True}, setupcrypto.GOOGLE_TOKEN_REPLY)
        # The token is what setup mode was for. Stop listening now rather than
        # at the deadline; the agent then repaints the calendar, which is the
        # first render to use the new token.
        self.server.session.finish("Google token delivered")

    def _handle_wifi(self, data: dict) -> None:
        opened = self._open(data, setupcrypto.WIFI)
        if opened is None:
            return
        plaintext, channel = opened
        try:
            request = json.loads(plaintext)
        except ValueError:
            request = None
        if not isinstance(request, dict):
            self._send_json(400, {"error": "expected a JSON object"})
            return
        ok, message = wifi.configure_wifi(str(request.get("ssid", "")), str(request.get("psk", "")))
        self._send_sealed(channel, {"ok": ok, "message": message, **wifi.status()}, setupcrypto.WIFI_REPLY)


def serve(session: SetupSession, port: int = HTTP_PORT, host: str = "0.0.0.0") -> ThreadingHTTPServer:
    """Start the HTTP server in a background thread and return it.

    It accepts changes only from exchanges keyed by `session`'s code; shut it
    down when the session ends.
    """
    httpd = _Server((host, port), _Handler)
    httpd.session = session
    thread = threading.Thread(target=httpd.serve_forever, name="inkycal-http", daemon=True)
    thread.start()
    print(f"[http] provisioning API listening on :{httpd.server_address[1]}")
    return httpd
