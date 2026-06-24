# Handoff — Employee Docs Bot

**Date:** 2026-06-24 (Updated)
**Status:** Deployed to hive, systemd service ready, awaiting first document test.

---

## What's Built & Deployed

### 1. Google Service Account (✅ Complete)
- SA `employee-docs-bot@claude-ai-474917.iam.gserviceaccount.com` created in `claude-ai-474917` project
- JSON key at `.service-account-keys/edmonds-villa-sa.json`
- Drive API enabled for project
- SA granted **Editor** access to both Drive roots:
  - **Edmonds Villa:** `EMPLOYEE RECORDS` folder (`1V-pKZ5-MEHJLlw6ZqHTB6zuapULJ9XOK`)
  - **AFH_22 (test):** `Employee Records` folder (`1KQ3fGvsCwRPeDvsCXj-Yltte2z_jXDmU`)

### 2. Bot Deployment (✅ Complete)
| Item | Detail |
|------|--------|
| **Location** | `/opt/employee-docs-bot/` (git clone from `omega-michael-1999/employee-docs-bot`) |
| **System user** | `docsbot` (dedicated service account) |
| **Python venv** | `/opt/employee-docs-bot/.venv/` with all deps |
| **Service file** | `/etc/systemd/system/employee-docs-bot.service` (daemon-reloaded) |
| **Config** | `config.json` with **2 clients** (Edmonds Villa + AFH_22 test) |
| **SA key** | `/opt/employee-docs-bot/.service-account-keys/edmonds-villa-sa.json` |
| **.env** | Test bot token active, DeepSeek key set, Anthropic vision key empty |

### 3. Two Clients Configured

| Client | Chat ID | Bot Token | Drive Root |
|--------|---------|-----------|------------|
| Edmonds Villa | `-1004370903054` | `8870362473:AAGzohk-Q5t8R9QKORtbgwiB3siKO_Qltnk` | `1V-pKZ5-MEHJLlw6ZqHTB6zuapULJ9XOK` |
| AFH_22 (Test) | `-1004391863263` | `8669018731:AAEAJCRcIb44t-RGwY3LsRhTEx3jGm7BIDk` | `1KQ3fGvsCwRPeDvsCXj-Yltte2z_jXDmU` |

**Note:** The `.env` currently has the **test bot token**. To run Edmonds Villa production, switch to the production token and run a second instance (or swap).

### 4. AFH_22 Test Structure Created
- `CAREGIVERS/Test Employee, CNA/` folder with 7 WAC category subfolders
- Ready for document filing tests

---

## What's Left

### 1. First Document Test
- Start the service: `sudo systemctl start employee-docs-bot`
- Send a test document (photo of CPR card, license, etc.) to the `afh-22-employee-docs` channel
- Verify:
  - Bot extracts text
  - Classifies employee + document type
  - Confirmation buttons appear
  - Files to correct Drive folder
- Then repeat for `edmonds-villa-employee-docs` channel

### 2. Production Switch / Multi-Instance
Option A (simple): Swap `.env` token when ready for Edmonds Villa live use
Option B (better): Create a second systemd service for the production bot so both run:
```bash
sudo cp /etc/systemd/system/employee-docs-bot.service /etc/systemd/system/employee-docs-bot-prod.service
# Edit the prod service to:
#   - Use different .env file with production token
#   - Different Description
sudo systemctl daemon-reload
```

### 3. Anthropic Vision Key
`ANTHROPIC_VISION_API_KEY` is empty in `.env`. OCR on scanned PDFs and photos **will fail** without it. Options:
- Get a real Anthropic API key for the Haiku vision API
- Or modify `doc-extract.py` to use DeepSeek's vision endpoint (since the environment routes through DeepSeek)

### 4. Chat IDs for Production
Both chat IDs are confirmed and in `config.json`.

---

## Key Locations

| What | Path |
|------|------|
| Bot code | `/opt/employee-docs-bot/` |
| Config | `/opt/employee-docs-bot/config.json` |
| SA key | `/opt/employee-docs-bot/.service-account-keys/edmonds-villa-sa.json` |
| Service file | `/etc/systemd/system/employee-docs-bot.service` |
| Logs | `journalctl -u employee-docs-bot -f` |

## Env Vars

| Variable | In `.env`? | Notes |
|----------|-----------|-------|
| `TELEGRAM_BOT_TOKEN` | ✅ Set (test bot) | Swap for production |
| `DEEPSEEK_API_KEY` | ✅ Set | `sk-29ab7a41719046d9930c18853828cbc0` |
| `ANTHROPIC_VISION_API_KEY` | ❌ Empty | Needed for scanned doc OCR |

---

## Files

- `bot.py` — Main bot script
- `scripts/doc-extract.py` — Text extraction (PDF, DOCX, images)
- `deploy/employee-docs-bot.service` — systemd unit
- `docs/CONTEXT.md` — Architecture glossary
- `docs/HANDOFF.md` — This file
