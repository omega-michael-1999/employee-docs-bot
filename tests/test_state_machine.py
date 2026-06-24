"""Tests for the per-chat state machine with SQLite persistence."""
from bot import ChatState, ChatSession, init_db, save_session, load_session, cleanup_old_sessions
from datetime import datetime, timedelta
import os
import tempfile


class TestChatState:
    """ChatState enum defines all expected states."""

    def test_states_exist(self):
        """ChatState has all required states."""
        assert ChatState.IDLE is not None
        assert ChatState.AWAITING_CONFIRMATION is not None
        assert ChatState.AWAITING_EMPLOYEE_CORRECTION is not None
        assert ChatState.AWAITING_DOCUMENT_TYPE is not None
        assert ChatState.FILING is not None


class TestChatSession:
    """ChatSession dataclass stores per-chat state."""

    def test_session_has_required_fields(self):
        """ChatSession has the fields needed for document processing."""
        session = ChatSession(chat_id=12345, state=ChatState.IDLE)
        assert session.chat_id == 12345
        assert session.state == ChatState.IDLE
        # Optional fields default to sensible values
        assert session.file_path == ""
        assert session.file_name == ""
        assert session.text == ""
        assert session.employee == ""
        assert session.category == ""


class TestSessionPersistence:
    """SQLite persistence round-trips session state."""

    def test_round_trip(self):
        """Save a session to SQLite and load it back."""
        db_fd, db_path = tempfile.mkstemp(suffix=".db")
        os.close(db_fd)
        try:
            init_db(db_path)

            session = ChatSession(
                chat_id=42,
                state=ChatState.AWAITING_CONFIRMATION,
                message_id=100,
                file_path="/tmp/test.pdf",
                file_name="test.pdf",
                text="CPR card for Fatou Manneh",
                employee="Fatou Manneh",
                category="04 - CPR & First Aid",
                created_at=datetime.now(),
                awaiting="",
            )
            save_session(db_path, session)

            loaded = load_session(db_path, 42)
            assert loaded is not None
            assert loaded.chat_id == 42
            assert loaded.state == ChatState.AWAITING_CONFIRMATION
            assert loaded.message_id == 100
            assert loaded.employee == "Fatou Manneh"
            assert loaded.category == "04 - CPR & First Aid"
        finally:
            os.unlink(db_path)

    def test_load_nonexistent_returns_none(self):
        """Loading a session that doesn't exist returns None."""
        db_fd, db_path = tempfile.mkstemp(suffix=".db")
        os.close(db_fd)
        try:
            init_db(db_path)
            loaded = load_session(db_path, 999)
            assert loaded is None
        finally:
            os.unlink(db_path)

    def test_delete_session(self):
        """Delete removes a session from the database."""
        db_fd, db_path = tempfile.mkstemp(suffix=".db")
        os.close(db_fd)
        try:
            init_db(db_path)
            session = ChatSession(chat_id=7, state=ChatState.AWAITING_CONFIRMATION, created_at=datetime.now())
            save_session(db_path, session)
            assert load_session(db_path, 7) is not None

            from bot import delete_session
            delete_session(db_path, 7)
            assert load_session(db_path, 7) is None
        finally:
            os.unlink(db_path)

    def test_cleanup_old_sessions(self):
        """Sessions older than 24 hours are cleaned up."""
        db_fd, db_path = tempfile.mkstemp(suffix=".db")
        os.close(db_fd)
        try:
            init_db(db_path)

            now = datetime.now()
            old = ChatSession(chat_id=1, state=ChatState.AWAITING_CONFIRMATION, created_at=now - timedelta(hours=48))
            recent = ChatSession(chat_id=2, state=ChatState.AWAITING_CONFIRMATION, created_at=now - timedelta(hours=1))

            save_session(db_path, old)
            save_session(db_path, recent)

            cleanup_old_sessions(db_path, max_age_hours=24)

            assert load_session(db_path, 1) is None, "Old session should be deleted"
            assert load_session(db_path, 2) is not None, "Recent session should remain"
        finally:
            os.unlink(db_path)
