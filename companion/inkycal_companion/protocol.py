"""InkyCal provisioning protocol constants (companion app side).

MUST stay in sync with src/inkycal/provisioning/protocol.py on the Pi.
Duplicated because the two halves ship to different machines, as is
setupcrypto.py.
"""
from __future__ import annotations

# --- WiFi / LAN transport ---
MDNS_SERVICE_TYPE = "_inkycal._tcp.local."
HTTP_PORT = 8338

# --- Bluetooth Low Energy transport ---
BLE_LOCAL_NAME = "InkyCal-Setup"

BLE_SERVICE_UUID = "f0a40000-3c5a-4b9e-9b7a-1e2d3c4b5a60"
BLE_CHAR_STATUS_UUID = "f0a40004-3c5a-4b9e-9b7a-1e2d3c4b5a60"
BLE_CHAR_INFO_UUID = "f0a40005-3c5a-4b9e-9b7a-1e2d3c4b5a60"
BLE_CHAR_PAIR_UUID = "f0a40007-3c5a-4b9e-9b7a-1e2d3c4b5a60"
BLE_CHAR_WIFI_UUID = "f0a40008-3c5a-4b9e-9b7a-1e2d3c4b5a60"
# Writes to PAIR and WIFI are framed with a 2-byte big-endian length.

STATUS_IDLE = "idle"
STATUS_CONNECTING = "connecting"
STATUS_CONNECTED = "connected"
STATUS_FAILED = "failed"

# The one-time setup code shown on the InkyCal's screen while setup mode is
# on (button C). It never leaves this computer: it keys the exchange in
# setupcrypto.py, and only a Pi showing the same code can open what's sent.
CODE_DIGITS = 6

# OAuth scopes the Pi's display program needs: read-only calendar access plus
# read-only Google Tasks (rendered as the "Reminders" region).
GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/tasks.readonly",
]
