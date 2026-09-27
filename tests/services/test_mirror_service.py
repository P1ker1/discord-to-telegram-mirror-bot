import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import discord
from discord import RawMessageUpdateEvent, RawMessageDeleteEvent, RawBulkMessageDeleteEvent

from src.services.mirror_service import MirrorService

class TestMirrorService(unittest.IsolatedAsyncioTestCase):
    """Unit tests for MirrorService (message mirroring, edits, deletions)."""

    def setUp(self):
        self.mock_discord = MagicMock(spec=discord.Client)
        self.mock_discord.user = MagicMock(id=99999)
        self.mock_tg = AsyncMock()
        self.mock_db = AsyncMock()
        self.service = MirrorService(discord_client=self.mock_discord, telegram_client=self.mock_tg, db=self.mock_db)

    @patch("src.services.mirror_service.config")
    async def test_on_message_ignores_other_channel(self, mock_config):
        mock_config.discord_channel_id = 12345
        msg = MagicMock(spec=discord.Message)
        msg.channel.id = 99999

        await self.service.process_message(msg)

        self.mock_tg.send_channel_post.assert_not_called()
        self.mock_db.save_mapping.assert_not_called()

    @patch("src.services.mirror_service.config")
    async def test_on_message_ignores_bot_when_configured(self, mock_config):
        mock_config.discord_channel_id = 12345
        mock_config.mirror_bot_messages = False
        msg = MagicMock(spec=discord.Message)
        msg.channel.id = 12345
        msg.author.bot = True
        msg.author.id = 11111

        await self.service.process_message(msg)

        self.mock_tg.send_channel_post.assert_not_called()

    @patch("src.services.mirror_service.config")
    async def test_on_message_mirrors_announcement(self, mock_config):
        mock_config.discord_channel_id = 12345
        mock_config.telegram_chat_id = "-100123"
        mock_config.enable_message_headers = True
        mock_config.announcement_header = "-- Announcement --"
        mock_config.show_author_header = False
        mock_config.tz = None
        mock_config.mirror_bot_messages = True

        self.mock_tg.send_channel_post = AsyncMock(return_value=([501], False))
        self.mock_db.save_mapping = AsyncMock()

        msg = MagicMock(spec=discord.Message)
        msg.id = 88888
        msg.channel.id = 12345
        msg.author.bot = False
        msg.author.display_name = "Alice"
        msg.content = "New event tomorrow!"
        msg.embeds = []
        msg.attachments = []
        msg.guild = None

        await self.service.process_message(msg)

        self.mock_tg.send_channel_post.assert_awaited_once()
        self.mock_db.save_mapping.assert_awaited_once_with(
            discord_msg_id=88888,
            telegram_chat_id="-100123",
            telegram_msg_ids=[501],
            has_media=False
        )

    @patch("src.services.mirror_service.config")
    async def test_on_raw_message_delete_synchronizes_deletion(self, mock_config):
        mock_config.discord_channel_id = 12345
        self.mock_db.delete_mapping = AsyncMock(return_value={
            "telegram_chat_id": "-100123",
            "telegram_message_ids": [501, 502],
        })
        self.mock_tg.delete_channel_post = AsyncMock(return_value=True)

        payload = MagicMock(spec=RawMessageDeleteEvent)
        payload.channel_id = 12345
        payload.message_id = 88888

        await self.service.process_message_delete(payload)

        self.mock_db.delete_mapping.assert_awaited_once_with(88888)
        self.mock_tg.delete_channel_post.assert_awaited_once_with(
            chat_id="-100123",
            message_ids=[501, 502]
        )

    @patch("src.services.mirror_service.config")
    async def test_on_raw_message_edit_synchronizes_edit(self, mock_config):
        mock_config.discord_channel_id = 12345
        mock_config.announcement_header = "-- Announcement --"
        mock_config.enable_message_headers = True
        mock_config.show_author_header = False
        mock_config.tz = None

        self.mock_db.get_mapping = AsyncMock(return_value={
            "telegram_chat_id": "-100123",
            "telegram_message_ids": [501],
            "has_media": False
        })
        self.mock_tg.edit_channel_post = AsyncMock(return_value=True)

        mock_channel = MagicMock()
        mock_msg = MagicMock(spec=discord.Message)
        mock_msg.content = "Updated announcement content"
        mock_msg.embeds = []
        mock_msg.guild = None
        mock_msg.author.display_name = "Alice"
        mock_channel.fetch_message = AsyncMock(return_value=mock_msg)
        self.mock_discord.get_channel = MagicMock(return_value=mock_channel)

        payload = MagicMock(spec=RawMessageUpdateEvent)
        payload.channel_id = 12345
        payload.message_id = 88888

        await self.service.process_message_edit(payload)

        self.mock_db.get_mapping.assert_awaited_once_with(88888)
        mock_channel.fetch_message.assert_awaited_once_with(88888)
        self.mock_tg.edit_channel_post.assert_awaited_once_with(
            chat_id="-100123",
            message_ids=[501],
            formatted_text="<b>-- Announcement --</b>\n\nUpdated announcement content",
            has_media=False
        )

    @patch("src.services.mirror_service.config")
    async def test_on_raw_message_edit_handles_not_found(self, mock_config):
        mock_config.discord_channel_id = 12345
        self.mock_db.get_mapping = AsyncMock(return_value={
            "telegram_chat_id": "-100123",
            "telegram_message_ids": [501],
            "has_media": False
        })

        mock_channel = MagicMock()
        mock_channel.fetch_message = AsyncMock(side_effect=discord.NotFound(MagicMock(), "Not found"))
        self.mock_discord.get_channel = MagicMock(return_value=mock_channel)

        payload = MagicMock(spec=RawMessageUpdateEvent)
        payload.channel_id = 12345
        payload.message_id = 88888

        await self.service.process_message_edit(payload)
        self.mock_tg.edit_channel_post.assert_not_called()

    @patch("src.services.mirror_service.config")
    async def test_on_raw_bulk_message_delete(self, mock_config):
        mock_config.discord_channel_id = 12345
        self.mock_db.delete_mappings_bulk = AsyncMock(return_value=[
            {"telegram_chat_id": "-100123", "telegram_message_ids": [501]},
            {"telegram_chat_id": "-100123", "telegram_message_ids": [502]},
        ])
        self.mock_tg.delete_channel_post = AsyncMock(return_value=True)

        payload = MagicMock(spec=RawBulkMessageDeleteEvent)
        payload.channel_id = 12345
        payload.message_ids = [88888, 88889]

        await self.service.process_bulk_message_delete(payload)

        self.mock_db.delete_mappings_bulk.assert_awaited_once_with([88888, 88889])
        self.assertEqual(self.mock_tg.delete_channel_post.await_count, 2)

    def test_extract_animation_discord_cdn_link(self):
        msg = MagicMock(spec=discord.Message)
        msg.attachments = []
        msg.embeds = []
        msg.content = "Look at this: https://cdn.discordapp.com/attachments/1475884456287015065/1544537751456587836/og_leo.gif"

        anim_url, cleaned = self.service._extract_animation(msg)
        self.assertEqual(anim_url, "https://cdn.discordapp.com/attachments/1475884456287015065/1544537751456587836/og_leo.gif")
        self.assertEqual(cleaned, "Look at this:")

    def test_extract_animation_discord_embed(self):
        msg = MagicMock(spec=discord.Message)
        msg.attachments = []
        embed = MagicMock()
        embed.type = "image"
        embed.video = None
        embed.image.url = "https://media.discordapp.net/attachments/1475884456287015065/1544537751456587836/og_leo.gif?ex=66f64243"
        embed.thumbnail = None
        embed.url = None
        msg.embeds = [embed]
        msg.content = "https://cdn.discordapp.com/attachments/1475884456287015065/1544537751456587836/og_leo.gif"

        anim_url, cleaned = self.service._extract_animation(msg)
        self.assertIn("og_leo.gif", anim_url)
        self.assertEqual(cleaned, "")

if __name__ == "__main__":
    unittest.main()
