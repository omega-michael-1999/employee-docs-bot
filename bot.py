#!/usr/bin/env python3
"""Employee Docs Bot — Telegram bot for filing AFH employee documents.

Receives documents in a Telegram channel, extracts text via doc-extract.py,
classifies by employee and WAC category, confirms with user via inline buttons,
and files into the correct Google Drive folder.

Designed for multi-tenant use. Each client (AFH) has a config entry mapping
their chat_id to their Drive folder and service account.
"""

import os, sys, re, json, logging, tempfile, subprocess, io, sqlite3, asyncio, uuid
from pathlib import Path
from datetime import datetime, timedelta
from enum import Enum, auto
from dataclasses import dataclass, field

# Supported file extensions for document processing
SUPPORTED_EXTS = {".pdf", ".jpg", ".jpeg", ".png", ".heic", ".heif", ".docx", ".txt"}
MAX_FILE_SIZE_BYTES = 20 * 1024 * 1024  # 20 MB

# --- Config ---
CONFIG_FILE = Path(__file__).parent / "config.json"
if not CONFIG_FILE.exists():
    CONFIG_FILE = Path(__file__).parent / "config.example.json"
    print(f"WARNING: Using config.example.json. Copy to config.json and configure.", file=sys.stderr)

with open(CONFIG_FILE) as f:
    CONFIG = json.load(f)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_VISION_API_KEY", "")

# Heartbeat monitoring (push-based — bot pings this URL every 5 min)
HEARTBEAT_URL = os.environ.get("HEARTBEAT_URL", "")

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=logging.INFO,
    handlers=[logging.StreamHandler()]
)
log = logging.getLogger("docs-bot")


def generate_doc_id() -> str:
    """Generate a short unique document identifier for tracing."""
    return "doc_" + uuid.uuid4().hex[:8]


class DocLogger(logging.LoggerAdapter):
    """Logger adapter that prefixes messages with a document ID."""

    def process(self, msg, kwargs):
        doc_id = self.extra.get("doc_id", "")
        if doc_id:
            return f"[{doc_id}] {msg}", kwargs
        return msg, kwargs


# --- State Machine ---

class ChatState(Enum):
    """Explicit states for per-chat document processing state machine."""
    IDLE = auto()
    AWAITING_CONFIRMATION = auto()
    AWAITING_EMPLOYEE_CORRECTION = auto()
    AWAITING_DOCUMENT_TYPE = auto()
    FILING = auto()


@dataclass
class ChatSession:
    """Per-chat session state for one document in flight."""
    chat_id: int
    state: ChatState
    message_id: int = 0
    file_path: str = ""
    file_name: str = ""
    text: str = ""
    employee: str = ""
    category: str = ""
    description: str = ""
    client: dict | None = None
    employees: dict | None = None
    doc_id: str = ""
    awaiting: str = ""
    created_at: datetime | None = None


DB_DIR = Path(__file__).parent / "data"
DB_PATH = DB_DIR / "pending.db"

chat_states: dict[int, ChatSession] = {}    # chat_id -> single active session
chat_locks: dict[int, asyncio.Lock] = {}    # per-chat mutex


def init_db(db_path: str | Path | None = None) -> str:
    """Initialise the SQLite database and create the sessions table."""
    if db_path is None:
        db_path = DB_PATH
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            chat_id INTEGER PRIMARY KEY,
            message_id INTEGER DEFAULT 0,
            state TEXT NOT NULL,
            file_path TEXT DEFAULT '',
            file_name TEXT DEFAULT '',
            text TEXT DEFAULT '',
            employee TEXT DEFAULT '',
            category TEXT DEFAULT '',
            description TEXT DEFAULT '',
            doc_id TEXT DEFAULT '',
            awaiting TEXT DEFAULT '',
            created_at TEXT DEFAULT ''
        )
    """)
    conn.commit()
    conn.close()
    return str(db_path)


def _session_to_row(session: ChatSession) -> dict:
    return dict(
        chat_id=session.chat_id,
        message_id=session.message_id,
        state=session.state.name,
        file_path=session.file_path,
        file_name=session.file_name,
        text=session.text,
        employee=session.employee,
        category=session.category,
        description=session.description,
        doc_id=session.doc_id,
        awaiting=session.awaiting,
        created_at=session.created_at.isoformat() if session.created_at else "",
    )


def _row_to_session(row: sqlite3.Row) -> ChatSession:
    created = None
    if row["created_at"]:
        try:
            created = datetime.fromisoformat(row["created_at"])
        except (ValueError, TypeError):
            created = None
    return ChatSession(
        chat_id=row["chat_id"],
        message_id=row["message_id"],
        state=ChatState[row["state"]],
        file_path=row["file_path"],
        file_name=row["file_name"],
        text=row["text"],
        employee=row["employee"],
        category=row["category"],
        description=row["description"],
        doc_id=row["doc_id"],
        awaiting=row["awaiting"],
        created_at=created,
    )


def save_session(db_path: str | Path, session: ChatSession) -> None:
    """Upsert a chat session into the database."""
    row = _session_to_row(session)
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        INSERT OR REPLACE INTO sessions
            (chat_id, message_id, state, file_path, file_name, text,
             employee, category, description, doc_id, awaiting, created_at)
        VALUES
            (:chat_id, :message_id, :state, :file_path, :file_name, :text,
             :employee, :category, :description, :doc_id, :awaiting, :created_at)
    """, row)
    conn.commit()
    conn.close()


def load_session(db_path: str | Path, chat_id: int) -> ChatSession | None:
    """Load a session by chat_id, or None if not found."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    cur = conn.execute("SELECT * FROM sessions WHERE chat_id = ?", (chat_id,))
    row = cur.fetchone()
    conn.close()
    if row is None:
        return None
    return _row_to_session(row)


def delete_session(db_path: str | Path, chat_id: int) -> None:
    """Delete a session from the database."""
    conn = sqlite3.connect(str(db_path))
    conn.execute("DELETE FROM sessions WHERE chat_id = ?", (chat_id,))
    conn.commit()
    conn.close()


def cleanup_old_sessions(db_path: str | Path, max_age_hours: int = 24) -> int:
    """Delete sessions older than max_age_hours. Returns count removed."""
    cutoff = datetime.now() - timedelta(hours=max_age_hours)
    conn = sqlite3.connect(str(db_path))
    cur = conn.execute("DELETE FROM sessions WHERE created_at != '' AND created_at < ?", (cutoff.isoformat(),))
    removed = cur.rowcount
    conn.commit()
    conn.close()
    return removed


def get_chat_lock(chat_id: int) -> asyncio.Lock:
    """Get or create a per-chat asyncio.Lock."""
    if chat_id not in chat_locks:
        chat_locks[chat_id] = asyncio.Lock()
    return chat_locks[chat_id]


# --- Roster Cache ---

class RosterCache:
    """In-memory cache for employee rosters with TTL-based expiry.

    Each client (drive_root_id) has an independent cache entry.
    On cache miss or TTL expiry, the fetch callback is called
    to get fresh data from Drive.
    """

    def __init__(self, ttl_seconds: int = 1800):
        self._ttl = ttl_seconds
        self._data: dict[str, dict] = {}        # drive_root_id -> roster dict
        self._timestamps: dict[str, float] = {}  # drive_root_id -> time of fetch

    def get(self, drive_root_id: str, fetch_callable) -> dict:
        """Return cached roster, or call fetch_callable on miss/expiry."""
        import time
        now = time.time()
        cached = self._data.get(drive_root_id)
        last_fetch = self._timestamps.get(drive_root_id, 0)

        if cached is not None and (now - last_fetch) < self._ttl:
            return cached

        # Cache miss or expired — fetch fresh data
        fresh = fetch_callable()
        self._data[drive_root_id] = fresh
        self._timestamps[drive_root_id] = time.time()
        return fresh


# Shared roster cache instance (one per process, 30-min TTL)
_roster_cache = RosterCache(ttl_seconds=1800)

# --- Temp File Registry ---
_temp_files: set[str] = set()


def register_temp_file(path: str) -> None:
    """Register a temp file path for tracking and cleanup."""
    _temp_files.add(path)


def unregister_temp_file(path: str) -> None:
    """Remove a temp file from tracking (after successful cleanup)."""
    _temp_files.discard(path)


def cleanup_stale_temp_files(max_age_hours: int = 24) -> int:
    """Remove tracked temp files older than max_age_hours. Returns count removed."""
    import time
    now = time.time()
    removed = 0
    for path in list(_temp_files):
        try:
            mtime = os.path.getmtime(path)
            if now - mtime > max_age_hours * 3600:
                os.unlink(path)
                _temp_files.discard(path)
                removed += 1
        except (FileNotFoundError, OSError):
            _temp_files.discard(path)
            continue
    return removed


def get_roster_cache(cache: RosterCache, drive_root_id: str, list_fn) -> dict:
    """Convenience wrapper: get roster from cache, calling list_fn on miss."""
    return cache.get(drive_root_id, list_fn)


# --- Google Drive helpers ---
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseUpload

def get_drive_service(sa_key_path):
    """Build a Google Drive service from a service account key file."""
    creds = service_account.Credentials.from_service_account_file(
        sa_key_path,
        scopes=["https://www.googleapis.com/auth/drive"]
    )
    return build("drive", "v3", credentials=creds)

def list_employee_folders(drive, parent_id):
    """List folder names under CAREGIVERS/ in the parent drive folder."""
    # Find CAREGIVERS folder
    results = drive.files().list(
        q=f"'{parent_id}' in parents and mimeType='application/vnd.google-apps.folder' and name='CAREGIVERS'",
        supportsAllDrives=True, includeItemsFromAllDrives=True,
        fields="files(id)"
    ).execute()
    folders = results.get("files", [])
    if not folders:
        return []
    caregivers_id = folders[0]["id"]

    # List employee folders
    results = drive.files().list(
        q=f"'{caregivers_id}' in parents and mimeType='application/vnd.google-apps.folder'",
        supportsAllDrives=True, includeItemsFromAllDrives=True,
        fields="files(id,name)"
    ).execute()
    employees = {}
    for f in results.get("files", []):
        employees[f["name"].lower()] = {"id": f["id"], "name": f["name"]}
    return employees

def find_category_folder(drive, emp_folder_id, cat_name):
    """Find or create a category subfolder inside an employee folder."""
    results = drive.files().list(
        q=f"'{emp_folder_id}' in parents and mimeType='application/vnd.google-apps.folder' and name='{cat_name}'",
        supportsAllDrives=True, includeItemsFromAllDrives=True,
        fields="files(id)"
    ).execute()
    folders = results.get("files", [])
    if folders:
        return folders[0]["id"]

    # Create the folder
    metadata = {"name": cat_name, "parents": [emp_folder_id], "mimeType": "application/vnd.google-apps.folder"}
    folder = drive.files().create(body=metadata, supportsAllDrives=True).execute()
    return folder["id"]

def upload_file(drive, parent_id, file_path, file_name, mime_type="application/pdf"):
    """Upload a file to a Drive folder."""
    media = MediaFileUpload(file_path, mimetype=mime_type, resumable=True)
    metadata = {"name": file_name, "parents": [parent_id]}
    file = drive.files().create(body=metadata, media_body=media, supportsAllDrives=True).execute()
    return file["id"]

# --- Classification ---
WAC_CATEGORIES = [
    "01 - Identity & Employment", "02 - Background Check", "03 - Health Screening",
    "04 - CPR & First Aid", "05 - Orientation & Training", "06 - HCA Certification & CE",
    "07 - Nurse Delegation", "08 - Administrator Training"
]

def _word_boundary_match(needle, haystack):
    """Check if needle appears as a whole word in haystack."""
    if not needle or not haystack:
        return False
    try:
        pattern = r'(?<![a-zA-Z])' + re.escape(needle) + r'(?![a-zA-Z])'
        return bool(re.search(pattern, haystack))
    except re.error:
        return needle in haystack


def _emp_confidence(key):
    """High confidence if the name has multiple words (full name), low if single-word."""
    name_part = key.split(",")[0].strip()
    return "high" if " " in name_part else "low"


def _keyword_shared_count(keyword, cat_keywords):
    """Count how many categories a keyword appears in."""
    count = 0
    for kws in cat_keywords.values():
        if keyword in kws:
            count += 1
    return count


def classify_by_rules(text, filename, cat_keywords, employees):
    """Try to classify by keyword matching.

    Returns (employee_name, category, confidence).
    confidence is "high", "low", or None.
    """
    text_lower = text.lower() if text else ""
    fname_lower = filename.lower() if filename else ""
    combined = f"{text_lower} {fname_lower}"

    # Find employee
    emp_match = None
    emp_conf = None
    for key, info in employees.items():
        parts = key.split(",")[0].strip()
        if _word_boundary_match(parts.lower(), combined):
            emp_match = info["name"]
            emp_conf = _emp_confidence(key)
            break

    # Find category and track which keyword matched
    cat_match = None
    cat_conf = None
    matched_kw = None
    for cat, kws in cat_keywords.items():
        for kw in kws:
            if _word_boundary_match(kw.lower(), combined):
                cat_match = cat
                matched_kw = kw
                break
        if cat_match:
            break

    # Determine category confidence
    if cat_match and matched_kw:
        shared = _keyword_shared_count(matched_kw, cat_keywords)
        cat_conf = "low" if shared > 1 else "high"

    # Overall confidence: high only if both emp and cat are high
    if emp_match and cat_match:
        if emp_conf == "high" and cat_conf == "high":
            return emp_match, cat_match, "high"
        else:
            return emp_match, cat_match, "low"

    # Partial match — return what we found, even if one is None
    return emp_match, cat_match, None


def parse_json_from_llm(content: str) -> dict | None:
    """Extract and parse JSON from an LLM response, handling code fences."""
    # Try to find JSON block within ```json ... ``` markers
    fence_match = re.search(r'```(?:json)?\s*\n?({.*?})\s*\n?```', content, re.DOTALL)
    if fence_match:
        try:
            return json.loads(fence_match.group(1))
        except json.JSONDecodeError:
            pass

    # Try bare JSON object (non-greedy outer match)
    json_match = re.search(r'\{(?:[^{}]|(?:\{[^{}]*\}))*\}', content, re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group())
        except json.JSONDecodeError:
            pass

    return None


def classify_by_llm(text, filename, employees, cat_keywords, hint_emp=None, hint_cat=None):
    """Fallback: use Claude Haiku to classify. Optional hints from rules result."""
    if not ANTHROPIC_API_KEY:
        log.warning("ANTHROPIC_VISION_API_KEY not set — skipping LLM classification")
        return None, None

    emp_list = ", ".join(sorted(set(v["name"] for v in employees.values())))
    cat_list = ", ".join(cat_keywords.keys())

    hint_line = ""
    if hint_emp or hint_cat:
        hint_line = f"\nRules suggest: employee={hint_emp or '?'}, category={hint_cat or '?'}. Verify if this is correct."

    prompt = f"""Given this document text, identify:
1. Which employee does this belong to? Choose from: {emp_list}
2. What document type is it? Choose from the categories or describe it.
{hint_line}
Return ONLY valid JSON: {{"employee": "Full Name", "category": "Category Name", "description": "brief description"}}

Document text:
{text[:3000]}"""

    payload = json.dumps({
        "model": "claude-haiku-4-5-20251001",
        "max_tokens": 300,
        "messages": [{"role": "user", "content": prompt}]
    })

    try:
        import urllib.request
        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages",
            data=payload.encode(),
            headers={
                "Content-Type": "application/json",
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
            },
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
        content = data["content"][0]["text"]

        result = parse_json_from_llm(content)
        if result is None:
            log.warning(f"Could not parse JSON from LLM response: {content[:300]}")
            return None, None

        emp = result.get("employee", "")
        cat = result.get("category", "")

        # Validate against known lists
        if cat and cat not in cat_keywords:
            log.info(f"LLM returned unknown category '{cat}' — clearing")
            cat = None
        if emp and emp.lower() not in employees:
            log.info(f"LLM returned unknown employee '{emp}' — clearing")
            emp = None

        return emp, cat

    except Exception as e:
        log.warning(f"LLM classification failed: {e}")

    return None, None


def classify(text, filename, cat_keywords, employees):
    """Three-tier: rules (with confidence) → LLM → manual.

    Returns (employee, category, method) where method is one of
    "rules", "llm", or "failed".
    """
    emp, cat, conf = classify_by_rules(text, filename, cat_keywords, employees)

    # Tier 1: High-confidence rules match — return immediately
    if conf == "high":
        log.info(f"Rules classified (high confidence): {emp} / {cat}")
        return emp, cat, "rules"

    # Tier 2: Low confidence or partial match — elevate to LLM with hint
    if emp or cat:
        log.info(f"Rules classified (low confidence): {emp or '?'} / {cat or '?'} — elevating to LLM")
        emp2, cat2 = classify_by_llm(text, filename, employees, cat_keywords,
                                      hint_emp=emp, hint_cat=cat)
    else:
        emp2, cat2 = classify_by_llm(text, filename, employees, cat_keywords)

    if emp2 or cat2:
        log.info(f"LLM classified: {emp2 or '?'} / {cat2 or '?'}")
        return emp2, cat2, "llm"

    # Tier 3: LLM also failed — manual correction
    log.info("Classification failed — manual correction needed")
    return None, None, "failed"


def is_provider(client, emp_name):
    """Check if an employee is flagged as a provider in the client config."""
    providers = client.get("providers", [])
    return emp_name in providers


# --- Bot ---
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes, JobQueue

# Pending classifications stored in chat_states dict + SQLite (data/pending.db)


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Process a document or photo sent to the channel."""
    chat_id = update.effective_chat.id
    client = next((c for c in CONFIG["clients"] if c["chat_id"] == chat_id), None)
    if not client:
        await update.message.reply_text("This chat is not configured for document filing.")
        return

    # Get file
    file = None
    if update.message.document:
        file = update.message.document
    elif update.message.photo:
        file = update.message.photo[-1]

    if not file:
        return

    # Check file size
    if hasattr(file, "file_size") and file.file_size and file.file_size > MAX_FILE_SIZE_BYTES:
        mb = file.file_size / (1024 * 1024)
        await update.message.reply_text(
            f"❌ This file is too large ({mb:.1f} MB). Maximum file size is 20 MB."
        )
        return

    # Check extension against supported types
    if hasattr(file, "file_name") and file.file_name:
        ext = Path(file.file_name).suffix.lower()
        if ext and ext not in SUPPORTED_EXTS:
            await update.message.reply_text(
                f"❌ This file type is not supported. "
                f"You sent a **{ext[1:].upper()}** file. "
                f"I can only process: PDF, JPEG, PNG, HEIC, DOCX, and TXT files.",
                parse_mode="Markdown"
            )
            return

    # Generate document trace ID
    doc_id = generate_doc_id()
    dlog = DocLogger(log, {"doc_id": doc_id})
    dlog.info("Document received")

    # Download to temp
    tg_file = await context.bot.get_file(file.file_id)
    suffix = Path(file.file_name or "doc.pdf").suffix if hasattr(file, "file_name") else ".jpg"
    tmp = tempfile.NamedTemporaryFile(delete=False, prefix=f"{doc_id}_", suffix=suffix)
    register_temp_file(tmp.name)
    await tg_file.download_to_drive(tmp.name)
    fname = getattr(file, "file_name", f"photo_{datetime.now().strftime('%Y%m%d_%H%M%S')}{suffix}")

    await update.message.reply_text("📄 Processing document...")

    # Extract text
    text = extract_text(tmp.name)
    if not text or text.startswith("ERROR"):
        dlog.warning(f"Text extraction failed: {text}")
        await update.message.reply_text(f"Could not extract text from this document.")
        tmp.close()
        os.unlink(tmp.name)
        unregister_temp_file(tmp.name)
        return

    # Load roster
    sa_key_path = Path(__file__).parent / client["service_account_key_file"]
    if not sa_key_path.exists():
        await update.message.reply_text("Service account key not configured.")
        tmp.close()
        os.unlink(tmp.name)
        unregister_temp_file(tmp.name)
        return

    try:
        drive = get_drive_service(str(sa_key_path))
        employees = get_roster_cache(
            _roster_cache,
            client["drive_root_id"],
            lambda: list_employee_folders(drive, client["drive_root_id"])
        )
    except Exception as e:
        await update.message.reply_text(f"Could not access Google Drive: {e}")
        tmp.close()
        os.unlink(tmp.name)
        unregister_temp_file(tmp.name)
        return

    # Classify
    emp, cat, method = classify(text, fname, client.get("cat_keywords", {}), employees)

    async with get_chat_lock(chat_id):
        dlog.info(f"Classification result: emp={emp or '?'}, cat={cat or '?'}, method={method}")
        session = ChatSession(
            chat_id=chat_id,
            state=ChatState.AWAITING_CONFIRMATION,
            file_path=tmp.name,
            file_name=fname,
            text=text,
            employee=emp or "",
            category=cat or "",
            client=client,
            employees=employees,
            doc_id=doc_id,
            created_at=datetime.now(),
        )

        if emp and cat:
            # Ask for confirmation
            msg = await update.message.reply_text(
                f"📄 Looks like this is a **{cat}** for **{emp}**.\nIs that right?",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("👍 Yes", callback_data="confirm_yes"),
                     InlineKeyboardButton("👎 No", callback_data="confirm_no")]
                ])
            )
            session.message_id = msg.message_id
        else:
            # Could not classify — start manual correction flow with context
            session.state = ChatState.AWAITING_EMPLOYEE_CORRECTION
            session.awaiting = "employee"

            # Craft helpful fallback message based on what failed
            if not emp and not cat:
                if method == "failed":
                    fallback_msg = (
                        "I couldn't auto-classify this document (the classification service "
                        "is temporarily unavailable). Let me ask you instead:\n\n"
                        "What's the employee's full name?"
                    )
                else:
                    fallback_msg = (
                        "I couldn't identify the employee or document type from the text. "
                        "Let me ask you:\n\n"
                        "What's the employee's full name?"
                    )
            else:
                # Known employee but couldn't classify document
                fallback_msg = (
                    f"I found **{emp}** in the roster but couldn't determine "
                    f"the document type. Let me ask you:\n\n"
                    f"What type of document is this?"
                )
                session.employee = emp or ""
                session.awaiting = "category"
                session.state = ChatState.AWAITING_DOCUMENT_TYPE

            await update.message.reply_text(
                fallback_msg,
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🆕 New Employee", callback_data="new_employee")
                ]])
            )

        chat_states[chat_id] = session
        save_session(DB_PATH, session)


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle inline button presses."""
    query = update.callback_query
    await query.answer()
    chat_id = update.effective_chat.id
    msg_id = query.message.message_id
    data = query.data

    async with get_chat_lock(chat_id):
        session = chat_states.get(chat_id)
        if session is None:
            await query.edit_message_text("Sorry, this expired. Please send the document again.")
            return

        if data == "confirm_yes":
            session.state = ChatState.FILING
            chat_states[chat_id] = session
            save_session(DB_PATH, session)
            await file_document(query, session)

        elif data == "confirm_no":
            session.state = ChatState.AWAITING_EMPLOYEE_CORRECTION
            session.awaiting = "employee"
            chat_states[chat_id] = session
            save_session(DB_PATH, session)
            await query.edit_message_text(
                "What's the employee's full name?",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🆕 New Employee", callback_data="new_employee_correct")
                ]])
            )

        elif data in ("new_employee", "new_employee_correct"):
            # Both the initial "New Employee" button and the correction-flow
            # "New Employee" button lead to the same name-prompt flow.
            session.state = ChatState.AWAITING_EMPLOYEE_CORRECTION
            session.awaiting = "employee_name"
            chat_states[chat_id] = session
            save_session(DB_PATH, session)
            await query.edit_message_text(
                "What's the new employee's full name? Example: John Smith, CNA"
            )

        else:
            await query.edit_message_text("Sorry, this expired. Please send the document again.")


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle text replies for corrections."""
    chat_id = update.effective_chat.id
    text = update.message.text.strip()

    async with get_chat_lock(chat_id):
        session = chat_states.get(chat_id)
        if session is None:
            return  # No pending state for this chat — ignore text (scoped handler)

        state = session.awaiting

        if state == "employee":
            # User provided employee name
            session.employee = text
            session.awaiting = "category"
            session.state = ChatState.AWAITING_DOCUMENT_TYPE
            chat_states[chat_id] = session
            save_session(DB_PATH, session)
            await update.message.reply_text(
                "What type of document is this?\n"
                "Examples: CPR Certificate, TB Test Results, Driver's License, Background Check, etc."
            )

        elif state == "category":
            # User provided category/type
            client = session.client or {}
            cat = match_category(text, client.get("cat_keywords", {}))
            session.category = cat if cat else text
            session.description = text
            session.state = ChatState.AWAITING_CONFIRMATION
            session.message_id = 0  # Will be set when we send the confirmation

            msg = await update.message.reply_text(
                f"📄 Filing as **{session.category}** for **{session.employee}**.\nIs that right?",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("👍 Yes", callback_data="confirm_yes"),
                     InlineKeyboardButton("👎 No", callback_data="confirm_no")]
                ])
            )
            session.message_id = msg.message_id
            session.awaiting = ""
            chat_states[chat_id] = session
            save_session(DB_PATH, session)

        elif state == "employee_name":
            session.employee = text
            session.awaiting = "category"
            session.state = ChatState.AWAITING_DOCUMENT_TYPE
            chat_states[chat_id] = session
            save_session(DB_PATH, session)
            await update.message.reply_text(
                "What type of document is this?\n"
                "Examples: CPR Certificate, TB Test Results, Driver's License"
            )


async def file_document(query, info):
    """Upload the document to the correct Drive folder."""
    client = info.client if hasattr(info, 'client') else info.get("client", {})
    emp_name = info.employee if hasattr(info, 'employee') else info.get("employee", "")
    cat_name = info.category if hasattr(info, 'category') else info.get("category", "")
    file_path = info.file_path if hasattr(info, 'file_path') else info.get("file_path", "")
    file_name = info.file_name if hasattr(info, 'file_name') else info.get("file_name", "")
    doc_id = info.doc_id if hasattr(info, 'doc_id') else ""
    dlog = DocLogger(log, {"doc_id": doc_id}) if doc_id else log
    dlog.info(f"Filing: {emp_name} / {cat_name}")

    try:
        sa_key_path = Path(__file__).parent / client["service_account_key_file"]
        drive = get_drive_service(str(sa_key_path))
        employees = get_roster_cache(
            _roster_cache,
            client["drive_root_id"],
            lambda: list_employee_folders(drive, client["drive_root_id"])
        )

        emp_key = emp_name.lower().strip()
        if emp_key not in employees:
            # New employee — create folder
            cat_folder = await create_employee_folders(drive, client["drive_root_id"], emp_name)
            emp_folder_id = cat_folder
        else:
            emp_folder_id = employees[emp_key]["id"]

        # Build description from filename or use category
        desc = os.path.splitext(os.path.basename(file_name))[0]
        ext = os.path.splitext(file_name)[1]
        safe_name = f"{emp_name} - {cat_name}{ext}" if cat_name else f"{emp_name} - {desc}{ext}"

        # Find category folder
        cat_folder_id = find_category_folder(drive, emp_folder_id, cat_name) if cat_name else emp_folder_id

        # Upload
        mime = "application/pdf" if ext.lower() == ".pdf" else "image/jpeg"
        fid = upload_file(drive, cat_folder_id, file_path, safe_name, mime)

        # Upload robot.txt too
        robot_path = file_path + "-robot.txt"
        session_text = info.text if hasattr(info, 'text') else info.get("text", "")
        with open(robot_path, "w") as rf:
            rf.write(f"SOURCE: Telegram\nFILED: {datetime.now().isoformat()}\n\n--- EXTRACTED TEXT ---\n{session_text}\n")
        robot_name = os.path.splitext(safe_name)[0] + "-robot.txt"
        upload_file(drive, cat_folder_id, robot_path, robot_name, "text/plain")
        os.unlink(robot_path)

        await query.edit_message_text(
            f"✅ Filed **{safe_name}** into **{emp_name}** → **{cat_name}**",
            parse_mode="Markdown"
        )
        dlog.info(f"Filed: {safe_name} -> {emp_name}/{cat_name} (file_id={fid})")

    except Exception as e:
        log.error(f"Filing failed: {e}")
        await query.edit_message_text(f"❌ Failed to file: {e}")
    finally:
        # Clean up session and temp file
        chat_id = query.message.chat_id if hasattr(query, 'message') else None
        if chat_id:
            async with get_chat_lock(chat_id):
                chat_states.pop(chat_id, None)
                delete_session(DB_PATH, chat_id)
        if file_path and os.path.exists(file_path):
            os.unlink(file_path)
            unregister_temp_file(file_path)


async def create_employee_folders(drive, root_id, emp_name):
    """Create employee folder structure for a new hire."""
    # Find CAREGIVERS folder
    results = drive.files().list(
        q=f"'{root_id}' in parents and mimeType='application/vnd.google-apps.folder' and name='CAREGIVERS'",
        supportsAllDrives=True, includeItemsFromAllDrives=True, fields="files(id)"
    ).execute()
    caregivers = results.get("files", [])
    if not caregivers:
        raise Exception("CAREGIVERS folder not found in Drive root")
    caregivers_id = caregivers[0]["id"]

    # Create employee folder
    emp_meta = {"name": emp_name, "parents": [caregivers_id], "mimeType": "application/vnd.google-apps.folder"}
    emp_folder = drive.files().create(body=emp_meta, supportsAllDrives=True).execute()
    emp_id = emp_folder["id"]

    # Create category subfolders — use the global WAC_CATEGORIES list
    for cat in WAC_CATEGORIES:
        drive.files().create(
            body={"name": cat, "parents": [emp_id], "mimeType": "application/vnd.google-apps.folder"},
            supportsAllDrives=True
        ).execute()

    return emp_id


def extract_text(file_path):
    """Run doc-extract.py and return the extracted text."""
    script = Path(__file__).parent / "scripts" / "doc-extract.py"
    if not script.exists():
        return "ERROR: doc-extract.py not found"

    result = subprocess.run(
        [sys.executable, str(script), file_path],
        capture_output=True, text=True, timeout=300
    )

    if result.returncode != 0:
        return f"ERROR: {result.stderr[:200]}"

    # Extract text after "--- EXTRACTED TEXT ---"
    output = result.stdout
    if "--- EXTRACTED TEXT ---" in output:
        return output.split("--- EXTRACTED TEXT ---", 1)[1].strip()
    return output.strip()


def match_category(text, cat_keywords):
    """Match user's free-text description to a WAC category."""
    text_lower = text.lower()
    for cat, kws in cat_keywords.items():
        for kw in kws:
            if kw in text_lower:
                return cat
    return None


# --- Heartbeat / External Monitoring ---

async def heartbeat_callback(context: ContextTypes.DEFAULT_TYPE):
    """Periodic heartbeat ping to external monitoring service.

    Called every 5 minutes via JobQueue if HEARTBEAT_URL is configured.
    Pings the URL with a simple GET — the monitoring service
    alerts if it stops receiving pings (bot crash, API key expiry,
    or process hang).
    """
    if not HEARTBEAT_URL:
        return
    import urllib.request
    try:
        req = urllib.request.Request(HEARTBEAT_URL, method="GET")
        with urllib.request.urlopen(req, timeout=15) as resp:
            log.debug(f"Heartbeat OK ({resp.status})")
    except Exception as e:
        log.warning(f"Heartbeat failed: {e}")


def get_client_config(chat_id):
    """Get client config by chat_id."""
    for c in CONFIG["clients"]:
        if c["chat_id"] == chat_id:
            return c
    return None


async def providers_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /providers — list provider vs caregiver status for all employees."""
    chat_id = update.effective_chat.id
    client = get_client_config(chat_id)
    if not client:
        await update.message.reply_text("This chat is not configured for document filing.")
        return

    sa_key = Path(__file__).parent / client["service_account_key_file"]
    if not sa_key.exists():
        await update.message.reply_text("Service account key not configured.")
        return

    try:
        drive = get_drive_service(str(sa_key))
        employees = get_roster_cache(
            _roster_cache,
            client["drive_root_id"],
            lambda: list_employee_folders(drive, client["drive_root_id"])
        )
    except Exception as e:
        await update.message.reply_text(f"Could not access Google Drive: {e}")
        return

    if not employees:
        await update.message.reply_text("No employees found in Drive.")
        return

    lines = ["📋 **Employee Provider Status**\n"]
    for key, info in sorted(employees.items()):
        name = info["name"]
        is_prov = is_provider(client, name)
        icon = "🏢" if is_prov else "👤"
        role = "Provider" if is_prov else "Caregiver"
        lines.append(f"{icon} **{name}** — {role}")

    # Split into multiple messages if too long
    msg = "\n".join(lines)
    if len(msg) > 4000:
        for i in range(0, len(msg), 4000):
            await update.message.reply_text(msg[i:i + 4000], parse_mode="Markdown")
    else:
        await update.message.reply_text(msg, parse_mode="Markdown")


def main():
    if not TELEGRAM_TOKEN:
        log.error("TELEGRAM_BOT_TOKEN not set in environment")
        sys.exit(1)

    # Initialise SQLite persistence
    db_path = init_db()
    removed = cleanup_old_sessions(db_path)
    if removed:
        log.info(f"Cleaned up {removed} stale session(s) from database")

    # Sweep stale temp files from the registry
    stale = cleanup_stale_temp_files()
    if stale:
        log.info(f"Cleaned up {stale} stale temp file(s) from registry")

    # Also sweep /tmp for orphaned doc_* files from previous crash cycles
    import glob
    orphaned = 0
    for f in glob.glob(f"/tmp/doc_*"):
        try:
            age = (datetime.now() - datetime.fromtimestamp(os.path.getmtime(f))).total_seconds()
            if age > 86400:  # >24h
                os.unlink(f)
                orphaned += 1
        except (FileNotFoundError, OSError):
            continue
    if orphaned:
        log.info(f"Cleaned up {orphaned} orphaned temp file(s) from /tmp")

    # Load pending sessions from DB into in-memory chat_states
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    cur = conn.execute("SELECT * FROM sessions")
    for row in cur.fetchall():
        session = _row_to_session(row)
        chat_states[session.chat_id] = session
    conn.close()
    if chat_states:
        log.info(f"Loaded {len(chat_states)} pending session(s) from database")

    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("providers", providers_command))
    app.add_handler(MessageHandler(filters.PHOTO | filters.Document.MimeType("application/pdf") | filters.Document.Category("image/"), handle_document))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    # Start heartbeat monitoring (pings every 5 min via JobQueue)
    if HEARTBEAT_URL and app.job_queue:
        app.job_queue.run_repeating(heartbeat_callback, interval=300, first=60)
        log.info(f"Heartbeat monitoring active → {HEARTBEAT_URL}")
    else:
        log.info("No HEARTBEAT_URL set or JobQueue unavailable — monitoring disabled")

    log.info("Bot started")
    app.run_polling()


if __name__ == "__main__":
    main()
