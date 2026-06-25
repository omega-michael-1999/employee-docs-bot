#!/usr/bin/env bash
# Start Edmonds Villa production instance
set -euo pipefail
sudo -n /usr/bin/systemctl start employee-docs-bot-edmonds-villa
echo "Edmonds Villa (prod) started"
