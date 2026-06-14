#!/usr/bin/env bash
set -euo pipefail

# Installs the InkyCal provisioning agent: BLE WiFi setup + Google token
# delivery over WiFi. Safe to run after scripts/install.sh.

APP_DIR="/opt/inkycal"
VENV_DIR="$APP_DIR/venv"

echo "== InkyCal provisioning agent install =="

if [ ! -d "$APP_DIR" ]; then
  echo "ERROR: Expected repo at $APP_DIR (run scripts/install.sh first)"
  exit 1
fi

# BlueZ + D-Bus/GLib bindings that bluezero needs at runtime. Installing the
# system packages avoids building dbus-python/PyGObject inside the venv.
echo "-- Installing Bluetooth + D-Bus system packages..."
sudo apt-get update
sudo apt-get install -y \
  bluetooth bluez \
  python3-dbus python3-gi \
  network-manager

# Let the venv use the system dbus/gi bindings.
if [ -d "$VENV_DIR" ]; then
  PYVER="$("$VENV_DIR/bin/python" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
  SITE_PACKAGES="$VENV_DIR/lib/python${PYVER}/site-packages"
  if [ -d "$SITE_PACKAGES" ] && [ ! -f "$SITE_PACKAGES/system-site.pth" ]; then
    echo "/usr/lib/python3/dist-packages" | sudo tee "$SITE_PACKAGES/system-site.pth" >/dev/null
    echo "✓ Exposed system dist-packages to the venv (for dbus/gi)"
  fi
fi

echo "-- Installing provisioning Python deps into venv..."
"$VENV_DIR/bin/pip" install -r "$APP_DIR/requirements-provisioning.txt"

echo "-- Making BlueZ advertise/peripheral capable..."
sudo systemctl enable --now bluetooth || true

echo "-- Installing systemd unit..."
sudo cp "$APP_DIR/systemd/inkycal-provisioning.service" /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now inkycal-provisioning.service

echo
echo "== Done =="
echo "The agent is now advertising over Bluetooth ('InkyCal-Setup') and,"
echo "once on WiFi, over mDNS (_inkycal._tcp)."
echo
echo "Check it:"
echo "  systemctl status inkycal-provisioning.service"
echo "  journalctl -u inkycal-provisioning.service -f"
