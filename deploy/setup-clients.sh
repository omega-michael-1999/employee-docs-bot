#!/usr/bin/env bash
set -euo pipefail

# Each AFH client gets their own named instance: employee-docs-bot-{client-name}
# Usage: ./setup-clients.sh
# Run this once to set up all current clients.

echo "========================================"
echo " Setting up all AFH client instances"
echo "========================================"

# --- Client 1: AFH_22 ---
CLIENT="afh-22"
SERVICE="employee-docs-bot-${CLIENT}"
ENV_FILE="/opt/employee-docs-bot/.env"

# Stop existing generic service if it exists
if systemctl is-active --quiet employee-docs-bot 2>/dev/null; then
  echo "==> Stopping old generic service..."
  sudo systemctl stop employee-docs-bot
fi
if systemctl is-enabled --quiet employee-docs-bot 2>/dev/null; then
  echo "==> Disabling old generic service..."
  sudo systemctl disable employee-docs-bot
fi

echo "==> Creating service file for ${SERVICE}..."
sudo tee "/etc/systemd/system/${SERVICE}.service" > /dev/null << SERVICE
[Unit]
Description=Employee Docs Bot — AFH_22
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

sudo systemctl daemon-reload
sudo systemctl enable "${SERVICE}"

# --- Client 2: Edmonds Villa ---
CLIENT2="edmonds-villa"
SERVICE2="employee-docs-bot-${CLIENT2}"
ENV_FILE2="/opt/employee-docs-bot/.env.${CLIENT2}"

echo "==> Creating service file for ${SERVICE2}..."
sudo tee "/etc/systemd/system/${SERVICE2}.service" > /dev/null << SERVICE2
[Unit]
Description=Employee Docs Bot — Edmonds Villa
Documentation=https://github.com/omega-michael-1999/employee-docs-bot
After=network.target

[Service]
Type=simple
User=michael
WorkingDirectory=/opt/employee-docs-bot
ExecStart=/opt/employee-docs-bot/.venv/bin/python3 bot.py
Restart=always
RestartSec=10
EnvironmentFile=${ENV_FILE2}
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
SERVICE2

echo "==> Setting up passwordless sudo for ${SERVICE2}..."
sudo tee "/etc/sudoers.d/${SERVICE2}" > /dev/null << SUDOERS2
michael ALL=(root) NOPASSWD: /usr/bin/systemctl start ${SERVICE2}
michael ALL=(root) NOPASSWD: /usr/bin/systemctl stop ${SERVICE2}
michael ALL=(root) NOPASSWD: /usr/bin/systemctl restart ${SERVICE2}
michael ALL=(root) NOPASSWD: /usr/bin/systemctl status ${SERVICE2}
SUDOERS2

sudo systemctl daemon-reload
sudo systemctl enable "${SERVICE2}"

# --- Remove old generic service file ---
if [ -f /etc/systemd/system/employee-docs-bot.service ]; then
  echo "==> Removing old generic service file..."
  sudo rm /etc/systemd/system/employee-docs-bot.service
  sudo systemctl daemon-reload
fi

# --- Cleanup old sudoers if exists ---
if [ -f /etc/sudoers.d/employee-docs-bot ]; then
  echo "==> Removing old generic sudoers..."
  sudo rm /etc/sudoers.d/employee-docs-bot
fi

echo ""
echo "========================================"
echo " All clients set up. Manage with:"
echo "========================================"
echo ""
echo "  sudo systemctl start employee-docs-bot-afh-22        # AFH_22"
echo "  sudo systemctl start employee-docs-bot-edmonds-villa # Edmonds Villa"
echo ""
echo "  sudo systemctl status employee-docs-bot-afh-22"
echo "  sudo systemctl status employee-docs-bot-edmonds-villa"
echo ""
echo "  journalctl -u employee-docs-bot-afh-22 -f"
echo "  journalctl -u employee-docs-bot-edmonds-villa -f"
echo ""
echo " To add a new client later, duplicate the pattern:"
echo "  - Create .env.{client-name}"
echo "  - Copy this script and change the name"
