#!/usr/bin/env bash
# Stop all employee-docs-bot instances
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
echo "Stopping all instances..."
"$DIR/stop-afh-22.sh"
"$DIR/stop-edmonds-villa.sh"
echo "All instances stopped"
