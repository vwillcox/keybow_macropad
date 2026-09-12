#!/usr/bin/env bash
# Installs the udev rule (sudo, one time), creates a venv for the daemon,
# seeds ~/.config/keybow/config.json, and enables the systemd --user service.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="$HOME/.local/share/keybow/venv"
SERVICE_DIR="$HOME/.config/systemd/user"

echo "==> Installing udev rule (needs sudo)"
sed -e "s|__USER__|$USER|g" "$REPO_DIR/install/99-keybow2040.rules" | sudo tee /etc/udev/rules.d/99-keybow2040.rules > /dev/null
sudo udevadm control --reload-rules
sudo udevadm trigger --action=add

echo "==> Creating Python venv at $VENV_DIR"
python3 -m venv "$VENV_DIR"
"$VENV_DIR/bin/pip" install --upgrade pip
"$VENV_DIR/bin/pip" install -e "$REPO_DIR/daemon"

echo "==> Seeding ~/.config/keybow/config.json (won't overwrite an existing one)"
mkdir -p "$HOME/.config/keybow"
if [ ! -f "$HOME/.config/keybow/config.json" ]; then
    cp "$REPO_DIR/config/default.config.json" "$HOME/.config/keybow/config.json"
fi

echo "==> Installing systemd --user unit"
mkdir -p "$SERVICE_DIR"
sed \
    -e "s|__VENV_PYTHON__|$VENV_DIR/bin/python|g" \
    -e "s|__WORKDIR__|$REPO_DIR/daemon|g" \
    "$REPO_DIR/install/keybow-daemon.service" > "$SERVICE_DIR/keybow-daemon.service"

systemctl --user daemon-reload
systemctl --user enable --now keybow-daemon.service

echo
echo "==> Done."
echo "    Status:  systemctl --user status keybow-daemon"
echo "    Logs:    journalctl --user -u keybow-daemon -f"
echo "    Web UI:  http://127.0.0.1:8642"
