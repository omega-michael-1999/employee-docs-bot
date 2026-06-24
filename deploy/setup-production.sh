#!/usr/bin/env bash
set -euo pipefail

# Each AFH client gets their own named instance: employee-docs-bot-{client-name}
# This script sets up the Edmonds Villa instance.
# For future clients: copy this script, change the name and .env file.

CLIENT="edmonds-villa"
SERVICE="employee-docs-bot-${CLIENT}"
ENV_FILE="/opt/employee-docs-bot/.env.${CLIENT}"

echo "==> Creating service file for ${SERVICE}..."

sudo tee "/etc/systemd/system/${SERVICE}.service" > /dev/null << SERVICE
[Unit]
Description=Employee Docs Telegram Bot — Edmonds Villa
Documentation=https://github.com/omega-michael-1999/employee-docs-bot
After=network.target

[Service]
Type=simple
User=michael
WorkingDirectory=/opt/employee-docs-bot
ExecStart=/opt/employee-docs-bot/.venv/bin/python3 bot.py
Restart=always
RestartSec=10
EnvironmentFile=${ENV_FILE}
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
SERVICE

echo "==> Setting up passwordless sudo for ${SERVICE}..."

sudo tee "/etc/sudoers.d/${SERVICE}" > /dev/null << SUDOERS
michael ALL=(root) NOPASSWD: /usr/bin/systemctl start ${SERVICE}
michael ALL=(root) NOPASSWD: /usr/bin/systemctl stop ${SERVICE}
michael ALL=(root) NOPASSWD: /usr/bin/systemctl restart ${SERVICE}
michael ALL=(root) NOPASSWD: /usr/bin/systemctl status ${SERVICE}
SUDOERS

echo "==> Reloading systemd and enabling service..."

sudo systemctl daemon-reload
sudo systemctl enable "${SERVICE}"

echo ""
echo "Done. Manage this instance with:"
echo "  sudo systemctl start ${SERVICE}"
echo "  sudo systemctl status ${SERVICE}"
echo "  sudo systemctl stop ${SERVICE}"
echo ""
echo "All instances on this server:"
echo "  sudo systemctl status employee-docs-bot                # test (AFH_22)"
echo "  sudo systemctl status ${SERVICE}                       # ${CLIENT}"
echo ""
echo "Logs: journalctl -u ${SERVICE} -f"
