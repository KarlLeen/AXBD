#!/usr/bin/env bash
# Sync listing enrichment code + W6 spreadsheet to the VPS, restart dashboard,
# and start (or resume) the long-running enrich job.
#
# Usage (from your Mac):
#
#   export VPS=43.156.131.187          # or whichever hosts bd.limlamleen.com
#   export SSH_USER=ubuntu             # optional
#   export SSH_KEY=~/.ssh/xxx.pem      # optional
#
#   bash deploy/sync-enrich.sh
set -euo pipefail

VPS="${VPS:?Set VPS to the public IP that serves bd.limlamleen.com}"
SSH_USER="${SSH_USER:-ubuntu}"
SSH_KEY="${SSH_KEY:-}"
INSTALL_DIR="/opt/athenax"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

ssh_args=(-o StrictHostKeyChecking=accept-new)
RSYNC_RSH="ssh -o StrictHostKeyChecking=accept-new"
if [ -n "$SSH_KEY" ]; then
  ssh_args+=(-i "$SSH_KEY")
  RSYNC_RSH="ssh -i $SSH_KEY -o StrictHostKeyChecking=accept-new"
fi

remote() {
  ssh "${ssh_args[@]}" "${SSH_USER}@${VPS}" "$@"
}

echo "==> Syncing repo → ${SSH_USER}@${VPS}:${INSTALL_DIR}"
remote "sudo mkdir -p ${INSTALL_DIR}/data && sudo chown -R ${SSH_USER}:${SSH_USER} ${INSTALL_DIR}"
rsync -az -e "$RSYNC_RSH" \
  --exclude '.venv' \
  --exclude '__pycache__' \
  --exclude '*.pyc' \
  --exclude '.git' \
  --exclude 'athenax.db' \
  --exclude '.env' \
  "$REPO_ROOT/" "${SSH_USER}@${VPS}:${INSTALL_DIR}/"

echo "==> Installing deps + enrich unit + restarting dashboard"
remote "sudo bash -lc '
  set -e
  cd ${INSTALL_DIR}
  chown -R athenax:athenax ${INSTALL_DIR}
  sudo -u athenax env HOME=${INSTALL_DIR} UV_CACHE_DIR=${INSTALL_DIR}/.cache/uv \
    /usr/local/bin/uv sync --python 3.12
  cp ${INSTALL_DIR}/deploy/athenax-enrich.service /etc/systemd/system/athenax-enrich.service
  systemctl daemon-reload
  systemctl restart athenax-dashboard
  systemctl start athenax-enrich
  systemctl --no-pager --full status athenax-enrich | head -20
'"

echo ""
echo "Done. Watch progress at https://bd.limlamleen.com (Listing Enrichment panel)"
echo "Logs:  ssh ${SSH_USER}@${VPS} 'journalctl -fu athenax-enrich'"
