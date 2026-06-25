#!/usr/bin/env bash
# Start AFH_22 dev instance
set -euo pipefail
sudo -n /usr/bin/systemctl start employee-docs-bot-afh-22
echo "AFH_22 (dev) started"
