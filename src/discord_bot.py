from datetime import datetime
import logging

import discord
from discord import RawMessageUpdateEvent, RawMessageDeleteEvent, RawBulkMessageDeleteEvent

from src.config import config
from src.database import db
from src.formatter import format_announcement
from src.scheduler import scheduler
from src.telegram_bot import telegram_bot

logger = logging.getLogger("DiscordTelegramMirror")

class MirrorBot(discord.Client):
    """
    Discord client responsible for listening to announcements, edits, and deletions
    and synchronizing them with Telegram in real-time.
    """
    def __init__(self):
        intents = discord.Intents.default()
        intents.guilds = True
        intents.messages = True
        intents.message_content = True
        intents.guild_scheduled_events = True

        super().__init__(intents=intents)

    async def setup_hook(self):
        """Pre-connection hook: initialize SQLite database and start background tasks."""
        await db.init_db()

        # Connect the bot client to the scheduler and start background tasks
        scheduler.set_bot(self)
        scheduler.start()

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
        # 1. Filter to designated announcements channel
        if message.channel.id != config.discord_channel_id:
            return

        # 2. Prevent echoing own messages
        if message.author == self.user:
            return

        # 3. Manual weekly events digest trigger for testing
        if message.content.strip().lower() in ("!events", "!post-events"):
            logger.info(f"Manual weekly events digest triggered by {message.author}")
            await scheduler.post_weekly_events_digest()
            return

        # 4. Check bot mirroring preference
        if message.author.bot and not config.mirror_bot_messages:
            logger.debug(f"Ignoring bot message from {message.author} (config.mirror_bot_messages={config.mirror_bot_messages})")
            return

        # 5. Check if message has content, embeds, or attachments
        if not message.content and not message.embeds and not message.attachments:
            logger.debug(f"Message {message.id} has no text or attachments. Skipping.")
            return

        logger.info(f"New announcement from {message.author} (Discord ID: {message.id})")

        try:
            author_name = message.author.display_name if hasattr(message.author, "display_name") else str(message.author)
            header = config.announcement_header if config.enable_message_headers else None

            # Format text & embeds to Telegram HTML
            formatted_text = format_announcement(
                content=message.content,
                embeds=message.embeds,
                guild=message.guild,
                author_name=author_name,
                show_author=config.show_author_header,
                header=header,
                tz=config.tz
            )

            # Send to Telegram
            sent_msg_ids, has_media = await telegram_bot.send_channel_post(
                chat_id=config.telegram_chat_id,
                formatted_text=formatted_text,
                attachments=message.attachments
            )

            # Persist mapping to SQLite
            await db.save_mapping(
                discord_msg_id=message.id,
                telegram_chat_id=config.telegram_chat_id,
                telegram_msg_ids=sent_msg_ids,
                has_media=has_media
            )
            logger.info(f"Mirrored message {message.id} to Telegram message(s): {sent_msg_ids}")

        except Exception as e:
            logger.error(f"Failed to mirror message {message.id}: {e}", exc_info=True)

    async def on_raw_message_edit(self, payload: RawMessageUpdateEvent):
        """Handles message edits on Discord and synchronizes them to Telegram."""
        if payload.channel_id != config.discord_channel_id:
            return

        mapping = await db.get_mapping(payload.message_id)
        if not mapping:
            return

        logger.info(f"Edit detected for Discord ID: {payload.message_id}")

        try:
            # Fetch fresh message from Discord API (payload.cached_message is pre-edit in raw events)
            channel = self.get_channel(payload.channel_id) or await self.fetch_channel(payload.channel_id)
            message = await channel.fetch_message(payload.message_id)

            author_name = message.author.display_name if hasattr(message.author, "display_name") else str(message.author)
            header = config.announcement_header if config.enable_message_headers else None

            formatted_text = format_announcement(
                content=message.content,
                embeds=message.embeds,
                guild=message.guild,
                author_name=author_name,
                show_author=config.show_author_header,
                header=header,
                tz=config.tz
            )

            success = await telegram_bot.edit_channel_post(
                chat_id=mapping["telegram_chat_id"],
                message_ids=mapping["telegram_message_ids"],
                formatted_text=formatted_text,
                has_media=mapping["has_media"]
            )
            if success:
                logger.info(f"Updated Telegram message for Discord ID: {payload.message_id}")

        except discord.NotFound:
            logger.warning(f"Message {payload.message_id} was deleted before edit could be processed.")
        except Exception as e:
            logger.error(f"Error handling message edit for {payload.message_id}: {e}", exc_info=True)

    async def on_raw_message_delete(self, payload: RawMessageDeleteEvent):
        """Handles message deletions on Discord and deletes mapped Telegram messages."""
        if payload.channel_id != config.discord_channel_id:
            return

        mapping = await db.delete_mapping(payload.message_id)
        if not mapping:
            return

        logger.info(f"Deletion detected for Discord ID: {payload.message_id}. Removing from Telegram...")
        try:
            await telegram_bot.delete_channel_post(
                chat_id=mapping["telegram_chat_id"],
                message_ids=mapping["telegram_message_ids"]
            )
            logger.info(f"Deleted Telegram message(s) {mapping['telegram_message_ids']}")
        except Exception as e:
            logger.error(f"Error deleting Telegram message for Discord ID {payload.message_id}: {e}", exc_info=True)

    async def on_raw_bulk_message_delete(self, payload: RawBulkMessageDeleteEvent):
        """Handles bulk message deletions on Discord."""
        if payload.channel_id != config.discord_channel_id:
            return

        logger.info(f"Bulk deletion detected ({len(payload.message_ids)} messages)")
        deleted_mappings = await db.delete_mappings_bulk(list(payload.message_ids))

        for mapping in deleted_mappings:
            try:
                await telegram_bot.delete_channel_post(
                    chat_id=mapping["telegram_chat_id"],
                    message_ids=mapping["telegram_message_ids"]
                )
            except Exception as e:
                logger.error(f"Error deleting bulk message mapping: {e}")

    async def close(self):
        scheduler.stop()
        await super().close()
