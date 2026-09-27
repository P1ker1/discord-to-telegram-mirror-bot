import os
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

from src.core.config import Config


class TestConfig(unittest.TestCase):
    """Unit tests for the Config class and environment validator."""

    def test_default_values(self):
        """Test default config values when minimal environment variables are present."""
        with patch.dict(os.environ, {}, clear=True):
            cfg = Config()
            self.assertEqual(cfg.discord_bot_token, "")
            self.assertEqual(cfg.discord_channel_id, 0)
            self.assertEqual(cfg.telegram_bot_token, "")
            self.assertEqual(cfg.telegram_chat_id, "")
            self.assertEqual(cfg.timezone, "Europe/Helsinki")
            self.assertTrue(cfg.mirror_bot_messages)
            self.assertFalse(cfg.show_author_header)
            self.assertTrue(cfg.enable_message_headers)
            self.assertEqual(cfg.announcement_header, "-- Announcement --")
            self.assertEqual(cfg.events_header, "-- Upcoming Events --")
            self.assertTrue(cfg.enable_weekly_events)
            self.assertEqual(cfg.weekly_events_day, 0)
            self.assertEqual(cfg.weekly_events_day_name, "Monday")
            self.assertEqual(cfg.weekly_events_time, "10:00")
            self.assertFalse(cfg.post_events_to_discord)
            self.assertEqual(cfg.weekly_events_grace_period_hours, 8)
            self.assertEqual(cfg.database_path, "data/bot.db")
            self.assertEqual(cfg.tz, ZoneInfo("Europe/Helsinki"))

    def test_custom_values(self):
        """Test parsing of custom environment variables."""
        env = {
            "DISCORD_BOT_TOKEN": "custom_discord_token",
            "DISCORD_CHANNEL_ID": "987654321098765432",
            "TELEGRAM_BOT_TOKEN": "custom_telegram_token",
            "TELEGRAM_CHAT_ID": "-1009999999999",
            "TIMEZONE": "Europe/London",
            "MIRROR_BOT_MESSAGES": "false",
            "SHOW_AUTHOR_HEADER": "true",
            "ENABLE_MESSAGE_HEADERS": "0",
            "ANNOUNCEMENT_HEADER": "[Announcement]",
            "EVENTS_HEADER": "[Events]",
            "ENABLE_WEEKLY_EVENTS": "no",
            "WEEKLY_EVENTS_DAY": "4",
            "WEEKLY_EVENTS_TIME": "14:30",
            "POST_EVENTS_TO_DISCORD": "1",
            "WEEKLY_EVENTS_GRACE_PERIOD_HOURS": "12",
            "DATABASE_PATH": "/tmp/custom.db",
        }
        with patch.dict(os.environ, env, clear=True):
            cfg = Config()
            self.assertEqual(cfg.discord_bot_token, "custom_discord_token")
            self.assertEqual(cfg.discord_channel_id, 987654321098765432)
            self.assertEqual(cfg.telegram_bot_token, "custom_telegram_token")
            self.assertEqual(cfg.telegram_chat_id, "-1009999999999")
            self.assertEqual(cfg.timezone, "Europe/London")
            self.assertFalse(cfg.mirror_bot_messages)
            self.assertTrue(cfg.show_author_header)
            self.assertFalse(cfg.enable_message_headers)
            self.assertEqual(cfg.announcement_header, "[Announcement]")
            self.assertEqual(cfg.events_header, "[Events]")
            self.assertFalse(cfg.enable_weekly_events)
            self.assertEqual(cfg.weekly_events_day, 4)
            self.assertEqual(cfg.weekly_events_day_name, "Friday")
            self.assertEqual(cfg.weekly_events_time, "14:30")
            self.assertTrue(cfg.post_events_to_discord)
            self.assertEqual(cfg.weekly_events_grace_period_hours, 12)
            self.assertEqual(cfg.database_path, "/tmp/custom.db")
            self.assertEqual(cfg.tz, ZoneInfo("Europe/London"))

    def test_invalid_day_and_time_handling(self):
        """Test that invalid day of week or invalid time formats fallback safely."""
        env = {
            "WEEKLY_EVENTS_DAY": "99",
            "WEEKLY_EVENTS_TIME": "not-a-time",
            "WEEKLY_EVENTS_GRACE_PERIOD_HOURS": "-5",
        }
        with patch.dict(os.environ, env, clear=True):
            cfg = Config()
            self.assertEqual(cfg.weekly_events_day, 0)
            self.assertEqual(cfg.weekly_events_time, "10:00")
            self.assertEqual(cfg.weekly_events_grace_period_hours, 0)

        env_non_numeric = {
            "WEEKLY_EVENTS_DAY": "monday",
            "WEEKLY_EVENTS_TIME": "25:99",
        }
        with patch.dict(os.environ, env_non_numeric, clear=True):
            cfg = Config()
            self.assertEqual(cfg.weekly_events_day, 0)
            self.assertEqual(cfg.weekly_events_time, "10:00")

    def test_invalid_timezone_fallback(self):
        """Test that an invalid timezone name falls back to UTC."""
        with patch.dict(os.environ, {"TIMEZONE": "Invalid/NonExistent_Zone"}, clear=True):
            cfg = Config()
            self.assertEqual(cfg.tz, ZoneInfo("UTC"))

    def test_validate_missing_and_placeholder_credentials(self):
        """Test that validate() catches unconfigured or placeholder credentials."""
        with patch.dict(os.environ, {}, clear=True):
            cfg = Config()
            errors = cfg.validate(exit_on_error=False)
            self.assertEqual(len(errors), 4)

        placeholders = {
            "DISCORD_BOT_TOKEN": "your_discord_bot_token_here",
            "DISCORD_CHANNEL_ID": "0",
            "TELEGRAM_BOT_TOKEN": "your_telegram_bot_token_here",
            "TELEGRAM_CHAT_ID": "-1001234567890",
        }
        with patch.dict(os.environ, placeholders, clear=True):
            cfg = Config()
            errors = cfg.validate(exit_on_error=False)
            self.assertEqual(len(errors), 4)

    def test_validate_success(self):
        """Test that validate() returns no errors when required credentials are valid."""
        valid_env = {
            "DISCORD_BOT_TOKEN": "valid_discord_token",
            "DISCORD_CHANNEL_ID": "112233445566778899",
            "TELEGRAM_BOT_TOKEN": "valid_telegram_token",
            "TELEGRAM_CHAT_ID": "-1001987654321",
        }
        with patch.dict(os.environ, valid_env, clear=True):
            cfg = Config()
            errors = cfg.validate(exit_on_error=False)
            self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
