#!/usr/bin/env bash
# Restart all employee-docs-bot instances
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
echo "Restarting all instances..."
"$DIR/restart-afh-22.sh"
"$DIR/restart-edmonds-villa.sh"
echo "All instances restarted"
