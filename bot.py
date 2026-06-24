#!/usr/bin/env python3
"""Employee Docs Bot — Telegram bot for filing AFH employee documents.

Receives documents in a Telegram channel, extracts text via doc-extract.py,
classifies by employee and WAC category, confirms with user via inline buttons,
and files into the correct Google Drive folder.

Designed for multi-tenant use. Each client (AFH) has a config entry mapping
their chat_id to their Drive folder and service account.
"""

import os, sys, re, json, logging, tempfile, subprocess, io
from pathlib import Path
from datetime import datetime

# --- Config ---
CONFIG_FILE = Path(__file__).parent / "config.json"
if not CONFIG_FILE.exists():
    CONFIG_FILE = Path(__file__).parent / "config.example.json"
    print(f"WARNING: Using config.example.json. Copy to config.json and configure.", file=sys.stderr)

with open(CONFIG_FILE) as f:
    CONFIG = json.load(f)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_VISION_API_KEY", "")
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_MODEL = "deepseek-chat"

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=logging.INFO,
    handlers=[logging.StreamHandler()]
)
log = logging.getLogger("docs-bot")

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

def classify_by_rules(text, filename, cat_keywords, employees):
    """Try to classify by keyword matching. Returns (employee_name, category) or (None, None)."""
    text_lower = text.lower() if text else ""
    fname_lower = filename.lower() if filename else ""

    # Find employee
    emp_match = None
    for key, info in employees.items():
        parts = key.split(",")[0].strip()
        if parts in text_lower or parts in fname_lower:
            emp_match = info["name"]
            break

    # Find category
    cat_match = None
    for cat, kws in cat_keywords.items():
        for kw in kws:
            if kw in text_lower or kw in fname_lower:
                cat_match = cat
                break
        if cat_match:
            break

    return emp_match, cat_match


def classify_by_llm(text, filename, employees, cat_keywords):
    """Fallback: use DeepSeek to classify."""
    emp_list = ", ".join(sorted(set(v["name"] for v in employees.values())))
    cat_list = ", ".join(cat_keywords.keys())
    prompt = f"""Given this document text, identify:
1. Which employee does this belong to? Choose from: {emp_list}
2. What document type is it? Choose from the categories or describe it.

Return ONLY valid JSON: {{"employee": "Full Name", "category": "Category Name", "description": "brief description"}}

Document text:
{text[:3000]}"""

    payload = json.dumps({
        "model": DEEPSEEK_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 300
    })

    try:
        import urllib.request
        req = urllib.request.Request(
            "https://api.deepseek.com/chat/completions",
            data=payload.encode(),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {DEEPSEEK_API_KEY}"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
        content = data["choices"][0]["message"]["content"]

        # Extract JSON from response
        json_match = re.search(r'\{[^}]+\}', content, re.DOTALL)
        if json_match:
            result = json.loads(json_match.group())
            emp = result.get("employee", "")
            cat = result.get("category", "")
            # Validate against known lists
            if cat not in cat_keywords:
                cat = None
            if emp.lower() not in employees:
                emp = None
            return emp, cat
    except Exception as e:
        log.warning(f"DeepSeek classification failed: {e}")

    return None, None


def classify(text, filename, cat_keywords, employees):
    """Hybrid: try rules first, fall back to LLM."""
    emp, cat = classify_by_rules(text, filename, cat_keywords, employees)
    if emp and cat:
        log.info(f"Rules classified: {emp} / {cat}")
        return emp, cat, "rules"

    emp2, cat2 = classify_by_llm(text, filename, employees, cat_keywords)
    if emp2 or cat2:
        log.info(f"LLM classified: {emp2 or '?'} / {cat2 or '?'}")
        return emp2, cat2, "llm"

    return None, None, "failed"


# --- Bot ---
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

# Store pending classifications
pending = {}  # chat_id: {msg_id: {file_path, text, employee, category, guess_type, file_name}}


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

    # Download to temp
    tg_file = await context.bot.get_file(file.file_id)
    suffix = Path(file.file_name or "doc.pdf").suffix if hasattr(file, "file_name") else ".jpg"
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    await tg_file.download_to_drive(tmp.name)
    fname = getattr(file, "file_name", f"photo_{datetime.now().strftime('%Y%m%d_%H%M%S')}{suffix}")

    await update.message.reply_text("📄 Processing document...")

    # Extract text
    text = extract_text(tmp.name)
    if not text or text.startswith("ERROR"):
        await update.message.reply_text(f"Could not extract text from this document.")
        tmp.close()
        os.unlink(tmp.name)
        return

    # Load roster
    sa_key = Path(__file__).parent / client["service_account_key_file"]
    if not sa_key.exists():
        await update.message.reply_text("Service account key not configured.")
        tmp.close()
        os.unlink(tmp.name)
        return

    try:
        drive = get_drive_service(str(sa_key))
        employees = list_employee_folders(drive, client["drive_root_id"])
    except Exception as e:
        await update.message.reply_text(f"Could not access Google Drive: {e}")
        tmp.close()
        os.unlink(tmp.name)
        return

    # Classify
    emp, cat, method = classify(text, fname, client.get("cat_keywords", {}), employees)

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
        pending[(chat_id, msg.message_id)] = {
            "file_path": tmp.name,
            "file_name": fname,
            "text": text,
            "employee": emp,
            "category": cat,
            "client": client,
            "employees": employees
        }
    else:
        # Ask for employee name first
        if not emp:
            await update.message.reply_text(
                "I couldn't identify the employee. What's their full name?",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🆕 New Employee", callback_data="new_employee")
                ]])
            )
            pending[(chat_id, "awaiting_employee")] = {
                "file_path": tmp.name,
                "file_name": fname,
                "text": text,
                "client": client,
                "employees": employees,
                "awaiting": "employee"
            }
        else:
            # Known employee but couldn't classify document
            msg = await update.message.reply_text(
                f"📄 Found employee **{emp}**, but unsure of document type.\n"
                f"Is this a new employee?",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("👍 Yes", callback_data="confirm_yes"),
                     InlineKeyboardButton("👎 No", callback_data="confirm_no")]
                ])
            )


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle inline button presses."""
    query = update.callback_query
    await query.answer()
    chat_id = update.effective_chat.id
    msg_id = query.message.message_id
    data = query.data

    key = (chat_id, msg_id)

    if key in pending:
        info = pending.pop(key)

    elif (chat_id, "awaiting_employee") in pending:
        info = pending.pop((chat_id, "awaiting_employee"))
        if data == "new_employee":
            info["awaiting"] = "employee_name"
            pending[(chat_id, "awaiting_new_name")] = info
            await query.edit_message_text(
                "What's the new employee's full name? Example: John Smith, CNA"
            )
            return
        else:
            info["awaiting"] = "employee_name"
            pending[(chat_id, "awaiting_employee_name")] = info
            await query.edit_message_text(
                "Type the employee's full name."
            )
            return
    else:
        # Check other pending states
        for k in list(pending.keys()):
            if k[0] == chat_id and k[1] in ("awaiting_new_name", "awaiting_employee_name", "awaiting_category"):
                info = pending.pop(k)
                break
        else:
            await query.edit_message_text("Sorry, this expired. Please send the document again.")
            return

    if data == "confirm_yes":
        await file_document(query, info)
    elif data == "confirm_no":
        # Ask what's wrong
        info["awaiting"] = "employee"
        pending[(chat_id, "awaiting_correction")] = info
        await query.edit_message_text(
            "What's the employee's full name?",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🆕 New Employee", callback_data="new_employee_correct")
            ]])
        )


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle text replies for corrections."""
    chat_id = update.effective_chat.id
    text = update.message.text.strip()

    # Check pending states
    info = None
    for k in list(pending.keys()):
        if k[0] == chat_id:
            info = pending.pop(k)
            break

    if not info:
        return

    state = info.get("awaiting", "")

    if state == "employee":
        # User provided employee name
        info["employee"] = text
        info["awaiting"] = "category"
        pending[(chat_id, "awaiting_category")] = info
        await update.message.reply_text(
            "What type of document is this?\n"
            "Examples: CPR Certificate, TB Test Results, Driver's License, Background Check, etc."
        )

    elif state == "category":
        # User provided category/type
        info["user_description"] = text
        # Map to a WAC category
        cat = match_category(text, info["client"].get("cat_keywords", {}))
        info["category"] = cat if cat else text

        msg = await update.message.reply_text(
            f"📄 Filing as **{info['category']}** for **{info.get('employee', '?')}**.\nIs that right?",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("👍 Yes", callback_data="confirm_yes"),
                 InlineKeyboardButton("👎 No", callback_data="confirm_no")]
            ])
        )
        pending[(chat_id, msg.message_id)] = info

    elif state == "employee_name":
        info["employee"] = text
        info["awaiting"] = "category"
        pending[(chat_id, "awaiting_category")] = info
        await update.message.reply_text(
            "What type of document is this?\n"
            "Examples: CPR Certificate, TB Test Results, Driver's License"
        )

    elif state == "new_employee":
        # Could be a new employee
        info["employee"] = text
        info["category"] = None
        info["awaiting"] = "category"
        pending[(chat_id, "awaiting_category")] = info
        await update.message.reply_text(
            "What type of document is this?"
        )


async def file_document(query, info):
    """Upload the document to the correct Drive folder."""
    client = info["client"]
    emp_name = info.get("employee", "")
    cat_name = info.get("category", "")
    file_path = info.get("file_path", "")
    file_name = info.get("file_name", "")

    try:
        sa_key = Path(__file__).parent / client["service_account_key_file"]
        drive = get_drive_service(str(sa_key))
        employees = list_employee_folders(drive, client["drive_root_id"])

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
        with open(robot_path, "w") as rf:
            rf.write(f"SOURCE: Telegram\nFILED: {datetime.now().isoformat()}\n\n--- EXTRACTED TEXT ---\n{info.get('text', '')}\n")
        robot_name = os.path.splitext(safe_name)[0] + "-robot.txt"
        upload_file(drive, cat_folder_id, robot_path, robot_name, "text/plain")
        os.unlink(robot_path)

        await query.edit_message_text(
            f"✅ Filed **{safe_name}** into **{emp_name}** → **{cat_name}**",
            parse_mode="Markdown"
        )

    except Exception as e:
        log.error(f"Filing failed: {e}")
        await query.edit_message_text(f"❌ Failed to file: {e}")
    finally:
        if file_path and os.path.exists(file_path):
            os.unlink(file_path)


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

    # Create category subfolders
    categories = ["01 - Identity & Employment", "02 - Background Check", "03 - Health Screening",
                  "04 - CPR & First Aid", "05 - Orientation & Training", "06 - HCA Certification & CE",
                  "07 - Nurse Delegation"]
    for cat in categories:
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


def get_client_config(chat_id):
    """Get client config by chat_id."""
    for c in CONFIG["clients"]:
        if c["chat_id"] == chat_id:
            return c
    return None


def main():
    if not TELEGRAM_TOKEN:
        log.error("TELEGRAM_BOT_TOKEN not set in environment")
        sys.exit(1)

    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(MessageHandler(filters.PHOTO | filters.DocumentCategory("application/pdf") | filters.DocumentCategory("image/*"), handle_document))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    log.info("Bot started")
    app.run_polling()


if __name__ == "__main__":
    main()
