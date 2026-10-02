"""Tiny HTTP provisioning API, served over WiFi/LAN while setup mode is on.

Endpoints
---------
GET  /info          -> JSON device descriptor (public; used for discovery)
POST /google-token  -> body is the Google token JSON; writes it, ends setup mode
POST /wifi          -> {"ssid": .., "psk": ..} configure WiFi over LAN too

Kept deliberately small (stdlib only) so the agent's only extra dependency
for the WiFi path is zeroconf.

Both POSTs have to carry the setup code shown on the panel (in the
CODE_HEADER header), and have to be JSON. The second rule is what keeps web
pages out: a page can only send another site a plain-text or form POST
without the browser first asking that site's permission -- which this server
never grants -- so requiring application/json means a page someone opens on
the same network can't reach these endpoints at all, code or no code.
"""
from __future__ import annotations

import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import wifi
from . import tokenstore
from .protocol import CODE_HEADER, HTTP_PORT
from .session import OK, SetupSession, refusal

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
        "requires_pairing": True,
    }


class _Server(ThreadingHTTPServer):
    session: SetupSession


class _Handler(BaseHTTPRequestHandler):
    server: _Server
    server_version = "InkyCalProvisioning/2.0"

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

    def _read_body(self) -> bytes:
        try:
            length = int(self.headers.get("Content-Length", 0) or 0)
        except ValueError:
            return b""
        if length <= 0 or length > MAX_BODY_BYTES:
            return b""
        return self.rfile.read(length)

    def _is_json(self) -> bool:
        content_type = self.headers.get("Content-Type", "")
        return content_type.split(";", 1)[0].strip().lower() == "application/json"

    def _authorized(self) -> bool:
        session = self.server.session
        verdict = session.check(self.headers.get(CODE_HEADER, ""))
        if verdict == OK:
            return True
        # 403 once the session can't be used any more, so the app can tell
        # "type it again" from "press C again".
        self._send_json(403 if session.ended else 401, {"error": refusal(verdict, session)})
        return False

    def do_GET(self) -> None:
        if self.path.rstrip("/") in ("/info", ""):
            self._send_json(200, info_payload())
        else:
            self._send_json(404, {"error": "not found"})

    def do_POST(self) -> None:
        handlers = {"/google-token": self._handle_token, "/wifi": self._handle_wifi}
        handler = handlers.get(self.path.rstrip("/"))
        if handler is None:
            self._send_json(404, {"error": "not found"})
            return
        if not self._is_json():
            self._send_json(415, {"error": "Send the request as JSON (Content-Type: application/json)."})
            return
        if not self._authorized():
            return
        handler()

    def _handle_token(self) -> None:
        body = self._read_body()
        if not body:
            self._send_json(400, {"error": "empty body"})
            return
        try:
            tokenstore.save_token(body)
        except ValueError as exc:
            self._send_json(400, {"error": str(exc)})
            return
        self._send_json(200, {"ok": True})
        # The token is what setup mode was for. Stop listening now rather than
        # at the deadline; the agent then repaints the calendar, which is the
        # first render to use the new token.
        self.server.session.finish("Google token delivered")

    def _handle_wifi(self) -> None:
        body = self._read_body()
        try:
            data = json.loads(body or b"{}")
        except json.JSONDecodeError:
            self._send_json(400, {"error": "invalid JSON"})
            return
        if not isinstance(data, dict):
            self._send_json(400, {"error": "expected a JSON object"})
            return
        ok, message = wifi.configure_wifi(data.get("ssid", ""), data.get("psk", ""))
        code = 200 if ok else 502
        self._send_json(code, {"ok": ok, "message": message, **wifi.status()})


def serve(session: SetupSession, port: int = HTTP_PORT, host: str = "0.0.0.0") -> ThreadingHTTPServer:
    """Start the HTTP server in a background thread and return it.

    It accepts changes only with `session`'s code; shut it down when the
    session ends.
    """
    httpd = _Server((host, port), _Handler)
    httpd.session = session
    thread = threading.Thread(target=httpd.serve_forever, name="inkycal-http", daemon=True)
    thread.start()
    print(f"[http] provisioning API listening on :{httpd.server_address[1]}")
    return httpd
