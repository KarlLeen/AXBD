#!/usr/bin/env bash
# AthenaX BD Agent — VPS setup (Ubuntu 24.04, 1 vCPU / 1 GB RAM)
# Run as root: curl -fsSL https://raw.githubusercontent.com/KarlLeen/AXBD/main/deploy/setup.sh | sudo bash
set -euo pipefail

REPO="https://github.com/KarlLeen/AXBD.git"
INSTALL_DIR="/opt/athenax"
SERVICE_USER="athenax"

# ── 1. Swap (critical for 1 GB RAM — pipeline peaks at ~800 MB) ──────────────
echo "==> [1/9] Setting up 2 GB swap..."
if [ ! -f /swapfile ]; then
  fallocate -l 2G /swapfile
  chmod 600 /swapfile
  mkswap /swapfile
  swapon /swapfile
  echo '/swapfile none swap sw 0 0' >> /etc/fstab
  # Reduce swappiness — only use swap when truly necessary
  echo 'vm.swappiness=10' >> /etc/sysctl.conf
  sysctl vm.swappiness=10
  echo "  Swap created (2 GB)"
else
  echo "  Swap already exists — skipping"
fi

# ── 2. System dependencies ────────────────────────────────────────────────────
echo "==> [2/9] Installing system dependencies..."
apt-get update -q
apt-get install -y -q git curl python3.12 python3.12-venv python3.12-dev build-essential nginx

# ── 3. uv ─────────────────────────────────────────────────────────────────────
echo "==> [3/9] Installing uv..."
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"

# ── 4. Repo ───────────────────────────────────────────────────────────────────
echo "==> [4/9] Cloning / updating repo..."
if [ -d "$INSTALL_DIR/.git" ]; then
  git -C "$INSTALL_DIR" pull --ff-only
else
  git clone "$REPO" "$INSTALL_DIR"
fi

# ── 5. Python deps ────────────────────────────────────────────────────────────
echo "==> [5/9] Installing Python dependencies..."
cd "$INSTALL_DIR"
uv sync --python python3.12

# ── 6. System user ────────────────────────────────────────────────────────────
echo "==> [6/9] Creating system user '$SERVICE_USER'..."
id "$SERVICE_USER" &>/dev/null || useradd --system --no-create-home --shell /usr/sbin/nologin "$SERVICE_USER"
chown -R "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR"

# ── 7. .env ───────────────────────────────────────────────────────────────────
echo "==> [7/9] Setting up .env..."
if [ ! -f "$INSTALL_DIR/.env" ]; then
  cp "$INSTALL_DIR/.env.example" "$INSTALL_DIR/.env"
  echo ""
  echo "  *** STOP: fill in your API keys before starting services ***"
  echo "  Edit: $INSTALL_DIR/.env"
  echo "  Required keys: DEEPSEEK_API_KEY, SERPER_API_KEY, GITHUB_TOKEN,"
  echo "                 INTERNAL_API_KEY, ATHENAX_API_URL"
  echo "  Then re-run: systemctl restart athenax-pipeline athenax-bot athenax-dashboard"
  echo ""
else
  echo "  .env already exists — skipping"
fi
chmod 600 "$INSTALL_DIR/.env"
chown "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR/.env"

# ── 8. systemd services (memory-constrained for 1 GB RAM) ────────────────────
echo "==> [8/9] Installing systemd services..."
DEPLOY_DIR="$INSTALL_DIR/deploy"

for svc in athenax-pipeline athenax-bot athenax-dashboard; do
  cp "$DEPLOY_DIR/$svc.service" "/etc/systemd/system/$svc.service"
done

systemctl daemon-reload

for svc in athenax-pipeline athenax-bot athenax-dashboard; do
  systemctl enable "$svc"
  systemctl restart "$svc"
done

# ── 9. nginx ──────────────────────────────────────────────────────────────────
echo "==> [9/9] Configuring nginx..."
cp "$DEPLOY_DIR/nginx-dashboard.conf" /etc/nginx/sites-available/athenax-dashboard
ln -sf /etc/nginx/sites-available/athenax-dashboard /etc/nginx/sites-enabled/athenax-dashboard
rm -f /etc/nginx/sites-enabled/default

# Tune nginx for low-RAM: 1 worker process
sed -i 's/worker_processes auto;/worker_processes 1;/' /etc/nginx/nginx.conf

nginx -t && systemctl enable nginx && systemctl reload nginx

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
echo "====================================================="
echo " AthenaX BD Agent deployed!"
echo "====================================================="
echo ""
echo " RAM:  $(free -h | awk '/^Mem/{print $2}') physical + $(free -h | awk '/^Swap/{print $2}') swap"
echo ""
echo " Services:"
echo "   systemctl status athenax-pipeline   # weekly scheduler"
echo "   systemctl status athenax-bot        # Telegram bot"
echo "   systemctl status athenax-dashboard  # web UI"
echo ""
echo " Dashboard:"
echo "   https://bd.limlamleen.com  (after Cloudflare A record → this VPS IP)"
echo "   http://$(hostname -I | awk '{print $1}'):8080  (direct)"
echo ""
echo " Logs:"
echo "   journalctl -fu athenax-pipeline"
echo "   journalctl -fu athenax-bot"
echo "   journalctl -fu athenax-dashboard"
echo ""
echo " Run pipeline now:"
echo "   sudo -u athenax /opt/athenax/.venv/bin/athenax run"
echo ""
