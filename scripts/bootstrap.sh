#!/usr/bin/env bash
set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/UrbinoZokin/InkMade.git}"
INSTALL_DIR="${INSTALL_DIR:-/opt/inkycal}"

echo "== InkyCal bootstrap =="
echo "Repo:   $REPO_URL"
echo "Target: $INSTALL_DIR"
echo

# Base deps
sudo apt-get update
sudo apt-get install -y git ca-certificates

# Create target dir
sudo mkdir -p "$INSTALL_DIR"
sudo chown -R "$USER":"$USER" "$INSTALL_DIR"

# Clone or update
if [ -d "$INSTALL_DIR/.git" ]; then
  echo "Updating existing repo..."
  cd "$INSTALL_DIR"
  git fetch --all
  git reset --hard main
  
else
  echo "Cloning repo..."
  git clone "$REPO_URL" "$INSTALL_DIR"
  cd "$INSTALL_DIR"
fi

# Run installer
chmod +x scripts/*.sh || true
./scripts/install.sh

echo
echo "Bootstrap done."
echo "Next:"
echo "  - Copy config.yaml.example -> /opt/inkycal/config.yaml"
echo "  - Copy .env.example -> /opt/inkycal/.env"
echo "  - Put Google creds in /opt/inkycal/secrets/"
