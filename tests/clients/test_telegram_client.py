import unittest
from unittest.mock import AsyncMock, MagicMock
from telegram.error import BadRequest
from telegram.constants import ParseMode

from src.clients.telegram_client import TelegramClient, re_strip_tags
from src.core.models import MediaAttachment


class TestTelegramClient(unittest.IsolatedAsyncioTestCase):
    """Unit tests for TelegramClient client helpers, media detection, and post operations."""

    def setUp(self):
        self.bot_wrapper = TelegramClient(token="123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11")
        self.mock_bot = AsyncMock()
        self.bot_wrapper._bot = self.mock_bot

    def test_re_strip_tags(self):
        self.assertEqual(re_strip_tags("<b>Bold</b> and <i>italic</i>"), "Bold and italic")
        self.assertEqual(re_strip_tags("<a href='http://x'>Link</a>"), "Link")

    async def test_send_animation_url(self):
        self.bot_wrapper.download_file_bytes = AsyncMock(return_value=b"GIF89a...")
        self.mock_bot.send_animation.return_value = MagicMock(message_id=77)

        msg_id = await self.bot_wrapper.send_animation_url("-10012345", "https://cdn.discordapp.com/attachments/1/2/test.gif")
        self.assertEqual(msg_id, 77)
        self.mock_bot.send_animation.assert_awaited_once()
        kwargs = self.mock_bot.send_animation.await_args.kwargs
        self.assertEqual(kwargs["filename"], "animation.gif")

    def test_media_detection(self):
        att_gif = MediaAttachment(url="http://x/dance.gif", content_type="image/gif", filename="dance.gif", is_animation=True)
        att_png = MediaAttachment(url="http://x/image.png", content_type="image/png", filename="image.png")
        att_mp4 = MediaAttachment(url="http://x/clip.mp4", content_type="video/mp4", filename="clip.mp4")
        att_doc = MediaAttachment(url="http://x/doc.pdf", content_type="application/pdf", filename="document.pdf")

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

    async def test_send_single_attachment_gif(self):
        mock_att = MediaAttachment(content_type="image/gif", filename="funny.gif", url="https://cdn.discord.com/funny.gif", is_animation=True)
        self.bot_wrapper.download_file_bytes = AsyncMock(return_value=b"GIF89a...")
        self.mock_bot.send_animation.return_value = MagicMock(message_id=99)
        self.mock_bot.send_message.return_value = MagicMock(message_id=100)

        result = await self.bot_wrapper.send_channel_post(
            chat_id="-10012345",
            formatted_text="Look at this gif!",
            attachments=[mock_att]
        )

        msg_ids, has_media = result
        self.assertEqual(msg_ids, [99, 100])
        self.assertTrue(has_media)
        self.assertEqual(result.text_msg_id, 100)
        self.mock_bot.send_animation.assert_awaited_once()
        call_kwargs = self.mock_bot.send_animation.await_args.kwargs
        self.assertEqual(call_kwargs["filename"], "funny.gif")
        self.mock_bot.send_message.assert_awaited_once()

    async def test_edit_channel_post_with_media_edits_text_message(self):
        # Post has media [100] and text message [101]
        self.mock_bot.edit_message_text.return_value = MagicMock()

        result = await self.bot_wrapper.edit_channel_post(
            chat_id="-10012345",
            message_ids=[100, 101],
            formatted_text="Updated text under media",
            has_media=True,
            text_message_id=101
        )

        self.assertTrue(result)
        self.assertEqual(result.updated_message_ids, [100, 101])
        self.assertEqual(result.updated_text_message_id, 101)
        self.mock_bot.edit_message_text.assert_awaited_once_with(
            chat_id="-10012345",
            message_id=101,
            text="Updated text under media",
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=False
        )

    async def test_edit_channel_post_media_only_adds_text(self):
        # Post originally had only media [100], now edited to include text
        self.mock_bot.send_message.return_value = MagicMock(message_id=102)

        result = await self.bot_wrapper.edit_channel_post(
            chat_id="-10012345",
            message_ids=[100],
            formatted_text="Newly added text",
            has_media=True,
            text_message_id=None
        )

        self.assertTrue(result)
        self.assertEqual(result.updated_message_ids, [100, 102])
        self.assertEqual(result.updated_text_message_id, 102)
        self.mock_bot.send_message.assert_awaited_once()

    async def test_edit_channel_post_empty_text_removes_text_message(self):
        # Post had media [100] and text [101], edited to empty string
        self.mock_bot.delete_message.return_value = True

        result = await self.bot_wrapper.edit_channel_post(
            chat_id="-10012345",
            message_ids=[100, 101],
            formatted_text="",
            has_media=True,
            text_message_id=101
        )

        self.assertTrue(result)
        self.assertEqual(result.updated_message_ids, [100])
        self.assertIsNone(result.updated_text_message_id)
        self.mock_bot.delete_message.assert_awaited_once_with(
            chat_id="-10012345",
            message_id=101
        )


    async def test_send_channel_post_partial_failure_preserves_media_ids(self):
        from telegram.error import TelegramError
        mock_att = MediaAttachment(content_type="image/png", filename="pic.png", url="https://cdn.discord.com/pic.png")
        self.bot_wrapper.download_file_bytes = AsyncMock(return_value=b"PNG...")
        self.mock_bot.send_photo.return_value = MagicMock(message_id=55)
        self.mock_bot.send_message.side_effect = TelegramError("Network failure on text send")

        with self.assertRaises(TelegramError) as ctx:
            await self.bot_wrapper.send_channel_post(
                chat_id="-10012345",
                formatted_text="This text fails",
                attachments=[mock_att]
            )

        self.assertEqual(getattr(ctx.exception, "partial_sent_msg_ids", None), [55])
        self.assertTrue(getattr(ctx.exception, "partial_has_media", False))


if __name__ == "__main__":
    unittest.main()

