"""InkyCal provisioning protocol constants (companion app side).

MUST stay in sync with src/inkycal/provisioning/protocol.py on the Pi.
Duplicated because the two halves ship to different machines.
"""
from __future__ import annotations

# --- WiFi / LAN transport ---
MDNS_SERVICE_TYPE = "_inkycal._tcp.local."
HTTP_PORT = 8338

# --- Bluetooth Low Energy transport ---
BLE_LOCAL_NAME = "InkyCal-Setup"

BLE_SERVICE_UUID = "f0a40000-3c5a-4b9e-9b7a-1e2d3c4b5a60"
BLE_CHAR_SSID_UUID = "f0a40001-3c5a-4b9e-9b7a-1e2d3c4b5a60"
BLE_CHAR_PSK_UUID = "f0a40002-3c5a-4b9e-9b7a-1e2d3c4b5a60"
BLE_CHAR_COMMAND_UUID = "f0a40003-3c5a-4b9e-9b7a-1e2d3c4b5a60"
BLE_CHAR_STATUS_UUID = "f0a40004-3c5a-4b9e-9b7a-1e2d3c4b5a60"
BLE_CHAR_INFO_UUID = "f0a40005-3c5a-4b9e-9b7a-1e2d3c4b5a60"

CMD_CONNECT = "connect"

STATUS_IDLE = "idle"
STATUS_CONNECTING = "connecting"
STATUS_CONNECTED = "connected"
STATUS_FAILED = "failed"

# OAuth scope the Pi's display program needs (read-only calendar access).
GOOGLE_SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]
