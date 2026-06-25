#!/usr/bin/env bash
# Setup systemd services for all employee-docs-bot instances
#
# Usage: sudo ./setup-clients.sh
#
# Architecture:
#   Dev (AFH_22)      → runs from the git subrepo (~/github/ai-os/subrepos/employee-docs-bot/)
#   Prod (Edmonds Villa) → runs from /opt/employee-docs-bot/
#
# Each instance has its own .env file, Telegram bot token, and API keys.

set -euo pipefail

echo "========================================"
echo " Setting up all AFH client instances"
echo "========================================"

# Stop existing services first
for svc in employee-docs-bot-afh-22 employee-docs-bot-edmonds-villa; do
  if systemctl is-active --quiet "$svc" 2>/dev/null; then
    echo "==> Stopping $svc..."
    systemctl stop "$svc"
  fi
done

# --- Dev Instance: AFH_22 (runs from subrepo) ---
CLIENT="afh-22"
SERVICE="employee-docs-bot-${CLIENT}"
WORKDIR="/home/michael/github/ai-os/subrepos/employee-docs-bot"
ENV_FILE="${WORKDIR}/.env"
VENV_PYTHON="${WORKDIR}/.venv/bin/python3"

echo "==> Creating service file for ${SERVICE} (dev, from subrepo)..."
tee "/etc/systemd/system/${SERVICE}.service" > /dev/null << SERVICE
[Unit]
Description=Employee Docs Bot — AFH_22 (Dev)
Documentation=https://github.com/omega-michael-1999/employee-docs-bot
After=network.target

[Service]
Type=simple
User=michael
WorkingDirectory=${WORKDIR}
ExecStart=${VENV_PYTHON} bot.py
Restart=always
RestartSec=10
EnvironmentFile=${ENV_FILE}
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
SERVICE
echo "  ✓ ${SERVICE} service created (dev → subrepo)"

# --- Prod Instance: Edmonds Villa (runs from /opt) ---
CLIENT2="edmonds-villa"
SERVICE2="employee-docs-bot-${CLIENT2}"
WORKDIR2="/opt/employee-docs-bot"
ENV_FILE2="${WORKDIR2}/.env.${CLIENT2}"
VENV_PYTHON2="${WORKDIR2}/.venv/bin/python3"

echo "==> Creating service file for ${SERVICE2} (production, from /opt)..."
tee "/etc/systemd/system/${SERVICE2}.service" > /dev/null << SERVICE2
[Unit]
Description=Employee Docs Bot — Edmonds Villa (Production)
Documentation=https://github.com/omega-michael-1999/employee-docs-bot
After=network.target

[Service]
Type=simple
User=michael
WorkingDirectory=${WORKDIR2}
ExecStart=${VENV_PYTHON2} bot.py
Restart=always
RestartSec=10
EnvironmentFile=${ENV_FILE2}
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
SERVICE2
echo "  ✓ ${SERVICE2} service created (prod → /opt)"

# --- Clean up old generic service ---
if [ -f /etc/systemd/system/employee-docs-bot.service ]; then
  echo "==> Removing old generic service file..."
  rm /etc/systemd/system/employee-docs-bot.service
fi
if [ -f /etc/systemd/system/employee-docs-bot-prod.service ]; then
  echo "==> Removing old employee-docs-bot-prod.service..."
  rm /etc/systemd/system/employee-docs-bot-prod.service
fi

systemctl daemon-reload

# Enable both
systemctl enable employee-docs-bot-afh-22
systemctl enable employee-docs-bot-edmonds-villa

echo ""
echo "========================================"
echo " All clients set up. Manage with:"
echo "========================================"
echo ""
echo "  # Dev instance (AFH_22 — from subrepo)"
echo "  sudo systemctl {start|stop|restart} employee-docs-bot-afh-22"
echo "  journalctl -u employee-docs-bot-afh-22 -f"
echo ""
echo "  # Prod instance (Edmonds Villa — from /opt)"
echo "  sudo systemctl {start|stop|restart} employee-docs-bot-edmonds-villa"
echo "  journalctl -u employee-docs-bot-edmonds-villa -f"
echo ""
echo "  # Or use the scripts in deploy/"
echo "  ./deploy/start-all.sh   ./deploy/stop-all.sh   ./deploy/status.sh"
echo ""
