# Flutter Setup Wizard Flow

This is the recommended setup flow for an iOS-focused Flutter app that provisions InkyCal over BLE.

## Screens

1. **Scan**
   - Scan BLE advertisements for InkyCal provisioning service UUID.
2. **Pair**
   - Connect and confirm one-time code shown on e-ink display.
3. **Wi-Fi**
   - Enter SSID/password and submit to `Wi-Fi Config` characteristic.
4. **Google auth**
   - Read OAuth URL from `Google OAuth URL`, open browser, collect callback code, write to `Google OAuth Code`.
5. **iCloud**
   - Enter Apple ID + app-specific password and write to `iCloud Config`.
6. **Display & schedule settings**
   - Configure timezone, sleep window, rotation, refresh interval, deep-clean schedule and write to `Settings`.
7. **Apply**
   - Write apply command to `Apply + Restart`.
8. **Done**
   - Show IP address and completion status from `Setup State`/`Wi-Fi Status` notifications.

## State machine

A lightweight Dart state machine is included at:

- `examples/flutter/setup_wizard_state_machine.dart`

## Flutter package recommendations

- BLE: `flutter_reactive_ble`
- OAuth helper: `flutter_appauth`
- Browser/deep-link fallback: `url_launcher` + app links

## iOS distribution note

You can write Flutter code from Linux/Windows, but App Store builds/signing require macOS tooling (local Mac, rented Mac, or cloud CI macOS runner).
