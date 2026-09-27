import asyncio
from datetime import datetime, timezone, timedelta
import logging
from typing import Optional

import discord
from discord.ext import tasks

from src.core.config import config
from src.core.database import db
from src.utils.telegram_builder import (
    format_upcoming_events_telegram,
    format_upcoming_events_discord
)


logger = logging.getLogger(__name__)

class DigestService:
    """Centralized background task DigestService for recurring jobs."""

    def __init__(self, bot: Optional[discord.Client] = None, telegram_client=None):
        self.bot = bot
        self.telegram_client = telegram_client

    def set_bot(self, bot: discord.Client):
        self.bot = bot

    def set_telegram_client(self, telegram_client):
        self.telegram_client = telegram_client

    async def fetch_upcoming_events(self, guild: discord.Guild, days: int = 7) -> list[discord.ScheduledEvent]:
        """Fetch scheduled events for the club within the given number of days."""
        all_events = await guild.fetch_scheduled_events()
        now = datetime.now(timezone.utc)
        cutoff = now + timedelta(days=days)

        upcoming = [
            ev for ev in all_events
            if ev.status in (discord.EventStatus.scheduled, discord.EventStatus.active)
            and ev.start_time and now <= ev.start_time <= cutoff
        ]
        upcoming.sort(key=lambda e: e.start_time)
        return upcoming

    async def post_weekly_events_digest(self):
        """Fetches Discord Scheduled Events for the next 7 days and posts the digest."""
        if not self.bot:
            logger.error("DigestService: Cannot post weekly events, bot instance not set.")
            return

        target_channel = self.bot.get_channel(config.discord_channel_id)
        if not target_channel:
            logger.error(f"Cannot post weekly events: channel {config.discord_channel_id} not found.")
            return

        guild = target_channel.guild
        logger.info(f"Fetching upcoming scheduled events for club '{guild.name}'...")
        try:
            upcoming = await self.fetch_upcoming_events(guild, days=7)
        except Exception as e:
            logger.error(f"Failed to fetch scheduled events: {e}", exc_info=True)
            return

        logger.info(f"Found {len(upcoming)} upcoming event(s) for the next 7 days.")

        discord_sent_msg = None
        # 1. Post to Discord announcements channel if enabled
        if config.post_events_to_discord:
            try:
                discord_content = format_upcoming_events_discord(upcoming)
                discord_sent_msg = await target_channel.send(discord_content)
                logger.info(f"Posted weekly events digest to Discord (Message ID: {discord_sent_msg.id})")
            except Exception as e:
                logger.error(f"Failed to post events digest to Discord: {e}", exc_info=True)

        # 2. Post to Telegram announcements channel
        tg_sent_ids = []
        try:
            header = config.events_header if config.enable_message_headers else None
            tg_text = format_upcoming_events_telegram(upcoming, header=header, tz=config.tz)
            tg_sent_ids, _ = await self.telegram_client.send_channel_post(
                chat_id=config.telegram_chat_id,
                formatted_text=tg_text,
                attachments=[],
                disable_web_page_preview=True
            )
            logger.info(f"Posted weekly events digest to Telegram: {tg_sent_ids}")
        except Exception as e:
            logger.error(f"Failed to post events digest to Telegram: {e}", exc_info=True)

        # 3. If posted to both, persist mapping in SQLite so deletions on Discord remove it on Telegram
        if discord_sent_msg and tg_sent_ids:
            await db.save_mapping(
                discord_msg_id=discord_sent_msg.id,
                telegram_chat_id=config.telegram_chat_id,
                telegram_msg_ids=tg_sent_ids,
                has_media=False
            )
            logger.debug(f"Saved database mapping for weekly events digest (Discord {discord_sent_msg.id} -> Telegram {tg_sent_ids})")

    @tasks.loop(seconds=30)
    async def weekly_events_scheduler(self):
        """
        Periodically checks if it is time to dispatch the weekly upcoming events digest.
        Uses persistent SQLite tracking and a configurable grace window to catch missed dispatches
        due to bot downtime or server reboots.
        """
        now = datetime.now(config.tz)
        week_key = now.strftime("%Y-W%W")

        # 1. Check if already dispatched or marked handled for this week
        try:
            last_handled_week = await db.get_metadata("last_weekly_digest_week")
            if last_handled_week == week_key:
                return
        except Exception as e:
            logger.error(f"Error querying database for weekly digest metadata: {e}")
            return

        # 2. Calculate scheduled target time for the current week
        try:
            target_hour, target_min = map(int, config.weekly_events_time.split(":"))
        except ValueError:
            target_hour, target_min = 10, 0

        # Start of current week (Monday 00:00:00 local time)
        start_of_week = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=now.weekday())
        scheduled_dt = start_of_week + timedelta(
            days=config.weekly_events_day,
            hours=target_hour,
            minutes=target_min
        )

        elapsed = (now - scheduled_dt).total_seconds()

        # If target time has not arrived yet this week, wait
        if elapsed < 0:
            return

        # 3. Target time has arrived or passed; evaluate against configured grace window
        grace_period_seconds = config.weekly_events_grace_period_hours * 3600
        if elapsed <= grace_period_seconds:
            logger.info(
                f"Weekly events digest due for {week_key} (scheduled: {scheduled_dt.strftime('%A %H:%M %Z')}, "
                f"delay: {elapsed / 60:.1f} mins). Dispatching..."
            )
            # Record in SQLite before dispatching to prevent duplicate triggers
            await db.set_metadata("last_weekly_digest_week", week_key)
            await self.post_weekly_events_digest()
        else:
            # Scheduled time was missed beyond the configured grace window (e.g. server down for days or fresh install)
            logger.info(
                f"Weekly events digest for {week_key} was missed by {elapsed / 3600:.1f} hours "
                f"(exceeds {config.weekly_events_grace_period_hours}h grace window). Marking as handled to prevent stale digest."
            )
            await db.set_metadata("last_weekly_digest_week", week_key)

    def start(self):
        """Starts the background DigestService if configured."""
        if config.enable_weekly_events and not self.weekly_events_scheduler.is_running():
            self.weekly_events_scheduler.start()
            logger.info(
                f"Weekly events DigestService started (Target: {config.weekly_events_day_name}s "
                f"at {config.weekly_events_time} {config.timezone})"
            )

    def stop(self):
        """Stops the background DigestService."""
        if self.weekly_events_scheduler.is_running():
            self.weekly_events_scheduler.cancel()

digest_service = DigestService()
