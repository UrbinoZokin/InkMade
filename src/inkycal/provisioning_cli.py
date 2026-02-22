from __future__ import annotations

import argparse
import json

from .provisioning import ProvisioningService, parse_payload


def main() -> None:
    ap = argparse.ArgumentParser(description="InkyCal provisioning bridge for mobile app transport layers")
    sub = ap.add_subparsers(dest="command", required=True)

    sub.add_parser("status")

    wifi = sub.add_parser("set-wifi")
    wifi.add_argument("--ssid", required=True)
    wifi.add_argument("--password", default="")

    icloud = sub.add_parser("set-icloud")
    icloud.add_argument("--username", required=True)
    icloud.add_argument("--app-password", required=True)

    google = sub.add_parser("set-google-paths")
    google.add_argument("--credentials-json")
    google.add_argument("--token-json")

    settings = sub.add_parser("update-settings")
    settings.add_argument("--payload", required=True, help="JSON object payload")

    apply_cmd = sub.add_parser("apply")
    apply_cmd.add_argument("--no-restart", action="store_true")

    args = ap.parse_args()
    service = ProvisioningService()

    if args.command == "status":
        print(json.dumps(service.get_status(), indent=2))
        return

    if args.command == "set-wifi":
        print(json.dumps(service.set_wifi(args.ssid, args.password), indent=2))
        return

    if args.command == "set-icloud":
        service.set_icloud_credentials(args.username, args.app_password)
        print(json.dumps({"ok": True}, indent=2))
        return

    if args.command == "set-google-paths":
        service.set_google_oauth_paths(credentials_json=args.credentials_json, token_json=args.token_json)
        print(json.dumps({"ok": True}, indent=2))
        return

    if args.command == "update-settings":
        service.update_settings(parse_payload(args.payload))
        print(json.dumps({"ok": True}, indent=2))
        return

    if args.command == "apply":
        print(json.dumps(service.apply(restart_service=not args.no_restart), indent=2))
        return


if __name__ == "__main__":
    main()
