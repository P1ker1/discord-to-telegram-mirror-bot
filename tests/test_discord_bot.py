import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import discord
from discord import RawMessageUpdateEvent, RawMessageDeleteEvent, RawBulkMessageDeleteEvent

from src.discord_bot import MirrorBot


class TestDiscordBot(unittest.IsolatedAsyncioTestCase):
    """Unit tests for Discord Gateway events (message mirroring, edits, deletions)."""

    def setUp(self):
        self.bot = MirrorBot()
        self.bot._connection = MagicMock()
        # Mock bot's own user
        self.bot._connection.user = MagicMock(id=99999)

    @patch("src.discord_bot.config")
    @patch("src.discord_bot.telegram_bot")
    @patch("src.discord_bot.db")
    async def test_on_message_ignores_other_channel(self, mock_db, mock_tg, mock_config):
        mock_config.discord_channel_id = 12345

        msg = MagicMock(spec=discord.Message)
        msg.channel.id = 99999
        await self.bot.on_message(msg)

        mock_tg.send_channel_post.assert_not_called()
        mock_db.save_mapping.assert_not_called()

    @patch("src.discord_bot.config")
    @patch("src.discord_bot.telegram_bot")
    @patch("src.discord_bot.db")
    async def test_on_message_ignores_bot_when_configured(self, mock_db, mock_tg, mock_config):
        mock_config.discord_channel_id = 12345
        mock_config.mirror_bot_messages = False

        msg = MagicMock(spec=discord.Message)
        msg.channel.id = 12345
        msg.author.bot = True
        msg.author.id = 11111

        await self.bot.on_message(msg)

        mock_tg.send_channel_post.assert_not_called()

    @patch("src.discord_bot.config")
    @patch("src.discord_bot.telegram_bot")
    @patch("src.discord_bot.db")
    async def test_on_message_mirrors_announcement(self, mock_db, mock_tg, mock_config):
        mock_config.discord_channel_id = 12345
        mock_config.telegram_chat_id = "-100123"
        mock_config.enable_message_headers = True
        mock_config.announcement_header = "-- Announcement --"
        mock_config.show_author_header = False
        mock_config.tz = None
        mock_config.mirror_bot_messages = True

        mock_tg.send_channel_post = AsyncMock(return_value=([501], False))
        mock_db.save_mapping = AsyncMock()

        msg = MagicMock(spec=discord.Message)
        msg.id = 88888
        msg.channel.id = 12345
        msg.author.bot = False
        msg.author.display_name = "Alice"
        msg.content = "New event tomorrow!"
        msg.embeds = []
        msg.attachments = []
        msg.guild = None

        await self.bot.on_message(msg)

        mock_tg.send_channel_post.assert_awaited_once()
        mock_db.save_mapping.assert_awaited_once_with(
            discord_msg_id=88888,
            telegram_chat_id="-100123",
            telegram_msg_ids=[501],
            has_media=False
        )

    @patch("src.discord_bot.config")
    @patch("src.discord_bot.telegram_bot")
    @patch("src.discord_bot.db")
    async def test_on_raw_message_delete_synchronizes_deletion(self, mock_db, mock_tg, mock_config):
        mock_config.discord_channel_id = 12345
        mock_db.delete_mapping = AsyncMock(return_value={
            "telegram_chat_id": "-100123",
            "telegram_message_ids": [501, 502],
        })
        mock_tg.delete_channel_post = AsyncMock(return_value=True)

        payload = MagicMock(spec=RawMessageDeleteEvent)
        payload.channel_id = 12345
        payload.message_id = 88888

        await self.bot.on_raw_message_delete(payload)

        mock_db.delete_mapping.assert_awaited_once_with(88888)
        mock_tg.delete_channel_post.assert_awaited_once_with(
            chat_id="-100123",
            message_ids=[501, 502]
        )


if __name__ == "__main__":
    unittest.main()
