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

New clients can be added in two ways, depending on whether they need their own Telegram bot identity or can share an existing one.

### Option A: New Client, New Instance (recommended for production)

Each production client gets its own isolated instance with unique API keys. This follows the isolation principle.

#### Phase 1: Dev (subrepo)

Develop and test in the dev environment first:

1. **Add the client to the dev config** — edit `~/github/ai-os/subrepos/employee-docs-bot/config.json`:
   ```json
   {
     "chat_id": -1001234567890,
     "name": "New Client Name",
     "drive_root_id": "<google-drive-folder-id>",
     "service_account_key_file": ".service-account-keys/client-name-sa.json",
     "provider_name": "Provider Name",
     "cat_keywords": { ... },
     "providers": [ ... ]
   }
   ```
2. **Add the test bot to the new client's Telegram chat** — the test bot (`8669...`) must be added to the chat to receive messages.
3. **Restart the dev service** — `./deploy/restart-afh-22.sh`
4. **Test** — send a document to the chat and verify it classifies correctly.

#### Phase 2: Production

Once dev testing is clean, promote to production:

1. **Provision API keys for the new instance:**
   - Register a new Telegram bot via [BotFather](https://t.me/BotFather) → get a unique token
   - Create a unique Anthropic API key from [console.anthropic.com](https://console.anthropic.com/settings/keys)
   - Set up a heartbeat URL at [healthchecks.io](https://healthchecks.io) (or reuse pattern)

2. **Deploy code to `/opt`** — sync the subrepo code to `/opt/employee-docs-bot/`:
   ```bash
   rsync -av --exclude='.env*' --exclude='.venv' \
     ~/github/ai-os/subrepos/employee-docs-bot/ \
     /opt/employee-docs-bot/
   ```

3. **Create env file** — `/opt/employee-docs-bot/.env.{client-name}`:
   ```ini
   # Telegram - Production bot for Client Name
   TELEGRAM_BOT_TOKEN=<telegram-bot-token>

   # Anthropic - Client Name prod instance (unique key)
   ANTHROPIC_VISION_API_KEY=<anthropic-api-key>

   # Heartbeat — healthchecks.io (Client Name prod, 5-min interval)
   HEARTBEAT_URL=https://hc-ping.com/<uuid>
   ```

4. **Add client to prod config** — edit `/opt/employee-docs-bot/config.json` with the client entry (same structure as dev, but production `chat_id` and drive folder).

5. **Install the service** — create `/etc/systemd/system/employee-docs-bot-{client-name}.service`:
   ```ini
   [Unit]
   Description=Employee Docs Bot — Client Name (Production)
   Documentation=https://github.com/omega-michael-1999/employee-docs-bot
   After=network.target

   [Service]
   Type=simple
   User=michael
   WorkingDirectory=/opt/employee-docs-bot
   ExecStart=/opt/employee-docs-bot/.venv/bin/python3 bot.py
   Restart=always
   RestartSec=10
   EnvironmentFile=/opt/employee-docs-bot/.env.{client-name}
   StandardOutput=journal
   StandardError=journal

   [Install]
   WantedBy=multi-user.target
   ```

6. **Reload and enable**:
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable employee-docs-bot-{client-name}
   sudo systemctl start employee-docs-bot-{client-name}
   ```

7. **Add passwordless sudo** — create `/etc/sudoers.d/employee-docs-bot-{client-name}`:
   ```bash
   michael ALL=(root) NOPASSWD: /usr/bin/systemctl start employee-docs-bot-{client-name}
   michael ALL=(root) NOPASSWD: /usr/bin/systemctl stop employee-docs-bot-{client-name}
   michael ALL=(root) NOPASSWD: /usr/bin/systemctl restart employee-docs-bot-{client-name}
   michael ALL=(root) NOPASSWD: /usr/bin/systemctl status employee-docs-bot-{client-name}
   ```

8. **Add the production bot to the target Telegram chat** — the new bot must be added as a member of the chat it will serve.

9. **Verify** — check logs: `journalctl -u employee-docs-bot-{client-name} -f`

10. **Create deploy scripts** — add start/stop/restart/{client-name}.sh scripts in the subrepo `deploy/` folder following the existing pattern, then update `restart-all.sh` and `status.sh` to include the new instance.

### Option B: Add Client to Existing Instance

Simpler — just adds a new client to an already-running bot:

1. Add the client entry to the instance's `config.json`
2. Restart the service
3. Add the bot to the client's Telegram chat

Use this when the client can share an existing Telegram bot identity. The isolation trade-off is that API key usage metrics will aggregate all clients under that instance.

## Promoting Dev Changes to Production

Code changes are developed in the subrepo (dev instance) and promoted to `/opt/` (production instances) when stable:

```bash
# From the subrepo
rsync -av --exclude='.env*' --exclude='.venv' --exclude='.git' --exclude='.gitignore' \
  ~/github/ai-os/subrepos/employee-docs-bot/ \
  /opt/employee-docs-bot/

# Restart all prod instances
~/github/ai-os/subrepos/employee-docs-bot/deploy/restart-all.sh

# Or restart a single prod instance
sudo systemctl restart employee-docs-bot-edmonds-villa
```

> `rsync` is used rather than `cp` because it's incremental — only changed files are copied. The `--exclude` flags ensure env files, venvs, and git metadata stay local to each environment.

## Hygiene

- **Never share API keys across instances.** If usage spikes, unique keys let you identify and fix the offender without touching other clients.
- **The subrepo `.env.afh-22` is gitignored** — it won't be committed. It's local to this server.
- **Restart dev after code changes:** `sudo systemctl restart employee-docs-bot-afh-22`
- **Promote to prod:** copy updated code to `/opt/employee-docs-bot/`, then restart the prod service.
