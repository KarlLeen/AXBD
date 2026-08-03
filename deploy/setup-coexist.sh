#!/usr/bin/env bash
# Install AthenaX on a VPS that already hosts other websites (coexist mode).
# Does NOT remove existing nginx sites or overwrite unrelated configs.
#
# Run on the VPS as root:
#   bash /opt/athenax/deploy/setup-coexist.sh
#
# Or from your Mac after rsync:
#   rsync ... then ssh root@142.93.129.2 'sudo bash /opt/athenax/deploy/setup-coexist.sh'
set -euo pipefail

INSTALL_DIR="/opt/athenax"
PORT="${DASHBOARD_PORT:-8080}"

echo "==> Pre-flight checks..."

if ss -tlnp | grep -q ":${PORT} "; then
  echo "ERROR: port ${PORT} is already in use:"
  ss -tlnp | grep ":${PORT} " || true
  echo "Pick another port: DASHBOARD_PORT=8081 bash $0"
  exit 1
fi

if [ -f /etc/nginx/sites-enabled/athenax-dashboard ]; then
  echo "  athenax nginx site already enabled — will refresh"
fi

bash "$(dirname "$0")/setup.sh"

echo ""
echo "==> Coexist summary"
echo "  AthenaX dashboard : 127.0.0.1:${PORT}"
echo "  Public URL        : https://bd.limlamleen.com (Cloudflare A → this server)"
echo "  Other nginx sites : unchanged (check: ls /etc/nginx/sites-enabled/)"
echo ""
nginx -T 2>/dev/null | grep -E '^\s*(listen|server_name)' | head -30 || true
