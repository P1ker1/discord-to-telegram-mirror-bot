import logging
import os
import sys
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

logger = logging.getLogger(__name__)

DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

class Config:
    """
    Reads, validates, and provides typed access to all settings in .env.
    All user-configurable options reside in .env.
    """
    def __init__(self):
        # 1. Discord Settings
        self.discord_bot_token: str = os.getenv("DISCORD_BOT_TOKEN", "").strip()
        channel_id_raw = os.getenv("DISCORD_CHANNEL_ID", "").strip()
        self.discord_channel_id: int = int(channel_id_raw) if channel_id_raw.isdigit() else 0

        # 2. Telegram Settings
        self.telegram_bot_token: str = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
        self.telegram_chat_id: str = os.getenv("TELEGRAM_CHAT_ID", "").strip()

        # 3. General & Timezone Settings
        # Defaults to Europe/Helsinki for Finnish local time (EET / EEST)
        self.timezone: str = os.getenv("TIMEZONE", "Europe/Helsinki").strip()

        # 4. Bot Behavior Options
        self.mirror_bot_messages: bool = os.getenv("MIRROR_BOT_MESSAGES", "true").lower() in ("true", "1", "yes")
        self.show_author_header: bool = os.getenv("SHOW_AUTHOR_HEADER", "false").lower() in ("true", "1", "yes")

        # 5. Telegram Category Headers
        self.enable_message_headers: bool = os.getenv("ENABLE_MESSAGE_HEADERS", "true").lower() in ("true", "1", "yes")
        self.announcement_header: str = os.getenv("ANNOUNCEMENT_HEADER", "-- Announcement --").strip()
        self.events_header: str = os.getenv("EVENTS_HEADER", "-- Upcoming Events --").strip()

        # 6. Weekly Events Digest
        self.enable_weekly_events: bool = os.getenv("ENABLE_WEEKLY_EVENTS", "true").lower() in ("true", "1", "yes")
        # 0 = Monday, 1 = Tuesday, ..., 6 = Sunday
        try:
            day_val = int(os.getenv("WEEKLY_EVENTS_DAY", "0"))
            self.weekly_events_day: int = day_val if 0 <= day_val <= 6 else 0
        except ValueError:
            logger.warning("Invalid WEEKLY_EVENTS_DAY in .env. Defaulting to 0 (Monday).")
            self.weekly_events_day = 0

        # Time to post digest: configured in local time (e.g. 10:00 or 13:30)
        time_local = os.getenv("WEEKLY_EVENTS_TIME", "").strip()
        time_utc_legacy = os.getenv("WEEKLY_EVENTS_TIME_UTC", "").strip()

        if time_local:
            try:
                h, m = map(int, time_local.split(":"))
                if 0 <= h <= 23 and 0 <= m <= 59:
                    self.weekly_events_time: str = f"{h:02d}:{m:02d}"
                else:
                    logger.warning(f"Invalid WEEKLY_EVENTS_TIME '{time_local}'. Defaulting to '10:00'.")
                    self.weekly_events_time = "10:00"
            except Exception:
                logger.warning(f"Invalid format for WEEKLY_EVENTS_TIME '{time_local}'. Expected HH:MM. Defaulting to '10:00'.")
                self.weekly_events_time = "10:00"
        elif time_utc_legacy:
            # Backwards compatibility: convert legacy UTC time into configured local timezone
            try:
                utc_h, utc_m = map(int, time_utc_legacy.split(":"))
                dummy_utc = datetime.now(timezone.utc).replace(hour=utc_h, minute=utc_m, second=0, microsecond=0)
                self.weekly_events_time = dummy_utc.astimezone(self.tz).strftime("%H:%M")
                logger.info(f"Converted legacy WEEKLY_EVENTS_TIME_UTC={time_utc_legacy} to local time {self.weekly_events_time} ({self.timezone}).")
            except Exception:
                self.weekly_events_time = time_utc_legacy
        else:
            self.weekly_events_time = "10:00"

        self.post_events_to_discord: bool = os.getenv("POST_EVENTS_TO_DISCORD", "false").lower() in ("true", "1", "yes")

        # Grace window in hours to catch up on missed weekly event digests after downtime
        try:
            self.weekly_events_grace_period_hours: int = max(0, int(os.getenv("WEEKLY_EVENTS_GRACE_PERIOD_HOURS", "8")))
        except ValueError:
            self.weekly_events_grace_period_hours = 8

        # 7. SQLite Storage Path
        self.database_path: str = os.getenv("DATABASE_PATH", "data/bot.db").strip()

    @property
    def tz(self) -> ZoneInfo:
        """Returns the configured ZoneInfo timezone object with fallback to UTC."""
        try:
            return ZoneInfo(self.timezone)
        except Exception as e:
            logger.warning(f"Invalid timezone '{self.timezone}': {e}. Falling back to UTC.")
            return ZoneInfo("UTC")

    @property
    def weekly_events_day_name(self) -> str:
        """Returns the human-readable day name (e.g. 'Monday', 'Friday')."""
        if 0 <= self.weekly_events_day <= 6:
            return DAY_NAMES[self.weekly_events_day]
        return f"Day {self.weekly_events_day}"

    def validate(self, exit_on_error: bool = True) -> list[str]:
        """Validate that all mandatory credentials exist in .env before starting."""
        errors = []
        if not self.discord_bot_token or self.discord_bot_token == "your_discord_bot_token_here":
            errors.append("DISCORD_BOT_TOKEN is missing or not configured in .env.")
        if not self.discord_channel_id:
            errors.append("DISCORD_CHANNEL_ID is missing or not a valid numeric ID in .env.")
        if not self.telegram_bot_token or self.telegram_bot_token == "your_telegram_bot_token_here":
            errors.append("TELEGRAM_BOT_TOKEN is missing or not configured in .env.")
        if not self.telegram_chat_id or self.telegram_chat_id == "-1001234567890":
            errors.append("TELEGRAM_CHAT_ID is missing or not configured in .env.")

        if errors and exit_on_error:
            print("\n" + "=" * 50)
            print("[CONFIG ERROR] Missing credentials in .env:")
            for err in errors:
                print(f"  ❌ {err}")
            print("=" * 50)
            print("Please edit your .env file to fill in your Discord & Telegram tokens.\n")
            sys.exit(1)

        return errors

config = Config()
