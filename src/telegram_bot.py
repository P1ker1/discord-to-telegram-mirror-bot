import asyncio
import io
import logging
import re
from typing import Optional, Union

import aiohttp
import discord
from telegram import Bot, InputMediaPhoto, InputMediaVideo, InputMediaDocument
from telegram.constants import ParseMode
from telegram.error import TelegramError, BadRequest, RetryAfter

from src.config import config
from src.formatter import _close_unclosed_tags

logger = logging.getLogger(__name__)

def re_strip_tags(text: str) -> str:
    """Helper to strip simple HTML tags for plain-text fallback."""
    return re.sub(r"<[^>]+>", "", text)

def truncate_caption(text: Optional[str], limit: int = 1024) -> Optional[str]:
    """Safely truncates caption to Telegram limit while balancing HTML tags."""
    if not text:
        return None
    if len(text) <= limit:
        return text
    return _close_unclosed_tags(text[:limit - 10])

class TelegramBot:
    def __init__(self, token: Optional[str] = None):
        self.token = token or config.telegram_bot_token
        self._bot: Optional[Bot] = None

    @property
    def bot(self) -> Bot:
        if self._bot is None:
            self._bot = Bot(token=self.token)
        return self._bot

    async def download_file_bytes(self, url: str) -> Optional[bytes]:
        """Download media bytes from Discord CDN."""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                    if resp.status == 200:
                        return await resp.read()
                    logger.warning(f"Failed to download attachment from {url}, status: {resp.status}")
        except Exception as e:
            logger.error(f"Error downloading attachment from {url}: {e}")
        return None

    def _is_animation(self, attachment: discord.Attachment) -> bool:
        if attachment.content_type == "image/gif":
            return True
        return attachment.filename.lower().endswith(".gif")

    def _is_image(self, attachment: discord.Attachment) -> bool:
        if self._is_animation(attachment):
            return False
        if attachment.content_type and attachment.content_type.startswith("image/"):
            return True
        return attachment.filename.lower().endswith((".png", ".jpg", ".jpeg", ".webp"))

    def _is_video(self, attachment: discord.Attachment) -> bool:
        if attachment.content_type and attachment.content_type.startswith("video/"):
            return True
        return attachment.filename.lower().endswith((".mp4", ".mov", ".mkv", ".webm"))

    async def _send_single_attachment(
        self,
        chat_id: Union[str, int],
        attachment: discord.Attachment,
        caption: Optional[str],
        parse_mode: Optional[str]
    ) -> int:
        """Helper to upload and send a single photo, video, animation (GIF), or generic document attachment."""
        file_bytes = await self.download_file_bytes(attachment.url)
        file_data = io.BytesIO(file_bytes) if file_bytes else attachment.url
        cap = truncate_caption(caption)

        if self._is_animation(attachment):
            msg = await self.bot.send_animation(
                chat_id=chat_id,
                animation=file_data,
                caption=cap,
                parse_mode=parse_mode
            )
        elif self._is_image(attachment):
            msg = await self.bot.send_photo(
                chat_id=chat_id,
                photo=file_data,
                caption=cap,
                parse_mode=parse_mode
            )
        elif self._is_video(attachment):
            msg = await self.bot.send_video(
                chat_id=chat_id,
                video=file_data,
                caption=cap,
                parse_mode=parse_mode
            )
        else:
            msg = await self.bot.send_document(
                chat_id=chat_id,
                document=file_data,
                filename=attachment.filename,
                caption=cap,
                parse_mode=parse_mode
            )
        return msg.message_id

    async def send_channel_post(
        self,
        chat_id: Union[str, int],
        formatted_text: str,
        attachments: list[discord.Attachment],
        disable_web_page_preview: bool = False
    ) -> tuple[list[int], bool]:
        """
        Sends a post to the target Telegram chat/channel.
        Returns: (list of sent Telegram message IDs, whether the message contains media)
        """
        bot = self.bot
        sent_msg_ids: list[int] = []
        has_media = False

        try:
            # Case 1: No attachments -> send regular text message
            if not attachments:
                msg = await bot.send_message(
                    chat_id=chat_id,
                    text=formatted_text or "(Empty message)",
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=disable_web_page_preview
                )
                sent_msg_ids.append(msg.message_id)
                return sent_msg_ids, False

            # Case 2: Has attachments
            has_media = True

            # Telegram media caption limit is 1024 characters.
            send_caption_separately = len(formatted_text) > 1000
            caption = "" if send_caption_separately else formatted_text

            if len(attachments) == 1:
                msg_id = await self._send_single_attachment(
                    chat_id=chat_id,
                    attachment=attachments[0],
                    caption=caption or None,
                    parse_mode=ParseMode.HTML if caption else None
                )
                sent_msg_ids.append(msg_id)
            else:
                # Multiple attachments: build media album in chunks of up to 10 items (Telegram API limit)
                for chunk_start in range(0, len(attachments), 10):
                    chunk = attachments[chunk_start:chunk_start + 10]
                    media_group = []
                    for i, att in enumerate(chunk):
                        is_first = (chunk_start == 0 and i == 0)
                        item_caption = truncate_caption(caption) if (is_first and caption) else None
                        parse_mode = ParseMode.HTML if item_caption else None

                        file_bytes = await self.download_file_bytes(att.url)
                        file_data = io.BytesIO(file_bytes) if file_bytes else att.url

                        if self._is_image(att):
                            media_group.append(InputMediaPhoto(media=file_data, caption=item_caption, parse_mode=parse_mode))
                        elif self._is_video(att):
                            media_group.append(InputMediaVideo(media=file_data, caption=item_caption, parse_mode=parse_mode))
                        else:
                            media_group.append(InputMediaDocument(media=file_data, caption=item_caption, parse_mode=parse_mode))

                    messages = await bot.send_media_group(chat_id=chat_id, media=media_group)
                    sent_msg_ids.extend([m.message_id for m in messages])

            # If caption was too long for the media, send text message immediately following
            if send_caption_separately and formatted_text:
                followup_msg = await bot.send_message(
                    chat_id=chat_id,
                    text=formatted_text,
                    parse_mode=ParseMode.HTML
                )
                sent_msg_ids.append(followup_msg.message_id)

        except BadRequest as e:
            logger.warning(f"Telegram BadRequest during send ({e}). Retrying with plain-text fallback...")
            try:
                plain = re_strip_tags(formatted_text) if formatted_text else "(Empty message)"
                if attachments and len(attachments) == 1:
                    msg_id = await self._send_single_attachment(
                        chat_id=chat_id,
                        attachment=attachments[0],
                        caption=plain,
                        parse_mode=None
                    )
                    sent_msg_ids.append(msg_id)
                    return sent_msg_ids, True
                else:
                    fallback_msg = await bot.send_message(chat_id=chat_id, text=plain)
                    sent_msg_ids.append(fallback_msg.message_id)
                    return sent_msg_ids, False
            except Exception as fallback_err:
                logger.error(f"Fallback plain-text dispatch failed: {fallback_err}")
                raise
        except TelegramError as e:
            logger.error(f"Telegram error sending announcement: {e}")
            raise

        return sent_msg_ids, has_media

    async def edit_channel_post(
        self,
        chat_id: Union[str, int],
        message_ids: list[int],
        formatted_text: str,
        has_media: bool
    ) -> bool:
        """Edits the text or caption of an existing Telegram channel post."""
        bot = self.bot
        if not message_ids:
            return False

        target_msg_id = message_ids[0]
        try:
            if has_media:
                caption = truncate_caption(formatted_text) or ""
                await bot.edit_message_caption(
                    chat_id=chat_id,
                    message_id=target_msg_id,
                    caption=caption or None,
                    parse_mode=ParseMode.HTML if caption else None
                )
            else:
                await bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=target_msg_id,
                    text=formatted_text or "(Empty message)",
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=False
                )
            logger.info(f"Successfully edited Telegram message {target_msg_id} in {chat_id}")
            return True
        except BadRequest as e:
            err_msg = str(e).lower()
            if "message is not modified" in err_msg:
                logger.debug(f"Telegram message {target_msg_id} was already up-to-date.")
                return True
            if "can't parse entities" in err_msg or "entity" in err_msg:
                logger.warning(f"HTML entity parsing failed on edit: {e}. Retrying with plain text.")
                plain = re_strip_tags(formatted_text) if formatted_text else "(Empty message)"
                try:
                    if has_media:
                        await bot.edit_message_caption(
                            chat_id=chat_id,
                            message_id=target_msg_id,
                            caption=plain[:1024] or None
                        )
                    else:
                        await bot.edit_message_text(
                            chat_id=chat_id,
                            message_id=target_msg_id,
                            text=plain
                        )
                    return True
                except Exception as inner_e:
                    logger.error(f"Fallback plain text edit failed: {inner_e}")
            logger.error(f"Failed to edit Telegram message {target_msg_id}: {e}")
            return False
        except TelegramError as e:
            logger.error(f"Telegram error editing message {target_msg_id}: {e}")
            return False

    async def delete_channel_post(
        self,
        chat_id: Union[str, int],
        message_ids: list[int]
    ) -> bool:
        """Deletes one or more messages linked to a post on Telegram with rate limit safety."""
        bot = self.bot
        success = True
        for i, msg_id in enumerate(message_ids):
            try:
                await bot.delete_message(chat_id=chat_id, message_id=msg_id)
                logger.info(f"Successfully deleted Telegram message {msg_id} in {chat_id}")
                # Rate limit pacing
                if len(message_ids) > 1 and i < len(message_ids) - 1:
                    await asyncio.sleep(0.05)
            except RetryAfter as e:
                logger.warning(f"Hit Telegram rate limit during delete, retrying after {e.retry_after}s")
                await asyncio.sleep(e.retry_after)
                try:
                    await bot.delete_message(chat_id=chat_id, message_id=msg_id)
                    logger.info(f"Successfully deleted Telegram message {msg_id} on retry")
                except Exception as retry_err:
                    logger.error(f"Failed to delete Telegram message {msg_id} after retry: {retry_err}")
                    success = False
            except BadRequest as e:
                if "message to delete not found" in str(e).lower():
                    logger.debug(f"Telegram message {msg_id} was already deleted.")
                else:
                    logger.warning(f"Could not delete Telegram message {msg_id}: {e}")
                    success = False
            except TelegramError as e:
                logger.error(f"Telegram error deleting message {msg_id}: {e}")
                success = False

        return success

telegram_bot = TelegramBot()
