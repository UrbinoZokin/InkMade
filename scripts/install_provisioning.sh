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

# Bluetooth/D-Bus/GLib + zeroconf, all as prebuilt system packages. This is
# important on a Pi: installing zeroconf from PyPI tries to COMPILE its Cython
# C-extensions, which can hang or run out of RAM on a Pi Zero 2 W. The apt
# package ships a prebuilt binary, so we use that and expose it to the venv.
echo "-- Installing Bluetooth + D-Bus + zeroconf system packages..."
sudo apt-get update
sudo apt-get install -y \
  bluetooth bluez \
  python3-dbus python3-gi \
  python3-zeroconf \
  network-manager

# Let the venv use the system dbus/gi/zeroconf bindings (no compiling needed).
if [ -d "$VENV_DIR" ]; then
  PYVER="$("$VENV_DIR/bin/python" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
  SITE_PACKAGES="$VENV_DIR/lib/python${PYVER}/site-packages"
  if [ -d "$SITE_PACKAGES" ] && [ ! -f "$SITE_PACKAGES/system-site.pth" ]; then
    echo "/usr/lib/python3/dist-packages" | sudo tee "$SITE_PACKAGES/system-site.pth" >/dev/null
    echo "✓ Exposed system dist-packages to the venv (dbus/gi/zeroconf)"
  fi
fi

# Only bluezero needs pip, and it is pure Python (no compilation). --prefer-binary
# guards against any source builds creeping in.
echo "-- Installing bluezero into venv..."
"$VENV_DIR/bin/pip" install --prefer-binary bluezero

# Fail fast with a clear message if the agent's imports are not satisfied.
echo "-- Verifying provisioning imports..."
if ! "$VENV_DIR/bin/python" -c "import zeroconf, bluezero, dbus, gi" 2>/dev/null; then
  echo "✗ Provisioning imports failed. Check that python3-zeroconf/python3-dbus/"
  echo "  python3-gi installed and that $SITE_PACKAGES/system-site.pth exists."
  "$VENV_DIR/bin/python" -c "import zeroconf, bluezero, dbus, gi" || true
  exit 1
fi
echo "✓ zeroconf, bluezero, dbus, gi all import"

echo "-- Making BlueZ advertise/peripheral capable..."
sudo systemctl enable --now bluetooth || true
# The adapter must be unblocked and powered, or advertising fails with
# 'org.bluez.Error.Failed: Not Powered'.
sudo rfkill unblock bluetooth || true
sudo bluetoothctl power on || true

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
