#!/usr/bin/env bash
# Stop AFH_22 dev instance
set -euo pipefail
sudo -n /usr/bin/systemctl stop employee-docs-bot-afh-22
echo "AFH_22 (dev) stopped"
