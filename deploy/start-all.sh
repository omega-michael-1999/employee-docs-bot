#!/usr/bin/env bash
# Start all employee-docs-bot instances
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
echo "Starting all instances..."
"$DIR/start-afh-22.sh"
"$DIR/start-edmonds-villa.sh"
echo "All instances started"
