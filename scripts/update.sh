#!/usr/bin/env bash
set -euo pipefail
APP_DIR="/opt/inkycal"
VENV_DIR="/opt/inkycal/venv"

cd "$APP_DIR"
"$VENV_DIR/bin/python" -m inkycal.main --config "$APP_DIR/config.yaml" --state "/var/lib/inkycal/state.json"
