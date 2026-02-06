#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/opt/inkycal"
VENV_DIR="/opt/inkycal/venv"
STATE_DIR="/var/lib/inkycal"

echo "== InkyCal install =="

if [ ! -d "$APP_DIR" ]; then
  echo "ERROR: Expected repo at $APP_DIR"
  exit 1
fi

# OS deps (fonts, PIL deps, SPI/I2C tooling)
echo "-- Installing OS packages..."
sudo apt-get update
sudo apt-get install -y \
  python3 python3-venv python3-pip \
  fonts-dejavu-core \
  libjpeg-dev zlib1g-dev libfreetype6-dev \
  i2c-tools \
  raspi-config

# Create dirs
echo "-- Creating directories..."
sudo mkdir -p "$APP_DIR/secrets" "$STATE_DIR"
sudo chown -R "$USER":"$USER" "$APP_DIR"
sudo chown -R "$USER":"$USER" "$STATE_DIR"

# Externally-managed env fix: venv
echo "-- Creating/updating venv at $VENV_DIR ..."
python3 -m venv "$VENV_DIR"
"$VENV_DIR/bin/python" -m pip install --upgrade pip wheel setuptools

echo "-- Installing Python deps..."
"$VENV_DIR/bin/pip" install -r "$APP_DIR/requirements.txt"

# Optional: install inky driver into venv if not already present.
# Many users install it via pip; some use apt. We'll prefer pip in the venv.
echo "-- Ensuring Inky library is installed in venv..."
"$VENV_DIR/bin/python" - <<'PY'
import importlib.util, sys
spec = importlib.util.find_spec("inky")
if spec is None:
    sys.exit(2)
sys.exit(0)
PY
if [ $? -ne 0 ]; then
  echo "   Inky not found in venv; installing..."
  "$VENV_DIR/bin/pip" install inky[rpi]
fi

# Sanity checks
echo
echo "== Sanity checks =="

# Fonts
if [ -f "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf" ]; then
  echo "✓ DejaVuSans.ttf present"
else
  echo "✗ DejaVuSans.ttf missing (fonts-dejavu-core should provide it)"
fi

echo
echo "== Enabling SPI and I2C =="

# 1) Try raspi-config non-interactive (preferred)
if command -v raspi-config >/dev/null 2>&1; then
  # Enable SPI (do_spi: 0 enable, 1 disable)
  sudo raspi-config nonint do_spi 0 || true
  # Enable I2C (do_i2c: 0 enable, 1 disable)
  sudo raspi-config nonint do_i2c 0 || true
else
  echo "⚠ raspi-config not found; will try config.txt edits."
fi

# 2) Ensure dtparam lines exist (fallback/extra safety)
BOOT_CFG=""
if [ -f /boot/firmware/config.txt ]; then
  BOOT_CFG="/boot/firmware/config.txt"
elif [ -f /boot/config.txt ]; then
  BOOT_CFG="/boot/config.txt"
fi

if [ -n "$BOOT_CFG" ]; then
  echo "-- Using boot config: $BOOT_CFG"

  # Ensure dtparam=spi=on
  if ! grep -qE '^\s*dtparam=spi=on\s*$' "$BOOT_CFG"; then
    # If a dtparam=spi= line exists but is off, replace it; else append.
    if grep -qE '^\s*dtparam=spi=' "$BOOT_CFG"; then
      sudo sed -i 's/^\s*dtparam=spi=.*/dtparam=spi=on/' "$BOOT_CFG"
    else
      echo "dtparam=spi=on" | sudo tee -a "$BOOT_CFG" >/dev/null
    fi
  fi

  # Ensure dtparam=i2c_arm=on
  if ! grep -qE '^\s*dtparam=i2c_arm=on\s*$' "$BOOT_CFG"; then
    if grep -qE '^\s*dtparam=i2c_arm=' "$BOOT_CFG"; then
      sudo sed -i 's/^\s*dtparam=i2c_arm=.*/dtparam=i2c_arm=on/' "$BOOT_CFG"
    else
      echo "dtparam=i2c_arm=on" | sudo tee -a "$BOOT_CFG" >/dev/null
    fi
  fi
else
  echo "⚠ Could not find /boot/firmware/config.txt or /boot/config.txt"
fi

# 3) Load kernel modules now (no harm if already loaded)
sudo modprobe spi-bcm2835 2>/dev/null || true
sudo modprobe i2c-dev 2>/dev/null || true

# 4) Post-check
echo "-- Checking device nodes (may require reboot to appear)..."
if ls /dev/spidev* >/dev/null 2>&1; then
  echo "✓ SPI device present: $(ls /dev/spidev* | tr '\n' ' ')"
else
  echo "⚠ SPI device not present yet (reboot likely required)."
fi

if ls /dev/i2c-* >/dev/null 2>&1; then
  echo "✓ I2C device present: $(ls /dev/i2c-* | tr '\n' ' ')"
else
  echo "⚠ I2C device not present yet (reboot likely required)."
fi

# 5) Recommend reboot if needed
NEED_REBOOT=0
ls /dev/spidev* >/dev/null 2>&1 || NEED_REBOOT=1
ls /dev/i2c-*   >/dev/null 2>&1 || NEED_REBOOT=1

if [ "$NEED_REBOOT" -eq 1 ]; then
  echo
  echo "== Reboot recommended =="
  echo "SPI/I2C were enabled, but device nodes are not visible yet."
  echo "Run: sudo reboot"
fi


# Quick inky detection (non-fatal)
echo "-- Checking Inky detection (non-fatal)..."
"$VENV_DIR/bin/python" - <<'PY' || true
try:
    from inky.auto import auto
    disp = auto(ask_user=False, verbose=False)
    if disp is None:
        print("⚠ Inky auto-detect returned None (check wiring/SPI).")
    else:
        print(f"✓ Inky detected: {disp.__class__.__name__}")
except Exception as e:
    print(f"⚠ Inky check error: {e}")
PY

# Config presence (non-fatal)
if [ -f "$APP_DIR/config.yaml" ]; then
  echo "✓ config.yaml present"
else
  echo "⚠ config.yaml missing. Create it:"
  echo "  cp $APP_DIR/config.yaml.example $APP_DIR/config.yaml"
fi

if [ -f "$APP_DIR/.env" ]; then
  echo "✓ .env present"
else
  echo "⚠ .env missing. Create it:"
  echo "  cp $APP_DIR/.env.example $APP_DIR/.env
