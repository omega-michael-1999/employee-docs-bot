"""Integration tests for the handler orchestration layer.

Tests the full state machine through the handler surface using
constructed mock Telegram objects. Real external API calls (Drive,
Anthropic) are mocked — these test orchestration, not integrations.
"""
import pytest
import json
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

from telegram import Update, Message, User, Chat, Document, CallbackQuery

pytestmark = pytest.mark.anyio

# Test config matching the schema bot.py expects
TEST_CONFIG = {
    "clients": [
        {
            "chat_id": -1004391863263,  # matches AFH_22 (Test) in actual config.json
            "name": "Test AFH",
            "drive_root_id": "test_drive_root",
            "service_account_key_file": ".service-account-keys/edmonds-villa-sa.json",
            "providers": ["Sandra Namwase"],
            "cat_keywords": {
                "04 - CPR & First Aid": ["cpr", "bls", "first aid"],
            }
        }
    ]
}

TEST_CHAT_ID = -1004391863263


@pytest.fixture(autouse=True)
def patch_config_and_extract(tmp_path):
    """Patch bot's CONFIG, DB_PATH, and external calls for all tests."""
    import bot
    db_path = tmp_path / "pending.db"
    with patch.object(bot, "CONFIG", TEST_CONFIG):
        with patch.object(bot, "DB_PATH", db_path):
            with patch.object(bot, "extract_text", return_value="Fatou Manneh CPR card expired 2026"):
                bot.init_db(str(db_path))
                yield


def _make_chat(chat_id=TEST_CHAT_ID):
    chat = MagicMock(spec=Chat)
    chat.id = chat_id
    chat.type = "group"
    chat.effective_id = chat_id
    return chat


def _make_user():
    user = MagicMock(spec=User)
    user.id = 123
    user.is_bot = False
    user.first_name = "Test"
    user.username = "test_user"
    return user


def _make_document(file_name="test_cpr.pdf", file_size=100000):
    doc = MagicMock(spec=Document)
    doc.file_id = "test_file_id"
    doc.file_name = file_name
    doc.file_size = file_size
    doc.mime_type = "application/pdf"
    return doc


async def _make_update_with_document(chat_id=TEST_CHAT_ID, file_name="test_cpr.pdf", file_size=100000):
    """Build a minimal Update with a Document attachment."""
    chat = _make_chat(chat_id)
    user = _make_user()
    doc = _make_document(file_name, file_size)

    reply_result = MagicMock(spec=Message)
    reply_result.message_id = 42

    msg = MagicMock(spec=Message)
    msg.message_id = 42
    msg.document = doc
    msg.photo = None
    msg.text = None
    msg.chat = chat
    msg.from_user = user
    msg.reply_text = AsyncMock(return_value=reply_result)
    msg.effective_chat = chat

    update = MagicMock(spec=Update)
    update.update_id = 1
    update.message = msg
    update.channel_post = None
    update.callback_query = None
    update.effective_chat = chat
    update.effective_message = msg
    update.effective_user = user

    return update, msg


async def _make_callback_update(chat_id, message_id, data, original_message=None):
    """Build a minimal Update with a CallbackQuery."""
    chat = _make_chat(chat_id)
    user = _make_user()
    msg = original_message or _make_message(message_id, chat)

    cq = MagicMock(spec=CallbackQuery)
    cq.data = data
    cq.message = msg
    cq.from_user = user
    cq.answer = AsyncMock()
    cq.edit_message_text = AsyncMock()
    cq.message.chat = chat
    cq.message.message_id = message_id

    update = MagicMock(spec=Update)
    update.update_id = 2
    update.message = None
    update.callback_query = cq
    update.effective_chat = chat
    update.effective_message = msg
    update.effective_user = user

    return update


def _make_message(message_id=42, chat=None):
    if chat is None:
        chat = _make_chat()
    msg = MagicMock(spec=Message)
    msg.message_id = message_id
    msg.chat = chat
    msg.reply_text = AsyncMock()
    return msg


@pytest.fixture
def mock_bot():
    """Create a mock bot that returns a fake file for download."""
    bot = MagicMock()
    bot.get_file = AsyncMock()
    fake_file = MagicMock()
    fake_file.download_to_drive = AsyncMock()
    bot.get_file.return_value = fake_file
    return bot


@pytest.fixture
def mock_context(mock_bot):
    """Create a minimal callback context with a mock bot."""
    context = MagicMock()
    context.bot = mock_bot
    return context


class TestHandlerOrchestration:
    """Integration tests for handler state machine orchestration."""

    @pytest.mark.anyio
    async def test_text_with_no_pending_is_ignored(self, mock_context):
        """Sending text without a pending session should silently return."""
        import bot
        chat = _make_chat()
        user = _make_user()

        msg = MagicMock(spec=Message)
        msg.message_id = 99
        msg.text = "Hello, bot"
        msg.chat = chat
        msg.from_user = user
        msg.reply_text = AsyncMock()

        update = MagicMock(spec=Update)
        update.update_id = 3
        update.message = msg
        update.channel_post = None
        update.callback_query = None
        update.effective_chat = chat
        update.effective_message = msg
        update.effective_user = user

        orig_states = dict(bot.chat_states)
        bot.chat_states.clear()
        try:
            await bot.handle_text(update, mock_context)
            msg.reply_text.assert_not_called()
        finally:
            bot.chat_states.clear()
            bot.chat_states.update(orig_states)

    @pytest.mark.anyio
    async def test_document_creates_pending_session(self, mock_context):
        """Sending a PDF should create a ChatSession in AWAITING_CONFIRMATION."""
        import bot
        update, msg = await _make_update_with_document()

        orig_states = dict(bot.chat_states)
        bot.chat_states.clear()

        with patch.object(bot, "get_drive_service"):
            with patch.object(bot, "list_employee_folders",
                              return_value={"fatou manneh": {"id": "f1", "name": "Fatou Manneh"}}):
                try:
                    await bot.handle_document(update, mock_context)
                    assert TEST_CHAT_ID in bot.chat_states
                    session = bot.chat_states[TEST_CHAT_ID]
                    assert session.state == bot.ChatState.AWAITING_CONFIRMATION
                    assert msg.reply_text.call_count == 2  # "Processing..." + confirmation
                finally:
                    bot.chat_states.clear()
                    bot.chat_states.update(orig_states)

    @pytest.mark.anyio
    async def test_confirm_no_starts_correction_flow(self, mock_context):
        """Clicking No should start correction flow with employee name prompt."""
        import bot
        update, msg = await _make_update_with_document()

        orig_states = dict(bot.chat_states)
        bot.chat_states.clear()

        with patch.object(bot, "get_drive_service"):
            with patch.object(bot, "list_employee_folders",
                              return_value={"fatou manneh": {"id": "f1", "name": "Fatou Manneh"}}):
                try:
                    await bot.handle_document(update, mock_context)

                    cb_update = await _make_callback_update(TEST_CHAT_ID, 42, "confirm_no")
                    await bot.handle_callback(cb_update, mock_context)

                    session = bot.chat_states[TEST_CHAT_ID]
                    assert session.state == bot.ChatState.AWAITING_EMPLOYEE_CORRECTION
                    assert session.awaiting == "employee"
                    cb_update.callback_query.edit_message_text.assert_called_once()
                finally:
                    bot.chat_states.clear()
                    bot.chat_states.update(orig_states)

    @pytest.mark.anyio
    async def test_new_employee_correct_shows_name_prompt(self, mock_context):
        """The new_employee_correct callback should show name prompt, not 'expired'."""
        import bot
        update, msg = await _make_update_with_document()

        orig_states = dict(bot.chat_states)
        bot.chat_states.clear()

        with patch.object(bot, "get_drive_service"):
            with patch.object(bot, "list_employee_folders",
                              return_value={"fatou manneh": {"id": "f1", "name": "Fatou Manneh"}}):
                try:
                    await bot.handle_document(update, mock_context)

                    cb_confirm_no = await _make_callback_update(TEST_CHAT_ID, 42, "confirm_no")
                    await bot.handle_callback(cb_confirm_no, mock_context)

                    cb_new_emp = await _make_callback_update(TEST_CHAT_ID, 42, "new_employee_correct")
                    await bot.handle_callback(cb_new_emp, mock_context)

                    call_text = cb_new_emp.callback_query.edit_message_text.call_args[0][0]
                    assert "expired" not in call_text.lower()
                    assert ("full name" in call_text.lower()
                            or "new employee" in call_text.lower())
                finally:
                    bot.chat_states.clear()
                    bot.chat_states.update(orig_states)

    @pytest.mark.anyio
    async def test_confirm_yes_starts_filing(self, mock_context):
        """Clicking Yes should transition session to FILING state."""
        import bot
        update, msg = await _make_update_with_document()

        orig_states = dict(bot.chat_states)
        bot.chat_states.clear()

        with patch.object(bot, "get_drive_service"):
            with patch.object(bot, "list_employee_folders",
                              return_value={"fatou manneh": {"id": "f1", "name": "Fatou Manneh"}}):
                with patch.object(bot, "file_document", AsyncMock()):
                    try:
                        await bot.handle_document(update, mock_context)

                        cb_update = await _make_callback_update(TEST_CHAT_ID, 42, "confirm_yes")
                        await bot.handle_callback(cb_update, mock_context)

                        session = bot.chat_states.get(TEST_CHAT_ID)
                        assert session is None or session.state == bot.ChatState.FILING
                        bot.file_document.assert_awaited_once()
                    finally:
                        bot.chat_states.clear()
                        bot.chat_states.update(orig_states)

    @pytest.mark.anyio
    async def test_oversized_file_is_rejected(self, mock_context):
        """Files larger than 20MB should be rejected before download."""
        import bot
        update, msg = await _make_update_with_document(file_size=25 * 1024 * 1024)

        orig_states = dict(bot.chat_states)
        bot.chat_states.clear()
        try:
            await bot.handle_document(update, mock_context)
            mock_context.bot.get_file.assert_not_called()
            msg.reply_text.assert_called_once()
            call_text = msg.reply_text.call_args[0][0]
            assert "too large" in call_text.lower()
        finally:
            bot.chat_states.clear()
            bot.chat_states.update(orig_states)

    @pytest.mark.anyio
    async def test_unsupported_extension_is_rejected(self, mock_context):
        """Unsupported file extensions should be rejected with detected type."""
        import bot
        update, msg = await _make_update_with_document(file_name="photo.tiff")

        orig_states = dict(bot.chat_states)
        bot.chat_states.clear()
        try:
            await bot.handle_document(update, mock_context)
            mock_context.bot.get_file.assert_not_called()
            msg.reply_text.assert_called_once()
            call_text = msg.reply_text.call_args[0][0]
            assert "TIFF" in call_text
            assert "I can only process" in call_text
        finally:
            bot.chat_states.clear()
            bot.chat_states.update(orig_states)
