"""BLE client used to provision WiFi on a fresh Pi over Bluetooth.

Built on ``bleak`` which is cross-platform (Windows/macOS/Linux), so the
same companion executable works on any laptop. All calls are async; the
workflow layer wraps them with ``asyncio.run`` for the GUI/CLI threads.
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import List, Optional

from .protocol import (
    BLE_LOCAL_NAME,
    BLE_SERVICE_UUID,
    BLE_CHAR_SSID_UUID,
    BLE_CHAR_PSK_UUID,
    BLE_CHAR_COMMAND_UUID,
    BLE_CHAR_STATUS_UUID,
    BLE_CHAR_INFO_UUID,
    CMD_CONNECT,
    STATUS_CONNECTED,
    STATUS_FAILED,
)


class BleError(RuntimeError):
    pass


@dataclass
class BleDevice:
    address: str
    name: str


async def scan(timeout: float = 8.0) -> List[BleDevice]:
    """Discover nearby InkyCal setup peripherals."""
    try:
        from bleak import BleakScanner
    except ImportError as exc:  # pragma: no cover
        raise BleError("Missing dependency bleak. Reinstall the app.") from exc

    results: dict[str, BleDevice] = {}

    devices = await BleakScanner.discover(timeout=timeout, return_adv=True)
    for address, (dev, adv) in devices.items():
        name = (adv.local_name or dev.name or "") if adv else (dev.name or "")
        service_uuids = [u.lower() for u in (adv.service_uuids if adv else [])]
        is_inkycal = (
            BLE_SERVICE_UUID.lower() in service_uuids
            or name == BLE_LOCAL_NAME
        )
        if is_inkycal:
            results[address] = BleDevice(address=address, name=name or BLE_LOCAL_NAME)
    return list(results.values())


async def provision_wifi(
    address: str,
    ssid: str,
    psk: str,
    connect_timeout: float = 60.0,
) -> dict:
    """Send WiFi credentials over BLE and wait for the Pi to join.

    Returns the final status dict reported by the Pi (includes its new IP).
    """
    try:
        from bleak import BleakClient
    except ImportError as exc:  # pragma: no cover
        raise BleError("Missing dependency bleak. Reinstall the app.") from exc

    async with BleakClient(address, timeout=30.0) as client:
        if not client.is_connected:
            raise BleError("Could not connect to the device over Bluetooth.")

        await client.write_gatt_char(BLE_CHAR_SSID_UUID, ssid.encode("utf-8"), response=True)
        await client.write_gatt_char(BLE_CHAR_PSK_UUID, psk.encode("utf-8"), response=True)

        # Subscribe to status notifications before issuing the connect command.
        final: dict = {}
        done = asyncio.Event()

        def _on_status(_handle, data: bytearray) -> None:
            nonlocal final
            try:
                parsed = json.loads(bytes(data).decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                return
            final = parsed
            if parsed.get("state") in (STATUS_CONNECTED, STATUS_FAILED):
                done.set()

        try:
            await client.start_notify(BLE_CHAR_STATUS_UUID, _on_status)
        except Exception:
            pass  # fall back to polling below

        await client.write_gatt_char(
            BLE_CHAR_COMMAND_UUID, CMD_CONNECT.encode("utf-8"), response=True
        )

        try:
            await asyncio.wait_for(done.wait(), timeout=connect_timeout)
        except asyncio.TimeoutError:
            # Notifications may be unsupported; poll the status characteristic.
            final = await _read_json(client, BLE_CHAR_STATUS_UUID)

        try:
            await client.stop_notify(BLE_CHAR_STATUS_UUID)
        except Exception:
            pass

        if final.get("state") == STATUS_FAILED:
            raise BleError(final.get("message") or "WiFi connection failed.")
        return final


async def read_info(address: str) -> dict:
    try:
        from bleak import BleakClient
    except ImportError as exc:  # pragma: no cover
        raise BleError("Missing dependency bleak. Reinstall the app.") from exc
    async with BleakClient(address, timeout=30.0) as client:
        return await _read_json(client, BLE_CHAR_INFO_UUID)


async def _read_json(client, char_uuid: str) -> dict:
    try:
        raw = await client.read_gatt_char(char_uuid)
        return json.loads(bytes(raw).decode("utf-8"))
    except Exception:
        return {}
