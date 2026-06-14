"""Tiny HTTP provisioning API served over WiFi/LAN.

Endpoints
---------
GET  /info          -> JSON device descriptor (always public; used for discovery)
POST /google-token  -> body is the Google token JSON; writes it and refreshes
POST /wifi          -> {"ssid": .., "psk": ..} configure WiFi over LAN too

Kept deliberately small (stdlib only) so the agent's only extra dependency
for the WiFi path is zeroconf. Intended for a trusted home LAN; an optional
pairing token (INKYCAL_PAIR_TOKEN) gates the write endpoints when set.
"""
from __future__ import annotations

import json
import os
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import wifi
from . import tokenstore
from .protocol import HTTP_PORT

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


def _pair_token() -> str:
    return os.environ.get("INKYCAL_PAIR_TOKEN", "").strip()


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
        "requires_pairing": bool(_pair_token()),
    }


class _Handler(BaseHTTPRequestHandler):
    server_version = "InkyCalProvisioning/1.0"

    def log_message(self, fmt: str, *args) -> None:  # quieter logs
        print("[http] " + (fmt % args))

    def _send_json(self, code: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self) -> bytes:
        length = int(self.headers.get("Content-Length", 0) or 0)
        if length <= 0 or length > MAX_BODY_BYTES:
            return b""
        return self.rfile.read(length)

    def _authorized(self) -> bool:
        token = _pair_token()
        if not token:
            return True
        return self.headers.get("X-Pairing-Token", "") == token

    def do_GET(self) -> None:
        if self.path.rstrip("/") in ("/info", ""):
            self._send_json(200, info_payload())
        else:
            self._send_json(404, {"error": "not found"})

    def do_POST(self) -> None:
        if not self._authorized():
            self._send_json(401, {"error": "invalid pairing token"})
            return

        path = self.path.rstrip("/")
        if path == "/google-token":
            self._handle_token()
        elif path == "/wifi":
            self._handle_wifi()
        else:
            self._send_json(404, {"error": "not found"})

    def _handle_token(self) -> None:
        body = self._read_body()
        if not body:
            self._send_json(400, {"error": "empty body"})
            return
        try:
            dest = tokenstore.save_token(body)
        except ValueError as exc:
            self._send_json(400, {"error": str(exc)})
            return
        refreshed = tokenstore.refresh_display()
        self._send_json(200, {"ok": True, "path": dest, "refreshed": refreshed})

    def _handle_wifi(self) -> None:
        body = self._read_body()
        try:
            data = json.loads(body or b"{}")
        except json.JSONDecodeError:
            self._send_json(400, {"error": "invalid JSON"})
            return
        ok, message = wifi.configure_wifi(data.get("ssid", ""), data.get("psk", ""))
        code = 200 if ok else 502
        self._send_json(code, {"ok": ok, "message": message, **wifi.status()})


def serve(port: int = HTTP_PORT) -> ThreadingHTTPServer:
    """Start the HTTP server in a background thread and return it."""
    httpd = ThreadingHTTPServer(("0.0.0.0", port), _Handler)
    thread = threading.Thread(target=httpd.serve_forever, name="inkycal-http", daemon=True)
    thread.start()
    print(f"[http] provisioning API listening on :{port}")
    return httpd
