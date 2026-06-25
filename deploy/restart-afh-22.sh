#!/usr/bin/env bash
# Restart AFH_22 dev instance
set -euo pipefail
sudo -n /usr/bin/systemctl restart employee-docs-bot-afh-22
echo "AFH_22 (dev) restarted"
