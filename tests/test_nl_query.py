"""Tests for natural language query handling via DeepSeek."""
import pytest
from unittest.mock import patch, MagicMock, AsyncMock

pytestmark = pytest.mark.anyio

TEST_CHAT_ID = -1004391863263


async def _make_text_message(chat_id, text, use_channel_post=False):
    """Create a minimal text update with no pending session."""
    from telegram import Update, Message, User, Chat

    chat = MagicMock(spec=Chat)
    chat.id = chat_id
    chat.type = "group"
    chat.effective_id = chat_id

    user = MagicMock(spec=User)
    user.id = 123
    user.is_bot = False

    msg = MagicMock(spec=Message)
    msg.message_id = 99
    msg.text = text
    msg.chat = chat
    msg.from_user = user
    msg.reply_text = AsyncMock()
    msg.effective_chat = chat

    update = MagicMock(spec=Update)
    update.update_id = 3
    update.message = msg
    update.channel_post = msg if use_channel_post else None
    update.callback_query = None
    update.effective_chat = chat
    update.effective_message = msg
    update.effective_user = user

    return update, msg


class TestNLQuery:
    """Natural language query handling."""

    @pytest.mark.anyio
    async def test_nl_query_answers_via_deepseek(self):
        """When user types a question with no pending session, bot answers via DeepSeek."""
        import bot
        update, msg = await _make_text_message(TEST_CHAT_ID, "What documents are required for caregivers?")

        # Mock DeepSeek API response
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.read.return_value = b'{"choices": [{"message": {"content": "Caregivers need: 01-Identity, 02-Background Check, 03-TB Test, 04-CPR, 05-Training, 06-HCA Certification, 07-Nurse Delegation"}}]}'

        orig_states = dict(bot.chat_states)
        bot.chat_states.clear()
        orig_key = os.environ.get("DEEPSEEK_API_KEY", "")
        os.environ["DEEPSEEK_API_KEY"] = "test-deepseek-key"
        try:
            with patch("urllib.request.urlopen") as mock_urlopen:
                mock_urlopen.return_value.__enter__.return_value = mock_response
                await bot.handle_text(update, MagicMock())
                msg.reply_text.assert_called_once()
                call_text = msg.reply_text.call_args[0][0]
                assert "Caregivers" in call_text or "caregivers" in call_text
        finally:
            bot.chat_states.clear()
            bot.chat_states.update(orig_states)
            os.environ["DEEPSEEK_API_KEY"] = orig_key


import os
