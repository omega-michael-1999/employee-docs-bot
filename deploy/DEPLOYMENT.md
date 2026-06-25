# Employee Docs Bot — Deployment Architecture

## Overview

The Employee Docs Bot runs as **two separate systemd services** on this server (hive), one per client. Each instance is isolated with its own API keys, working directory, and Telegram bot identity.

| Instance | Type | Service Name | Working Directory | Env File | Telegram Token |
|----------|------|-------------|-------------------|----------|---------------|
| AFH_22 | Dev/Test | `employee-docs-bot-afh-22` | `~/github/ai-os/subrepos/employee-docs-bot/` | `.env.afh-22` (in subrepo) | Test bot: `8669...` |
| Edmonds Villa | Production | `employee-docs-bot-edmonds-villa` | `/opt/employee-docs-bot/` | `.env.edmonds-villa` | Prod bot: `8870...` |

## Architecture Principles

### 1. Dev/Prod Separation

- **AFH_22 (dev) runs from the git subrepo.** Code changes are developed here. The service runs directly from the working tree so changes take effect on restart. No deployment step needed for dev.

- **Edmonds Villa (prod) runs from `/opt/employee-docs-bot/`.** This is the stable deployment. Code is deployed here manually after testing on dev, then the service is restarted.

### 2. API Key Isolation (per client)

Every client gets unique API keys. Current state:

| Key Type | Dev (AFH_22) | Prod (Edmonds Villa) |
|----------|-------------|---------------------|
| Telegram Bot Token | `8669018731:AAEA...` (test bot) | `8870362473:AAGz...` (prod bot) |
| Anthropic API Key | `sk-ant-api03-l8z0...` | `sk-ant-api03-l8z0...` (**SHARED — needs separate key**) |
| Heartbeat URL | `hc-ping.com/66c1...` | `hc-ping.com/a462...` |

### 3. Service File Locations

- Dev: `/etc/systemd/system/employee-docs-bot-afh-22.service`
- Prod: `/etc/systemd/system/employee-docs-bot-edmonds-villa.service`

### 4. Config (`config.json`)

Each instance has its own `config.json` defining the clients it serves:

- **Dev (AFH_22)**: `~/github/ai-os/subrepos/employee-docs-bot/config.json` — serves AFH_22 test chat. Uses the test Telegram bot token, so it only receives messages from test channels.

- **Prod (Edmonds Villa)**: `/opt/employee-docs-bot/config.json` — serves the Edmonds Villa chat. Uses the production bot token.

> **Important:** Currently both config files list both clients. The Telegram bot token is the actual access control — each bot only receives messages sent to it. The config's `chat_id` fields must match the chats each bot is a member of.

## Management Commands

### Start/Stop/Restart

Use the scripts in `deploy/`:

```bash
# Start all instances
./deploy/start-all.sh

# Stop all instances
./deploy/stop-all.sh

# Restart all instances
./deploy/restart-all.sh

# Individual instances
./deploy/start-afh-22.sh
./deploy/stop-edmonds-villa.sh
```

Or directly via systemctl:

```bash
sudo systemctl restart employee-docs-bot-afh-22
sudo systemctl restart employee-docs-bot-edmonds-villa
```

### View Logs

```bash
# Dev logs
journalctl -u employee-docs-bot-afh-22 -f

# Prod logs
journalctl -u employee-docs-bot-edmonds-villa -f
```

## Adding a New Client

1. Register a new Telegram bot via BotFather — get a unique token
2. Provision a unique Anthropic API key from console.anthropic.com
3. Create a config entry in `config.json` for the new client
4. Create `.env.{client-name}` with the new keys
5. Create a new systemd service file following the pattern
6. Add passwordless sudo rules for the new service
7. Add the bot to the target Telegram chat

## Hygiene

- **Never share API keys across instances.** If usage spikes, unique keys let you identify and fix the offender without touching other clients.
- **The subrepo `.env.afh-22` is gitignored** — it won't be committed. It's local to this server.
- **Restart dev after code changes:** `sudo systemctl restart employee-docs-bot-afh-22`
- **Promote to prod:** copy updated code to `/opt/employee-docs-bot/`, then restart the prod service.
