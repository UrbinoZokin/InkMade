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

# Bluetooth/D-Bus/GLib, zeroconf and cryptography, all as prebuilt system
# packages. This is important on a Pi: installing zeroconf from PyPI tries to
# COMPILE its Cython C-extensions, which can hang or run out of RAM on a Pi
# Zero 2 W, and cryptography is Rust. The apt packages ship prebuilt binaries,
# so we use those and expose them to the venv.
echo "-- Installing Bluetooth + D-Bus + zeroconf + cryptography system packages..."
sudo apt-get update
sudo apt-get install -y \
  bluetooth bluez \
  python3-dbus python3-gi \
  python3-zeroconf \
  python3-cryptography \
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

# Only bluezero and spake2 need pip, and both are pure Python (no compilation).
# --no-deps leaves everything they depend on to the apt packages above, and
# --prefer-binary guards against any source builds creeping in.
echo "-- Installing bluezero + spake2 into venv..."
"$VENV_DIR/bin/pip" install --prefer-binary --no-deps -r "$APP_DIR/requirements-provisioning.txt"

# Fail fast with a clear message if the agent's imports are not satisfied.
echo "-- Verifying provisioning imports..."
if ! "$VENV_DIR/bin/python" -c "import zeroconf, bluezero, dbus, gi, spake2, cryptography" 2>/dev/null; then
  echo "✗ Provisioning imports failed. Check that python3-zeroconf/python3-dbus/"
  echo "  python3-gi/python3-cryptography installed and that"
  echo "  $SITE_PACKAGES/system-site.pth exists."
  "$VENV_DIR/bin/python" -c "import zeroconf, bluezero, dbus, gi, spake2, cryptography" || true
  exit 1
fi
echo "✓ zeroconf, bluezero, dbus, gi, spake2, cryptography all import"

echo "-- Making BlueZ advertise/peripheral capable..."
sudo systemctl enable --now bluetooth || true
# The adapter must be unblocked and powered, or advertising fails with
# 'org.bluez.Error.Failed: Not Powered'.
sudo rfkill unblock bluetooth || true
sudo bluetoothctl power on || true

echo "-- Installing systemd unit..."
sudo cp "$APP_DIR/systemd/inkycal-provisioning.service" /etc/systemd/system/
sudo systemctl daemon-reload
# Enabled so a device that still has no Google token or WiFi network comes up
# in setup mode by itself. Anything already set up exits straight away.
sudo systemctl enable --now inkycal-provisioning.service

echo
echo "== Done =="
echo "The agent only runs in setup mode: for 10 minutes after you press"
echo "button C, or by itself while this InkyCal has no Google token or WiFi"
echo "network yet. Setup mode puts a one-time setup code on the screen; the"
echo "companion app asks for it, and everything it sends over Bluetooth"
echo "('InkyCal-Setup') or WiFi (mDNS _inkycal._tcp) is encrypted with a key"
echo "only that code produces."
echo
echo "Check it:"
echo "  systemctl status inkycal-provisioning.service"
echo "  journalctl -u inkycal-provisioning.service -f"
