import unittest
from unittest.mock import AsyncMock, MagicMock
from datetime import datetime, timezone, timedelta
import discord

from src.services.digest_service import DigestService
from src.utils.telegram_builder import format_upcoming_events_telegram, format_upcoming_events_discord

class TestDigestService(unittest.IsolatedAsyncioTestCase):
    async def test_fetch_upcoming_events_filtering(self):
        service = DigestService()

        now = datetime.now(timezone.utc)
        mock_club = MagicMock()

        # Event within 7 days
        ev_soon = MagicMock()
        ev_soon.status = discord.EventStatus.scheduled
        ev_soon.start_time = now + timedelta(days=2)

        # Event already active within window
        ev_active = MagicMock()
        ev_active.status = discord.EventStatus.active
        ev_active.start_time = now + timedelta(hours=1)

        # Event far in the future (> 7 days)
        ev_future = MagicMock()
        ev_future.status = discord.EventStatus.scheduled
        ev_future.start_time = now + timedelta(days=10)

        # Event completed / cancelled
        ev_past = MagicMock()
        ev_past.status = discord.EventStatus.completed
        ev_past.start_time = now - timedelta(days=1)

        mock_club.fetch_scheduled_events = AsyncMock(return_value=[
            ev_soon, ev_active, ev_future, ev_past
        ])

        results = await service.fetch_upcoming_events(mock_club, days=7)
        self.assertEqual(len(results), 2)
        # Should be sorted chronologically
        self.assertEqual(results[0], ev_active)
        self.assertEqual(results[1], ev_soon)

    async def test_post_weekly_events_digest_destinations(self):
        from unittest.mock import patch
        from src.core.config import config

        service = DigestService()
        mock_bot = MagicMock()
        mock_channel = MagicMock()
        mock_channel.send = AsyncMock()
        mock_club = MagicMock()
        mock_club.fetch_scheduled_events = AsyncMock(return_value=[])
        mock_channel.guild = mock_club
        mock_bot.get_channel = MagicMock(return_value=mock_channel)
        service.set_bot(mock_bot)

        mock_tg_client = MagicMock()
        mock_tg_client.send_channel_post = AsyncMock()
        service.set_telegram_client(mock_tg_client)

        # 1. Test Telegram-only mode (default: post_events_to_discord=False)
        with patch.object(config, "post_events_to_discord", False):
            mock_tg_client.send_channel_post.return_value = ([999], False)
            await service.post_weekly_events_digest()

            mock_channel.send.assert_not_called()
            mock_tg_client.send_channel_post.assert_called_once()

        mock_channel.send.reset_mock()
        mock_tg_client.send_channel_post.reset_mock()

        # 2. Test both Discord and Telegram enabled (post_events_to_discord=True)
        with patch.object(config, "post_events_to_discord", True), \
             patch("src.services.digest_service.db.save_mapping", new_callable=AsyncMock) as mock_save_mapping:
            mock_tg_client.send_channel_post.return_value = ([999], False)
            mock_sent_discord = MagicMock()
            mock_sent_discord.id = 12345
            mock_channel.send.return_value = mock_sent_discord

            await service.post_weekly_events_digest()

            mock_channel.send.assert_called_once()
            mock_tg_client.send_channel_post.assert_called_once()
            mock_save_mapping.assert_awaited_once_with(
                discord_msg_id=12345,
                telegram_chat_id=config.telegram_chat_id,
                telegram_msg_ids=[999],
                has_media=False,
            )

    async def test_weekly_scheduler_grace_window(self):
        """Tests on-schedule dispatch, skip-when-handled, and expired grace window handling."""
        from unittest.mock import patch
        from src.core.config import config
        from src.core.database import db

        service = DigestService()
        service.post_weekly_events_digest = AsyncMock()

        # Fixed Monday 10:00 local time for deterministic test
        monday_scheduled = datetime(2026, 9, 28, 10, 0, 0, tzinfo=config.tz)

        with patch("src.services.digest_service.datetime") as mock_dt, \
             patch.object(config, "weekly_events_day", 0), \
             patch.object(config, "weekly_events_time", "10:00"), \
             patch.object(config, "weekly_events_grace_period_hours", 8), \
             patch.object(db, "get_metadata", new_callable=AsyncMock) as mock_get_meta, \
             patch.object(db, "set_metadata", new_callable=AsyncMock) as mock_set_meta:

            # Case 1: Within 8h grace window (1h after target) -> dispatches & saves to DB
            mock_dt.now.return_value = monday_scheduled + timedelta(hours=1)
            mock_get_meta.return_value = None
            await service.weekly_events_scheduler()
            mock_set_meta.assert_called_with("last_weekly_digest_week", "2026-W39")
            service.post_weekly_events_digest.assert_called_once()

            # Reset mocks for next case
            service.post_weekly_events_digest.reset_mock()
            mock_set_meta.reset_mock()

            # Case 2: Already recorded in DB for this week -> skips without dispatching
            mock_get_meta.return_value = "2026-W39"
            await service.weekly_events_scheduler()
            service.post_weekly_events_digest.assert_not_called()
            mock_set_meta.assert_not_called()

            # Case 3: Beyond grace window (12h after target) -> marks handled, no dispatch
            mock_dt.now.return_value = monday_scheduled + timedelta(hours=12)
            mock_get_meta.return_value = None
            await service.weekly_events_scheduler()
            service.post_weekly_events_digest.assert_not_called()
            mock_set_meta.assert_called_with("last_weekly_digest_week", "2026-W39")

if __name__ == "__main__":
    unittest.main()
