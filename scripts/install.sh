#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/opt/inkycal"
VENV_DIR="/opt/inkycal/venv"
STATE_DIR="/var/lib/inkycal"

sudo apt-get update

# OS deps (fonts, PIL deps, SPI/I2C tooling)
sudo apt-get install -y \
  python3 python3-venv python3-pip \
  git \
  fonts-dejavu-core \
  libjpeg-dev zlib1g-dev libfreetype6-dev \
  i2c-tools

sudo mkdir -p "$APP_DIR" "$STATE_DIR" "$APP_DIR/secrets"
sudo chown -R "$USER":"$USER" "$APP_DIR"
sudo chown -R "$USER":"$USER" "$STATE_DIR"

# Create venv to avoid "externally-managed-environment" issues
python3 -m venv "$VENV_DIR"
"$VENV_DIR/bin/python" -m pip install --upgrade pip wheel setuptools

# Install python deps
"$VENV_DIR/bin/pip" install -r "$APP_DIR/requirements.txt"

echo "Install complete."
echo "Next:"
echo "  1) Copy config.yaml.example -> /opt/inkycal/config.yaml"
echo "  2) Copy .env.example -> /opt/inkycal/.env and fill in secrets"
echo "  3) Place Google credentials JSON in /opt/inkycal/secrets/"
echo "  4) Install + enable systemd units from ./systemd/"
