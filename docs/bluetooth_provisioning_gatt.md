# Bluetooth Provisioning GATT Contract

This document defines a minimal BLE contract for provisioning InkyCal devices from a mobile app.

## Service

- **Service name:** InkyCal Provisioning
- **Service UUID:** `9c5f0001-3f13-4f61-9c2f-4e0d7a76d001`
- **Transport:** BLE GATT, paired + bonded, encrypted characteristic access.

## Characteristics

| Name | UUID | Properties | Payload |
|---|---|---|---|
| Device Info | `9c5f1001-3f13-4f61-9c2f-4e0d7a76d001` | Read | JSON: model, serial, firmware |
| Setup State | `9c5f1002-3f13-4f61-9c2f-4e0d7a76d001` | Read + Notify | JSON: wizard state and message |
| Wi-Fi Config | `9c5f1003-3f13-4f61-9c2f-4e0d7a76d001` | Write | JSON: ssid/password/country |
| Wi-Fi Status | `9c5f1004-3f13-4f61-9c2f-4e0d7a76d001` | Read + Notify | JSON: connected/ip/error |
| Google OAuth URL | `9c5f1005-3f13-4f61-9c2f-4e0d7a76d001` | Read | JSON: url/state/code_challenge |
| Google OAuth Code | `9c5f1006-3f13-4f61-9c2f-4e0d7a76d001` | Write | JSON: code/state/redirect_uri |
| iCloud Config | `9c5f1007-3f13-4f61-9c2f-4e0d7a76d001` | Write | JSON: username/app_password |
| Settings | `9c5f1008-3f13-4f61-9c2f-4e0d7a76d001` | Read + Write | JSON: timezone/sleep/rotation/refresh |
| Apply + Restart | `9c5f1009-3f13-4f61-9c2f-4e0d7a76d001` | Write | JSON: action=apply |

## State values

Setup state value (`Setup State` characteristic):

- `idle`
- `awaiting_wifi`
- `wifi_connecting`
- `wifi_connected`
- `oauth_pending`
- `icloud_pending`
- `settings_pending`
- `applying_changes`
- `done`
- `error`

## Payload examples

### Device info (read)

```json
{
  "model": "Raspberry Pi Zero 2 W",
  "serial": "INKY-001122",
  "firmware": "inkycal-0.1.0"
}
```

### Wi-Fi config (write)

```json
{
  "ssid": "MyNetwork",
  "password": "correct horse battery staple",
  "country": "US"
}
```

### OAuth URL (read)

```json
{
  "url": "https://accounts.google.com/o/oauth2/v2/auth?...",
  "state": "gX2...",
  "code_challenge": "f9A..."
}
```

### Settings (write)

```json
{
  "timezone": "America/New_York",
  "sleep_start": "22:00",
  "sleep_end": "06:00",
  "portrait_rotation": 270,
  "refresh_minutes": 15,
  "deep_clean_day": "Sunday",
  "deep_clean_time": "03:00"
}
```

## Security requirements

- Enforce BLE pairing + bonding before write access.
- Show one-time pairing code on e-ink and require user confirmation.
- Reject stale OAuth `state` values.
- Treat all incoming BLE JSON as untrusted input (strict validation + bounds checks).
- Persist secrets with mode `0600` under `/opt/inkycal`.
