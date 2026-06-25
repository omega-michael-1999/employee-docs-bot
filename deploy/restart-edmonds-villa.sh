#!/usr/bin/env bash
# Restart Edmonds Villa production instance
set -euo pipefail
sudo -n /usr/bin/systemctl restart employee-docs-bot-edmonds-villa
echo "Edmonds Villa (prod) restarted"
