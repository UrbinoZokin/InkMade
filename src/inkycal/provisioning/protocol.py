"""Shared constants for the InkyCal provisioning protocol.

The companion app (companion/inkycal_companion/protocol.py) MUST keep the
UUIDs, service type and port below in sync with this file. They are
duplicated rather than imported because the two halves are deployed to
different machines (Pi vs laptop).
"""
from __future__ import annotations

# --- WiFi / LAN transport (used once the Pi is online) ---
# mDNS / Zeroconf service type the agent advertises and the app browses for.
MDNS_SERVICE_TYPE = "_inkycal._tcp.local."
# TCP port the on-device HTTP provisioning API listens on.
HTTP_PORT = 8338

# --- Bluetooth Low Energy transport (used for first-time WiFi setup) ---
# Local name the BLE peripheral advertises with.
BLE_LOCAL_NAME = "InkyCal-Setup"

# Custom 128-bit GATT UUIDs for the provisioning service.
BLE_SERVICE_UUID = "f0a40000-3c5a-4b9e-9b7a-1e2d3c4b5a60"
BLE_CHAR_SSID_UUID = "f0a40001-3c5a-4b9e-9b7a-1e2d3c4b5a60"   # write
BLE_CHAR_PSK_UUID = "f0a40002-3c5a-4b9e-9b7a-1e2d3c4b5a60"    # write
BLE_CHAR_COMMAND_UUID = "f0a40003-3c5a-4b9e-9b7a-1e2d3c4b5a60"  # write ("connect")
BLE_CHAR_STATUS_UUID = "f0a40004-3c5a-4b9e-9b7a-1e2d3c4b5a60"   # read / notify (JSON)
BLE_CHAR_INFO_UUID = "f0a40005-3c5a-4b9e-9b7a-1e2d3c4b5a60"     # read (JSON)

# Command tokens written to the command characteristic.
CMD_CONNECT = "connect"

# Provisioning status values (reported over both BLE status char and HTTP).
STATUS_IDLE = "idle"
STATUS_CONNECTING = "connecting"
STATUS_CONNECTED = "connected"
STATUS_FAILED = "failed"
