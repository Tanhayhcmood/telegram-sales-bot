import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.models.conversation import Conversation
from app.services.userbot.handlers import (
    _build_model_messages,
    get_or_create_conversation,
)


class _ExecuteResult:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class _Session:
    def __init__(self, result):
        self.result = result
        self.added = []
        self.executed = []

    async def execute(self, statement):
        self.executed.append(statement)
        return _ExecuteResult(self.result)

    def add(self, value):
        self.added.append(value)

    async def flush(self):
        return None


class ConversationMemoryTests(unittest.IsolatedAsyncioTestCase):
    def test_model_payload_keeps_both_roles_and_caps_old_turns(self):
        history = [
            {"role": "user", "content": "پیام قدیمی"},
            {"role": "assistant", "content": "پاسخ قدیمی"},
            {"role": "user", "content": "برای گیم میخوام"},
            {"role": "assistant", "content": "ENTRY مناسب شروعه"},
        ]

        messages = _build_model_messages(history, "پلن بعدیش چیه؟", limit=4)

        self.assertEqual(
            messages,
            [
                {"role": "assistant", "content": "پاسخ قدیمی"},
                {"role": "user", "content": "برای گیم میخوام"},
                {"role": "assistant", "content": "ENTRY مناسب شروعه"},
                {"role": "user", "content": "پلن بعدیش چیه؟"},
            ],
        )

    async def test_database_restores_active_conversation_when_cache_is_empty(self):
        customer_id = uuid.uuid4()
        account_id = uuid.uuid4()
        conversation = SimpleNamespace(
            id=uuid.uuid4(),
            customer_id=customer_id,
            account_id=account_id,
            status="active",
        )
        customer = SimpleNamespace(id=customer_id, telegram_id=123456)
        session = _Session(conversation)

        with patch(
            "app.services.userbot.handlers.cache_get",
            new=AsyncMock(return_value=None),
        ), patch(
            "app.services.userbot.handlers.cache_set",
            new=AsyncMock(),
        ) as cache_set:
            restored = await get_or_create_conversation(
                session,
                customer,
                str(account_id),
                language="fa",
            )

        self.assertIs(restored, conversation)
        self.assertEqual(session.added, [])
        cache_set.assert_awaited_once()
        self.assertEqual(cache_set.await_args.kwargs["ttl"], 30 * 24 * 60 * 60)
        self.assertEqual(len(session.executed), 1)
        self.assertIn("conversations", str(session.executed[0]))


if __name__ == "__main__":
    unittest.main()