#!/usr/bin/env bash
# AthenaX BD Agent — VPS setup (Ubuntu 22.04/24.04; tested on 2 vCPU / 4 GB RAM)
# Run as root: curl -fsSL https://raw.githubusercontent.com/KarlLeen/AXBD/main/deploy/setup.sh | sudo bash
set -euo pipefail

REPO="https://github.com/KarlLeen/AXBD.git"
INSTALL_DIR="/opt/athenax"
SERVICE_USER="athenax"

RAM_MB="$(awk '/^MemTotal:/{print int($2/1024)}' /proc/meminfo)"

# ── 1. Swap (required on ≤2 GB; optional safety net on larger instances) ─────
echo "==> [1/9] Checking swap (detected ${RAM_MB} MB RAM)..."
if [ ! -f /swapfile ]; then
  if [ "$RAM_MB" -lt 2048 ]; then
    SWAP_SIZE="2G"
  elif [ "$RAM_MB" -lt 4096 ]; then
    SWAP_SIZE="1G"
  else
    SWAP_SIZE=""
  fi
  if [ -n "$SWAP_SIZE" ]; then
    fallocate -l "$SWAP_SIZE" /swapfile
    chmod 600 /swapfile
    mkswap /swapfile
    swapon /swapfile
    echo '/swapfile none swap sw 0 0' >> /etc/fstab
    grep -q '^vm.swappiness=' /etc/sysctl.conf 2>/dev/null || echo 'vm.swappiness=10' >> /etc/sysctl.conf
    sysctl vm.swappiness=10
    echo "  Swap created ($SWAP_SIZE)"
  else
    echo "  RAM ≥ 4 GB — skipping swap"
  fi
else
  echo "  Swap already exists — skipping"
fi

# ── 2. System dependencies ────────────────────────────────────────────────────
echo "==> [2/9] Installing system dependencies..."
apt-get update -q
apt-get install -y -q git curl build-essential nginx ca-certificates \
  python3 python3-venv python3-dev

# ── 3. uv (+ Python 3.12 via uv on Ubuntu 22.04) ─────────────────────────────
echo "==> [3/9] Installing uv..."
curl -LsSf https://astral.sh/uv/install.sh | sh
install -m 755 "${HOME}/.local/bin/uv" /usr/local/bin/uv
UV_BIN="/usr/local/bin/uv"

# ── 4. Repo ───────────────────────────────────────────────────────────────────
echo "==> [4/9] Cloning / updating repo..."
if [ -d "$INSTALL_DIR/.git" ]; then
  git -C "$INSTALL_DIR" pull --ff-only
elif [ -f "$INSTALL_DIR/pyproject.toml" ]; then
  echo "  Using existing checkout at $INSTALL_DIR"
else
  git clone "$REPO" "$INSTALL_DIR"
fi

# ── 5. System user (before venv — python must live under /opt/athenax) ────────
echo "==> [5/9] Creating system user '$SERVICE_USER'..."
id "$SERVICE_USER" &>/dev/null || useradd --system --no-create-home --shell /usr/sbin/nologin "$SERVICE_USER"
chown -R "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR"

# ── 6. Python deps (as service user so .venv python is accessible) ───────────
echo "==> [6/9] Installing Python dependencies..."
cd "$INSTALL_DIR"
UV_PYTHON_INSTALL_DIR="${INSTALL_DIR}/.uv-python"
UV_CACHE_DIR="${INSTALL_DIR}/.cache/uv"
mkdir -p "$UV_CACHE_DIR"
chown -R "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR"
export UV_PYTHON_INSTALL_DIR UV_CACHE_DIR
sudo -u "$SERVICE_USER" env \
  HOME="$INSTALL_DIR" UV_PYTHON_INSTALL_DIR="$UV_PYTHON_INSTALL_DIR" UV_CACHE_DIR="$UV_CACHE_DIR" \
  "$UV_BIN" python install 3.12
sudo -u "$SERVICE_USER" env \
  HOME="$INSTALL_DIR" UV_PYTHON_INSTALL_DIR="$UV_PYTHON_INSTALL_DIR" UV_CACHE_DIR="$UV_CACHE_DIR" \
  "$UV_BIN" sync --python 3.12

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

# ── 8. systemd services ───────────────────────────────────────────────────────
echo "==> [8/9] Installing systemd services..."
DEPLOY_DIR="$INSTALL_DIR/deploy"

for svc in athenax-pipeline athenax-bot athenax-dashboard; do
  cp "$DEPLOY_DIR/$svc.service" "/etc/systemd/system/$svc.service"
done
# Enrich is a long one-shot backfill — install unit but do NOT auto-start on setup.
cp "$DEPLOY_DIR/athenax-enrich.service" /etc/systemd/system/athenax-enrich.service
systemctl daemon-reload

for svc in athenax-pipeline athenax-bot athenax-dashboard; do
  systemctl enable "$svc"
  systemctl restart "$svc"
done
mkdir -p "$INSTALL_DIR/data"
chown -R "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR/data"

# ── 9. nginx ──────────────────────────────────────────────────────────────────
echo "==> [9/9] Configuring nginx..."
cp "$DEPLOY_DIR/nginx-dashboard.conf" /etc/nginx/sites-available/athenax-dashboard
ln -sf /etc/nginx/sites-available/athenax-dashboard /etc/nginx/sites-enabled/athenax-dashboard
# Do NOT remove sites-enabled/default — other vhosts on this VPS must keep working.
# bd.limlamleen.com is routed by server_name; the default site serves everything else.

# On ≤2 GB hosts, cap nginx workers to reduce RAM use
if [ "$RAM_MB" -lt 2048 ]; then
  sed -i 's/worker_processes auto;/worker_processes 1;/' /etc/nginx/nginx.conf
fi

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
echo "   systemctl start athenax-enrich      # listing spreadsheet backfill (optional)"
echo ""
echo " Logs:"
echo "   journalctl -fu athenax-pipeline"
echo "   journalctl -fu athenax-bot"
echo "   journalctl -fu athenax-dashboard"
echo "   journalctl -fu athenax-enrich"
echo ""
echo " Dashboard:"
echo "   https://bd.limlamleen.com  (after Cloudflare A record → this VPS IP)"
echo "   http://$(hostname -I | awk '{print $1}'):8080  (direct)"
echo ""
echo " Run pipeline now:"
echo "   sudo -u athenax /opt/athenax/.venv/bin/athenax run"
echo ""
