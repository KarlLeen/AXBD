#!/usr/bin/env bash
# Migrate AthenaX BD Agent to a new VPS.
#
# Usage (from your Mac):
#
#   export NEW_VPS=43.156.131.187
#   export SSH_KEY=~/.ssh/lhkp-kg706v4z.pem
#   export SSH_USER=ubuntu          # Lighthouse Ubuntu image; use root if needed
#   export OLD_VPS=<old-ip>         # optional — copy .env + DB from old server
#
#   bash deploy/migrate-vps.sh
#
# Then in Cloudflare: bd.limlamleen.com A → NEW_VPS (proxy ON)
set -euo pipefail

NEW_VPS="${NEW_VPS:?Set NEW_VPS to the new public IP}"
OLD_VPS="${OLD_VPS:-}"
SSH_KEY="${SSH_KEY:-}"
SSH_USER="${SSH_USER:-ubuntu}"
INSTALL_DIR="/opt/athenax"
SERVICE_USER="athenax"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

ssh_args=()
rsync_ssh=()
if [ -n "$SSH_KEY" ]; then
  ssh_args=(-i "$SSH_KEY")
  rsync_ssh=(-e "ssh -i $SSH_KEY")
fi

remote() {
  ssh "${ssh_args[@]}" -o StrictHostKeyChecking=accept-new "${SSH_USER}@${NEW_VPS}" "$@"
}

echo "==> Target: ${SSH_USER}@${NEW_VPS}"

tmpdir="$(mktemp -d)"
trap 'rm -rf "$tmpdir"' EXIT

if [ -n "$OLD_VPS" ]; then
  echo "==> Copying .env + athenax.db from old VPS ${OLD_VPS}..."
  scp "${ssh_args[@]/#/-i /}" 2>/dev/null || true
  scp_cmd=(scp)
  [ -n "$SSH_KEY" ] && scp_cmd+=(-i "$SSH_KEY")
  "${scp_cmd[@]}" "${SSH_USER}@${OLD_VPS}:${INSTALL_DIR}/.env" "$tmpdir/.env"
  "${scp_cmd[@]}" "${SSH_USER}@${OLD_VPS}:${INSTALL_DIR}/athenax.db" "$tmpdir/athenax.db" 2>/dev/null \
    || echo "  (no athenax.db on old server)"
else
  echo "==> Using local .env (+ athenax.db if present)"
  cp "$REPO_ROOT/.env" "$tmpdir/.env"
  [ -f "$REPO_ROOT/athenax.db" ] && cp "$REPO_ROOT/athenax.db" "$tmpdir/athenax.db"
fi

echo "==> Syncing project to new VPS..."
remote "sudo mkdir -p ${INSTALL_DIR} && sudo chown ${SSH_USER}:${SSH_USER} ${INSTALL_DIR}"
rsync -az --delete \
  "${rsync_ssh[@]}" \
  --exclude '.venv' \
  --exclude '__pycache__' \
  --exclude '*.pyc' \
  --exclude '.git' \
  --exclude 'athenax.db' \
  "$REPO_ROOT/" "${SSH_USER}@${NEW_VPS}:${INSTALL_DIR}/"

echo "==> Running setup.sh on new VPS..."
remote "sudo bash ${INSTALL_DIR}/deploy/setup.sh"

echo "==> Installing .env and database..."
scp_cmd=(scp)
[ -n "$SSH_KEY" ] && scp_cmd+=(-i "$SSH_KEY")
"${scp_cmd[@]}" "$tmpdir/.env" "${SSH_USER}@${NEW_VPS}:/tmp/athenax.env"
remote "sudo mv /tmp/athenax.env ${INSTALL_DIR}/.env && sudo chmod 600 ${INSTALL_DIR}/.env && sudo chown ${SERVICE_USER}:${SERVICE_USER} ${INSTALL_DIR}/.env"
if [ -f "$tmpdir/athenax.db" ]; then
  "${scp_cmd[@]}" "$tmpdir/athenax.db" "${SSH_USER}@${NEW_VPS}:/tmp/athenax.db"
  remote "sudo mv /tmp/athenax.db ${INSTALL_DIR}/athenax.db && sudo chown ${SERVICE_USER}:${SERVICE_USER} ${INSTALL_DIR}/athenax.db"
fi

echo "==> Restarting services..."
remote "sudo systemctl restart athenax-pipeline athenax-bot athenax-dashboard nginx"
remote "sudo systemctl is-active athenax-dashboard athenax-pipeline nginx"

echo ""
echo "====================================================="
echo " Done — update Cloudflare DNS:"
echo "   bd.limlamleen.com  A  ${NEW_VPS}  (proxied)"
echo "====================================================="
echo ""
echo " Verify: curl -sI https://bd.limlamleen.com"
echo " Logs:   ssh ${SSH_USER}@${NEW_VPS} 'journalctl -u athenax-dashboard -n 30 --no-pager'"
echo ""
