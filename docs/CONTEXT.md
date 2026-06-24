# Employee Docs Bot — Glossary

## Domain Terms

| Term | Definition |
|------|-----------|
| **Client** | An adult family home (AFH) using the bot. Each has its own Telegram chat and Google Drive folder. Config-driven in `config.json`. |
| **Document** | A single file sent to the Telegram channel — photo, PDF, or DOCX. Each processed independently even if sent in a batch. |
| **Sandra** | Primary human user. The bot's confirmation flow is designed around her phone-based workflow. |
| **New Employee** | A name detected in a document that doesn't match any folder in the client's Drive roster. Triggers onboarding flow. |

## Architecture

| Term | Decision |
|------|----------|
| **Bot Runtime** | Single Python script using `python-telegram-bot`. One systemd service per Telegram bot token (test + production), each sharing the same `config.json`. |
| **Document Classification** | Three-tier: (1) rules keyword match with word-boundary checks, (2) if employee or category is ambiguous (partial name, weak keyword, multiple candidates) the rules result is treated as a hint and elevated to DeepSeek LLM, (3) if LLM also fails → manual inline-keyboard correction flow. Rules never bypass the LLM when confidence is low. |
| **OCR / Text Extraction** | `doc-extract.py` — forked into the bot repo from ai-os. Uses PyMuPDF + Anthropic Haiku vision API for scanned docs. |
| **Drive Auth** | Single Google service account shared by all clients. Access is controlled at the Drive folder level (each client's folder shared individually). No interactive login needed. |
| **Drive API** | Direct `google-api-python-client` calls, not `gws` CLI. |
| **Confirmation UX** | Inline keyboard buttons [👍 Yes] [👎 No]. Correction via two sequential text prompts: first the employee name, then the document type. |
| **Employee Roster** | Scanned from Drive folder names at runtime. New names (not in any folder) trigger the "new employee?" onboarding question. Providers are flagged in `config.json` for audit purposes. |
| **Provider vs. Caregiver** | No structural folder split. Filing uses the same 8-category structure for everyone. Config marks provider names (`"providers": ["Sandra Namwase"]`). Audit checks providers against categories 01–08 + facility-level docs (insurance, succession plan, emergency plan). Caregivers checked against 01–07 only. |
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
