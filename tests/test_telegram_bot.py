import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from telegram.error import BadRequest

from src.telegram_bot import TelegramBot, truncate_caption, re_strip_tags


class TestTelegramBot(unittest.IsolatedAsyncioTestCase):
    """Unit tests for TelegramBot client helpers, media detection, and post operations."""

    def setUp(self):
        self.bot_wrapper = TelegramBot(token="123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11")
        self.mock_bot = AsyncMock()
        self.bot_wrapper._bot = self.mock_bot

    def test_re_strip_tags(self):
        self.assertEqual(re_strip_tags("<b>Bold</b> and <i>italic</i>"), "Bold and italic")
        self.assertEqual(re_strip_tags("<a href='http://x'>Link</a>"), "Link")

    def test_truncate_caption(self):
        # Short caption untouched
        self.assertEqual(truncate_caption("Short text"), "Short text")
        self.assertIsNone(truncate_caption(None))
        self.assertIsNone(truncate_caption(""))

        # Long caption truncated with balanced tags
        long_text = "<b>" + ("Word " * 300) + "</b>"
        truncated = truncate_caption(long_text, limit=1024)
        self.assertLessEqual(len(truncated), 1024)
        self.assertEqual(truncated.count("<b>"), truncated.count("</b>"))

    def test_media_detection(self):
        att_gif = MagicMock(content_type="image/gif", filename="dance.gif")
        att_png = MagicMock(content_type="image/png", filename="image.png")
        att_mp4 = MagicMock(content_type="video/mp4", filename="clip.mp4")
        att_doc = MagicMock(content_type="application/pdf", filename="document.pdf")

        # Animation
        self.assertTrue(self.bot_wrapper._is_animation(att_gif))
        self.assertFalse(self.bot_wrapper._is_animation(att_png))

        # Image
        self.assertTrue(self.bot_wrapper._is_image(att_png))
        self.assertFalse(self.bot_wrapper._is_image(att_gif))
        self.assertFalse(self.bot_wrapper._is_image(att_mp4))

        # Video
        self.assertTrue(self.bot_wrapper._is_video(att_mp4))
        self.assertFalse(self.bot_wrapper._is_video(att_png))
        self.assertFalse(self.bot_wrapper._is_video(att_doc))

    async def test_send_channel_post_text_only(self):
        mock_msg = MagicMock(message_id=42)
        self.mock_bot.send_message.return_value = mock_msg

        msg_ids, has_media = await self.bot_wrapper.send_channel_post(
            chat_id="-10012345",
            formatted_text="Test announcement",
            attachments=[]
        )

        self.assertEqual(msg_ids, [42])
        self.assertFalse(has_media)
        self.mock_bot.send_message.assert_awaited_once()

    async def test_edit_channel_post_success(self):
        self.mock_bot.edit_message_text.return_value = MagicMock()

        result = await self.bot_wrapper.edit_channel_post(
            chat_id="-10012345",
            message_ids=[42],
            formatted_text="Updated announcement",
            has_media=False
        )

        self.assertTrue(result)
        self.mock_bot.edit_message_text.assert_awaited_once()

    async def test_edit_channel_post_not_modified(self):
        self.mock_bot.edit_message_text.side_effect = BadRequest("Message is not modified")

        result = await self.bot_wrapper.edit_channel_post(
            chat_id="-10012345",
            message_ids=[42],
            formatted_text="Same text",
            has_media=False
        )

        self.assertTrue(result)

    async def test_delete_channel_post(self):
        self.mock_bot.delete_message.return_value = True

        result = await self.bot_wrapper.delete_channel_post(
            chat_id="-10012345",
            message_ids=[101, 102]
        )

        self.assertTrue(result)
        self.assertEqual(self.mock_bot.delete_message.await_count, 2)


if __name__ == "__main__":
    unittest.main()
