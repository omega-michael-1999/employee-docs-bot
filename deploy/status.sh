#!/usr/bin/env bash
# Show status of all employee-docs-bot instances
set -euo pipefail
echo "=== Dev Instance: AFH_22 ==="
sudo -n /usr/bin/systemctl status employee-docs-bot-afh-22 2>&1 | head -10 || echo "(stopped/failed)"
echo ""
echo "=== Production Instance: Edmonds Villa ==="
sudo -n /usr/bin/systemctl status employee-docs-bot-edmonds-villa 2>&1 | head -10 || echo "(stopped/failed)"
