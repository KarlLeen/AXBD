#!/usr/bin/env bash
# AthenaX BD Agent — VPS initial setup (Ubuntu/Debian, run as root)
set -euo pipefail

REPO="https://github.com/KarlLeen/AXBD.git"
INSTALL_DIR="/opt/athenax"
SERVICE_USER="athenax"

echo "==> [1/7] Creating system user '$SERVICE_USER'..."
id "$SERVICE_USER" &>/dev/null || useradd --system --no-create-home --shell /usr/sbin/nologin "$SERVICE_USER"

echo "==> [2/7] Installing system dependencies..."
apt-get update -q
apt-get install -y -q git curl python3.12 python3.12-venv python3.12-dev build-essential

echo "==> [3/7] Installing uv..."
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"

echo "==> [4/7] Cloning / updating repo..."
if [ -d "$INSTALL_DIR/.git" ]; then
  git -C "$INSTALL_DIR" pull --ff-only
else
  git clone "$REPO" "$INSTALL_DIR"
fi
chown -R "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR"

echo "==> [5/7] Installing Python dependencies..."
cd "$INSTALL_DIR"
uv sync --python python3.12

echo "==> [6/7] Setting up .env..."
if [ ! -f "$INSTALL_DIR/.env" ]; then
  cp "$INSTALL_DIR/.env.example" "$INSTALL_DIR/.env"
  echo ""
  echo "  *** IMPORTANT: fill in your API keys before starting services ***"
  echo "  Edit: $INSTALL_DIR/.env"
  echo ""
else
  echo "  .env already exists — skipping"
fi
chmod 600 "$INSTALL_DIR/.env"
chown "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR/.env"

echo "==> [7/7] Installing and enabling systemd services..."
DEPLOY_DIR="$INSTALL_DIR/deploy"
for svc in athenax-pipeline athenax-bot athenax-dashboard; do
  cp "$DEPLOY_DIR/$svc.service" "/etc/systemd/system/$svc.service"
done

systemctl daemon-reload

for svc in athenax-pipeline athenax-bot athenax-dashboard; do
  systemctl enable "$svc"
  systemctl restart "$svc"
done

echo ""
echo "====================================================="
echo " AthenaX BD Agent deployed successfully!"
echo "====================================================="
echo ""
echo " Services:"
echo "   systemctl status athenax-pipeline   # weekly scheduler"
echo "   systemctl status athenax-bot        # Telegram bot"
echo "   systemctl status athenax-dashboard  # web UI → http://<VPS-IP>:8080"
echo ""
echo " Logs:"
echo "   journalctl -fu athenax-pipeline"
echo "   journalctl -fu athenax-bot"
echo "   journalctl -fu athenax-dashboard"
echo ""
echo " Run pipeline immediately:"
echo "   sudo -u athenax /opt/athenax/.venv/bin/athenax run"
echo ""
