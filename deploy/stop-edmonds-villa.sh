#!/usr/bin/env bash
# Stop Edmonds Villa production instance
set -euo pipefail
sudo -n /usr/bin/systemctl stop employee-docs-bot-edmonds-villa
echo "Edmonds Villa (prod) stopped"
