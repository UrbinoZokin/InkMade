#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/opt/inkycal"
VENV="$APP_DIR/venv/bin/python"

# Load .env in a way that tolerates quotes and avoids systemd parsing quirks
if [ -f "$APP_DIR/.env" ]; then
  set -a
  # shellcheck disable=SC1090
  source "$APP_DIR/.env"
  set +a
fi

exec "$VENV" -m inkycal.main \
  --config "$APP_DIR/config.yaml" \
  --state "/var/lib/inkycal/state.json"
