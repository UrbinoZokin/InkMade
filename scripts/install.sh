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

echo "-- Installing inkycal package into venv..."
cd /opt/inkycal
/opt/inkycal/venv/bin/pip install -e .

# Optional: install inky driver into venv if not already present.
# Many users install it via pip; some use apt. We'll prefer pip in the venv.
echo "-- Ensuring Inky library is installed in venv..."
"$VENV_DIR/bin/pip" install inky[rpi]

# GPIO button support (view toggle / force refresh / force update). lgpio is
# the pin-factory backend gpiozero uses on current Raspberry Pi OS.
echo "-- Ensuring GPIO button libraries are installed in venv..."
"$VENV_DIR/bin/pip" install lgpio

# -------------- Create config.yaml file --------------

echo "-- Creating config.yaml if missing..."

CONFIG_EXAMPLE="/opt/inkycal/config.yaml.example"
CONFIG_FILE="/opt/inkycal/config.yaml"

if [ ! -f "$CONFIG_FILE" ]; then
  if [ -f "$CONFIG_EXAMPLE" ]; then
    cp "$CONFIG_EXAMPLE" "$CONFIG_FILE"
    echo "✓ Created $CONFIG_FILE from example"
  else
    echo "⚠ Could not find $CONFIG_EXAMPLE to create config.yaml"
  fi
else
  echo "✓ $CONFIG_FILE already exists (leaving it unchanged)"
fi

# ---------------- Create env File --------------
echo "-- Creating .env if missing..."

ENV_EXAMPLE="/opt/inkycal/.env.example"
ENV_FILE="/opt/inkycal/.env"

if [ ! -f "$ENV_FILE" ]; then
  if [ -f "$ENV_EXAMPLE" ]; then
    cp "$ENV_EXAMPLE" "$ENV_FILE"
    echo "✓ Created $ENV_FILE from example (edit this!)"
  else
    echo "⚠ Could not find $ENV_EXAMPLE to create .env"
  fi
else
  echo "✓ $ENV_FILE already exists"
fi


# ----- Install systemd units to correct location -----
echo "-- Installing systemd unit files..."
sudo cp "$APP_DIR/systemd/"*.service "$APP_DIR/systemd/"*.timer /etc/systemd/system/
sudo systemctl daemon-reload

sudo chmod +x "$APP_DIR"/scripts/*.sh

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


# Point the display units at whoever is installing, not the packaged 'pi'.
# Group matters as much as User: since Bookworm the first-boot wizard lets you
# pick any username, and a unit left on Group=pi refuses to start on a device
# where no 'pi' group exists.
APP_USER="$USER"
APP_GROUP="$(id -gn)"
echo "-- Running the display units as $APP_USER:$APP_GROUP ..."
sudo sed -i -e "s/^User=.*/User=$APP_USER/" -e "s/^Group=.*/Group=$APP_GROUP/" \
  /etc/systemd/system/inkycal.service \
  /etc/systemd/system/inkycal-boot.service \
  /etc/systemd/system/inkycal-deepclean.service
sudo systemctl daemon-reload

# ----- Enable services and timers -----
# After this the device is hands-off: plug it in and everything below comes up
# on its own, no keyboard, SSH or button press needed.
echo "-- Enabling services and timers..."

# network-online.target only means anything if something actually waits on the
# network. Without this it is reached immediately and the power-on render can
# start before WiFi has associated.
sudo systemctl enable NetworkManager-wait-online.service >/dev/null 2>&1 || true
# The Pi has no battery-backed RTC. Without NTP the first render after a power
# cut dates the screen from whenever the device was last shut down.
sudo systemctl enable systemd-timesyncd.service >/dev/null 2>&1 || true

sudo systemctl enable --now inkycal.timer
sudo systemctl enable --now inkycal-deepclean.timer
# Over-the-air updates: periodically pull the latest code from GitHub so the
# display can be updated remotely without SSH. Disable with:
#   auto_update.enabled: false  in config.yaml  (or: sudo systemctl disable --now inkycal-update.timer)
sudo systemctl enable --now inkycal-update.timer

# Physical buttons on the Inky Impression board (view toggle / force refresh
# / force update). Disable with: buttons.enabled: false in config.yaml
# (or: sudo systemctl disable --now inkycal-buttons.service)
sudo systemctl enable --now inkycal-buttons.service

# Forced full repaint on every power-on. E-ink holds its last image through a
# power cut and the quarter-hour render skips repainting when nothing changed,
# so without this a device that has been unplugged can come back up showing a
# stale screen. Enabled (not --now): the install triggers its own refresh at
# the end. Disable with: sudo systemctl disable inkycal-boot.service
sudo systemctl enable inkycal-boot.service

# The provisioning agent is installed separately (scripts/install_provisioning.sh),
# but if it is present it belongs in the set that starts at boot too.
if [ -f /etc/systemd/system/inkycal-provisioning.service ]; then
  echo "-- Provisioning agent present; making sure it starts at boot too..."
  sudo systemctl enable --now inkycal-provisioning.service || true
fi

echo "-- Enabled units:"
systemctl list-unit-files 'inkycal*' --no-pager || true

# Quick inky detection (non-fatal)
# echo "-- Checking Inky detection (non-fatal)..."
# python -c 'try:
#     from inky.auto import auto
#     disp = auto(ask_user=False, verbose=False)
#     if disp is None:
#         print("⚠ Inky auto-detect returned None (check wiring/SPI).")
#     else:
#         print(f"✓ Inky detected: {disp.__class__.__name__}")
# except Exception as e:
#     print(f"⚠ Inky check error: {e}")'

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
  echo "  cp $APP_DIR/.env.example $APP_DIR/.env"
fi

# ===== Power-loss safe filesystem (optional) =====
ENABLE_OVERLAYROOT="${ENABLE_OVERLAYROOT:-0}"

if [ "$ENABLE_OVERLAYROOT" -eq 1 ]; then
  echo
  echo "== Enabling power-loss safe filesystem (overlayroot + tmpfs logs) =="

  echo "-- Installing overlayroot..."
  sudo apt-get install -y overlayroot

  echo "-- Configuring overlayroot..."
  # This makes root read-only with a tmpfs overlay (writes go to RAM)
  sudo tee /etc/overlayroot.conf >/dev/null <<'EOF'
overlayroot="tmpfs:swap=1"
EOF

  echo "-- Ensuring persistent directories exist..."
  sudo mkdir -p /var/lib/inkycal /opt/inkycal
  sudo chown -R "$USER" /var/lib/inkycal /opt/inkycal

  echo "-- Updating /etc/fstab for tmpfs + bind mounts..."
  FSTAB="/etc/fstab"

  # Helper: append a line only if it doesn't already exist (exact match)
  ensure_fstab_line() {
    local line="$1"
    grep -qxF "$line" "$FSTAB" || echo "$line" | sudo tee -a "$FSTAB" >/dev/null
  }

  # Bind mounts (these paths remain persistent across reboots)
  # NOTE: bind mounts require both source and target to exist (they do).
  ensure_fstab_line "# InkyCal persistent storage"
  ensure_fstab_line "/var/lib/inkycal  /var/lib/inkycal  none  bind  0  0"
  ensure_fstab_line "/opt/inkycal      /opt/inkycal      none  bind  0  0"

  # RAM-backed temp + logs to reduce SD writes/corruption
  ensure_fstab_line ""
  ensure_fstab_line "# RAM-backed temp/logs (reduce SD wear)"
  ensure_fstab_line "tmpfs   /tmp        tmpfs   defaults,noatime,size=100m   0  0"
  ensure_fstab_line "tmpfs   /var/tmp    tmpfs   defaults,noatime,size=50m    0  0"
  ensure_fstab_line "tmpfs   /var/log    tmpfs   defaults,noatime,size=50m    0  0"

  echo "-- Enabling kernel modules now (best-effort)..."
  sudo modprobe overlay 2>/dev/null || true

  echo
  echo "== Overlayroot enabled. A reboot is required. =="
  echo "After reboot, root will be overlayed (writes go to RAM)."
  echo "Your app data stays persistent in /var/lib/inkycal and /opt/inkycal."
  echo
  echo "Reboot with: sudo reboot"
fi

# Paint the panel now, using the same unit every power-on will use. --no-block
# so a slow full repaint doesn't hold the installer open; watch the journal for
# how it went.
echo
echo "-- Forcing a display refresh (exactly what every power-on now does)..."
sudo systemctl start --no-block inkycal-boot.service || true

echo
echo "== Done =="
echo "Edit these before expecting calendar sync:"
echo "  sudo nano $APP_DIR/config.yaml"
echo "  sudo nano $APP_DIR/.env"
echo
echo "At every power-on the Pi now brings itself up on its own:"
echo "  inkycal-boot.service    forces a full display refresh"
echo "  inkycal.timer           renders again every quarter hour"
echo "  inkycal-update.timer    checks GitHub for over-the-air updates"
echo "  inkycal-deepclean.timer weekly deep-clean refresh"
echo "  inkycal-buttons.service physical buttons"
echo
echo "Check services and timers:"
echo "  systemctl list-unit-files 'inkycal*'"
echo "  systemctl list-timers --all | grep inkycal"
echo "Logs:"
echo "  journalctl -u inkycal-boot.service -n 50"
echo "  journalctl -u inkycal.service -n 50"
echo
echo "Refresh the display on demand (same path as a power-on):"
echo "  sudo systemctl start inkycal-boot.service"
echo
echo "Manual test (forces refresh):"
echo "  $VENV_DIR/bin/python -m inkycal.main --config $APP_DIR/config.yaml --state $STATE_DIR/state.json --force"
echo
echo "NOTE: If SPI/I2C devices weren't present, reboot:"
echo "  sudo reboot"
