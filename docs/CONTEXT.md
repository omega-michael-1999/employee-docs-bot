# Employee Docs Bot — Glossary

## Domain Terms

| Term | Definition |
|------|-----------|
| **Client** | An adult family home (AFH) using the bot. Each has its own Telegram chat, Google Drive folder, and service account. Config-driven in `config.json`. |
| **Document** | A single file sent to the Telegram channel — photo, PDF, or DOCX. Each processed independently even if sent in a batch. |
| **Sandra** | Primary human user. The bot's confirmation flow is designed around her phone-based workflow. |
| **New Employee** | A name detected in a document that doesn't match any folder in the client's Drive roster. Triggers onboarding flow. |

## Architecture

| Term | Decision |
|------|----------|
| **Bot Runtime** | Single Python script using `python-telegram-bot`, runs as a systemd service on the Beelink server (hive). |
| **Document Classification** | Hybrid: rules-based matching first (employee name + document type keywords), falls back to DeepSeek LLM call for ambiguous cases. |
| **OCR / Text Extraction** | `doc-extract.py` — forked into the bot repo from ai-os. Uses PyMuPDF + Anthropic Haiku vision API for scanned docs. |
| **Drive Auth** | Google service account. One per client. Never expires, no interactive login. |
| **Drive API** | Direct `google-api-python-client` calls, not `gws` CLI. |
| **Confirmation UX** | Inline keyboard buttons [👍 Yes] [👎 No]. Correction via two sequential text prompts: first the employee name, then the document type. |
| **Employee Roster** | Scanned from Drive folder names at runtime. New names (not in any folder) trigger the "new employee?" onboarding question. |
| **Multi-Tenancy** | Single bot binary. Client config in `config.json` keyed by Telegram chat_id. |

## WAC Categories (8)

| Code | Name |
|------|------|
| 01 | Identity & Employment |
| 02 | Background Check |
| 03 | Health Screening (TB) |
| 04 | CPR & First Aid |
| 05 | Orientation & Training |
| 06 | HCA Certification & CE |
| 07 | Nurse Delegation |
| 08 | Administrator Training (provider only) |

## File Naming

`{Employee Full Name} - {Document Description}.{ext}`
