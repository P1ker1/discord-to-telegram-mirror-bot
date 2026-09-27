from datetime import datetime
import logging

import aiohttp
import discord
from discord import RawMessageUpdateEvent, RawMessageDeleteEvent, RawBulkMessageDeleteEvent

from src.core.config import config
from src.core.database import db
from src.services.digest_service import digest_service

logger = logging.getLogger("DiscordClient")

class DiscordClient(discord.Client):
    """
    Discord client responsible for listening to announcements, edits, and deletions.
    Delegates all business logic to MirrorService.
    """
    def __init__(self, mirror_service=None):
        intents = discord.Intents.default()
        intents.guilds = True
        intents.messages = True
        intents.message_content = True
        intents.guild_scheduled_events = True

        super().__init__(intents=intents)
        self.mirror_service = mirror_service

    def set_mirror_service(self, mirror_service):
        self.mirror_service = mirror_service

    async def refresh_attachment_url(self, url: str) -> str:
        """Refreshes expired or unexpired Discord CDN attachment URLs via Discord REST API."""
        try:
            api_url = "https://discord.com/api/v10/attachments/refresh-urls"
            headers = {
                "Authorization": f"Bot {config.discord_bot_token}",
                "Content-Type": "application/json",
                "User-Agent": "DiscordBot"
            }
            payload = {"attachment_urls": [url]}
            async with aiohttp.ClientSession() as session:
                async with session.post(api_url, json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        refreshed_list = data.get("refreshed_urls", [])
                        if refreshed_list and "refreshed" in refreshed_list[0]:
                            return refreshed_list[0]["refreshed"]
        except Exception as e:
            logger.warning(f"Failed to refresh Discord attachment URL {url}: {e}")
        return url

    async def setup_hook(self):
        """Pre-connection hook: initialize SQLite database and start background tasks."""
        await db.init_db()

        digest_service.set_bot(self)
        digest_service.start()

    async def on_ready(self):
        """Triggered when the bot establishes connection with Discord."""
        target_channel = self.get_channel(config.discord_channel_id)
        now_local = datetime.now(config.tz)

        logger.info("=" * 60)
        logger.info(f"Bot Online: {self.user} (ID: {self.user.id})")
        if target_channel:
            logger.info(f"Monitoring Discord: #{target_channel.name} ({target_channel.id}) in '{target_channel.guild.name}'")
        else:
            logger.warning(
                f"Could not locate channel ID {config.discord_channel_id}! "
                f"Please verify bot permissions and server membership."
            )
        logger.info(f"Target Telegram Chat: {config.telegram_chat_id}")
        logger.info(f"Timezone: {config.timezone} (Current time: {now_local.strftime('%A %H:%M %Z')})")

        if config.enable_weekly_events:
            logger.info(
                f"Weekly Events Digest: Active | Every {config.weekly_events_day_name} at "
                f"{config.weekly_events_time} {now_local.strftime('%Z')}"
            )
        else:
            logger.info("Weekly Events Digest: Disabled")
        logger.info("=" * 60)

    async def on_message(self, message: discord.Message):
        """Handles new messages posted in the monitored channel."""
        if message.content.strip().lower() in ("!events", "!post-events"):
            logger.info(f"Manual weekly events digest triggered by {message.author}")
            await digest_service.post_weekly_events_digest()
            return

        if self.mirror_service:
            await self.mirror_service.process_message(message)

    async def on_raw_message_edit(self, payload: RawMessageUpdateEvent):
        """Handles message edits on Discord and synchronizes them to Telegram."""
        if self.mirror_service:
            await self.mirror_service.process_message_edit(payload)

    async def on_raw_message_delete(self, payload: RawMessageDeleteEvent):
        """Handles message deletions on Discord and deletes mapped Telegram messages."""
        if self.mirror_service:
            await self.mirror_service.process_message_delete(payload)

    async def on_raw_bulk_message_delete(self, payload: RawBulkMessageDeleteEvent):
        """Handles bulk message deletions on Discord."""
        if self.mirror_service:
            await self.mirror_service.process_bulk_message_delete(payload)

    async def close(self):
        digest_service.stop()
        await super().close()
