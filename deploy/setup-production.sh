#!/usr/bin/env bash
set -euo pipefail

echo "==> Creating production service file..."

sudo tee /etc/systemd/system/employee-docs-bot-prod.service > /dev/null << 'SERVICE'
[Unit]
Description=Employee Docs Telegram Bot — Edmonds Villa (Production)
After=network.target

[Service]
Type=simple
User=michael
WorkingDirectory=/opt/employee-docs-bot
ExecStart=/opt/employee-docs-bot/.venv/bin/python3 bot.py
Restart=always
RestartSec=10
EnvironmentFile=/opt/employee-docs-bot/.env.prod
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
SERVICE

echo "==> Setting up passwordless sudo for production service..."

sudo tee /etc/sudoers.d/employee-docs-bot-prod > /dev/null << 'SUDOERS'
michael ALL=(root) NOPASSWD: /usr/bin/systemctl start employee-docs-bot-prod
michael ALL=(root) NOPASSWD: /usr/bin/systemctl stop employee-docs-bot-prod
michael ALL=(root) NOPASSWD: /usr/bin/systemctl restart employee-docs-bot-prod
michael ALL=(root) NOPASSWD: /usr/bin/systemctl status employee-docs-bot-prod
SUDOERS

echo "==> Reloading systemd and enabling service..."

sudo systemctl daemon-reload
sudo systemctl enable employee-docs-bot-prod

echo ""
echo "Done. You can now start the production bot with:"
echo "  sudo systemctl start employee-docs-bot-prod"
echo ""
echo "Both instances running:"
echo "  sudo systemctl status employee-docs-bot     # test (AFH_22)"
echo "  sudo systemctl status employee-docs-bot-prod # production (Edmonds Villa)"
