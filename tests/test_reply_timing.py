import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.services.userbot.reply_timing import (
    mark_message_read,
    new_reply_deadline,
    wait_for_reply_deadline,
)


class ReplyTimingTests(unittest.IsolatedAsyncioTestCase):
    def test_deadline_is_randomized_within_thirty_to_thirty_five_seconds(self):
        with patch("app.services.userbot.reply_timing.monotonic", return_value=100.0):
            with patch("app.services.userbot.reply_timing.random.uniform", return_value=32.6) as pick:
                self.assertEqual(new_reply_deadline(), 132.6)
        pick.assert_called_once_with(30.0, 35.0)

    async def test_waits_only_for_remaining_time(self):
        with patch("app.services.userbot.reply_timing.monotonic", return_value=10.0):
            with patch("app.services.userbot.reply_timing.sleep", new_callable=AsyncMock) as pause:
                await wait_for_reply_deadline(40.5)
        pause.assert_awaited_once_with(30.5)

    async def test_does_not_add_delay_when_processing_passed_deadline(self):
        with patch("app.services.userbot.reply_timing.monotonic", return_value=20.0):
            with patch("app.services.userbot.reply_timing.sleep", new_callable=AsyncMock) as pause:
                await wait_for_reply_deadline(14.5)
        pause.assert_not_awaited()

    async def test_marks_incoming_message_read_up_to_its_id(self):
        acknowledge = AsyncMock()
        event = SimpleNamespace(
            client=SimpleNamespace(send_read_acknowledge=acknowledge),
            chat_id=12345,
            message=SimpleNamespace(id=678),
        )
        await mark_message_read(event)
        acknowledge.assert_awaited_once_with(12345, max_id=678)


if __name__ == "__main__":
    unittest.main()
