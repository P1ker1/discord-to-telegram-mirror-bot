import asyncio
import html
import io
import logging
import re
from typing import Optional, Union

import aiohttp
import discord
from telegram import Bot, InputMediaPhoto, InputMediaVideo, InputMediaDocument
from telegram.constants import ParseMode
from telegram.error import TelegramError, BadRequest, RetryAfter

from src.core.config import config

logger = logging.getLogger(__name__)

def re_strip_tags(text: str) -> str:
    """Helper to strip simple HTML tags and unescape entities for plain-text fallback."""
    if not text:
        return ""
    return html.unescape(re.sub(r"<[^>]+>", "", text))

class SendPostResult(tuple):
    """
    Subclass of 2-tuple (sent_msg_ids, has_media) that preserves backward compatibility
    with 2-element tuple unpacking while carrying text_msg_id as an attribute.
    """
    sent_msg_ids: list[int]
    has_media: bool
    text_msg_id: Optional[int]
    followup_message_id: Optional[int]

    def __new__(cls, sent_msg_ids: list[int], has_media: bool, text_msg_id: Optional[int] = None):
        instance = super().__new__(cls, (sent_msg_ids, has_media))
        instance.sent_msg_ids = sent_msg_ids
        instance.has_media = has_media
        instance.text_msg_id = text_msg_id
        instance.followup_message_id = text_msg_id  # alias
        return instance

class EditPostResult:
    """
    Result of edit_channel_post that evaluates as boolean while providing updated IDs.
    """
    def __init__(self, success: bool, updated_message_ids: list[int], updated_text_message_id: Optional[int] = None):
        self.success = success
        self.updated_message_ids = updated_message_ids
        self.updated_text_message_id = updated_text_message_id
        self.updated_followup_message_id = updated_text_message_id  # alias

    def __bool__(self) -> bool:
        return self.success

class TelegramClient:
    def __init__(self, token: Optional[str] = None):
        self.token = token or config.telegram_bot_token
        self._bot: Optional[Bot] = None

    @property
    def bot(self) -> Bot:
        if self._bot is None:
            self._bot = Bot(token=self.token)
        return self._bot

    async def download_file_bytes(self, url: str) -> Optional[bytes]:
        """Download media bytes from a given URL."""
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        try:
            async with aiohttp.ClientSession(headers=headers) as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                    if resp.status == 200:
                        return await resp.read()
                    logger.warning(f"Failed to download media from {url}, status: {resp.status}")
        except Exception as e:
            logger.error(f"Error downloading media from {url}: {e}")
        return None

    def _is_animation(self, attachment: discord.Attachment) -> bool:
        if attachment.content_type == "image/gif":
            return True
        filename = (attachment.filename or "").lower()
        return filename.endswith(".gif")

    def _is_image(self, attachment: discord.Attachment) -> bool:
        if self._is_animation(attachment):
            return False
        if attachment.content_type and attachment.content_type.startswith("image/"):
            return True
        filename = (attachment.filename or "").lower()
        return filename.endswith((".png", ".jpg", ".jpeg", ".webp"))

    def _is_video(self, attachment: discord.Attachment) -> bool:
        if attachment.content_type and attachment.content_type.startswith("video/"):
            return True
        filename = (attachment.filename or "").lower()
        return filename.endswith((".mp4", ".mov", ".mkv", ".webm"))

    async def _send_single_attachment(
        self,
        chat_id: Union[str, int],
        attachment: discord.Attachment
    ) -> int:
        """Helper to upload and send a single photo, video, animation (GIF), or generic document attachment without caption."""
        file_bytes = await self.download_file_bytes(attachment.url)
        if file_bytes:
            file_data = io.BytesIO(file_bytes)
            file_data.name = attachment.filename
        else:
            file_data = attachment.url

        if self._is_animation(attachment):
            msg = await self.bot.send_animation(
                chat_id=chat_id,
                animation=file_data,
                filename=attachment.filename
            )
        elif self._is_image(attachment):
            msg = await self.bot.send_photo(
                chat_id=chat_id,
                photo=file_data,
                filename=attachment.filename
            )
        elif self._is_video(attachment):
            msg = await self.bot.send_video(
                chat_id=chat_id,
                video=file_data,
                filename=attachment.filename
            )
        else:
            msg = await self.bot.send_document(
                chat_id=chat_id,
                document=file_data,
                filename=attachment.filename
            )
        return msg.message_id

    async def send_animation_url(
        self,
        chat_id: Union[str, int],
        url: str
    ) -> int:
        """Helper to send an animation from a direct URL (e.g. Tenor/Giphy/Discord GIF) without caption."""
        file_bytes = await self.download_file_bytes(url)
        ext = ".mp4" if ".mp4" in url.lower() else ".gif"
        if file_bytes:
            file_data = io.BytesIO(file_bytes)
            file_data.name = f"animation{ext}"
        else:
            file_data = url

        filename = f"animation{ext}" if file_bytes else None
        msg = await self.bot.send_animation(
            chat_id=chat_id,
            animation=file_data,
            filename=filename
        )
        return msg.message_id

    async def send_channel_post(
        self,
        chat_id: Union[str, int],
        formatted_text: str,
        attachments: list[discord.Attachment],
        disable_web_page_preview: bool = False,
        animation_url: Optional[str] = None
    ) -> SendPostResult:
        """
        Sends a post to the target Telegram chat/channel.
        Media is sent cleanly first without captions; announcement text is posted immediately below it.
        """
        bot = self.bot
        sent_msg_ids: list[int] = []
        has_media = False
        text_msg_id: Optional[int] = None

        try:
            # 1. Send media if present (single photo, video, gif, or media album)
            if animation_url and not attachments:
                try:
                    msg_id = await self.send_animation_url(chat_id=chat_id, url=animation_url)
                    sent_msg_ids.append(msg_id)
                    has_media = True
                except Exception as e:
                    logger.warning(f"Could not send animation from {animation_url}: {e}")
            elif len(attachments) == 1:
                has_media = True
                msg_id = await self._send_single_attachment(chat_id=chat_id, attachment=attachments[0])
                sent_msg_ids.append(msg_id)
            elif len(attachments) > 1:
                has_media = True
                for chunk_start in range(0, len(attachments), 10):
                    chunk = attachments[chunk_start:chunk_start + 10]
                    media_group = []
                    for att in chunk:
                        file_bytes = await self.download_file_bytes(att.url)
                        if file_bytes:
                            file_data = io.BytesIO(file_bytes)
                            file_data.name = att.filename
                        else:
                            file_data = att.url

                        if self._is_image(att):
                            media_group.append(InputMediaPhoto(media=file_data))
                        elif self._is_video(att):
                            media_group.append(InputMediaVideo(media=file_data))
                        else:
                            media_group.append(InputMediaDocument(media=file_data))

                    messages = await bot.send_media_group(chat_id=chat_id, media=media_group)
                    sent_msg_ids.extend([m.message_id for m in messages])

            # 2. Send announcement text directly following media (or as standalone text post)
            if formatted_text or not has_media:
                text_to_send = formatted_text or "(Empty message)"
                text_msg = await bot.send_message(
                    chat_id=chat_id,
                    text=text_to_send,
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=disable_web_page_preview
                )
                sent_msg_ids.append(text_msg.message_id)
                text_msg_id = text_msg.message_id

        except BadRequest as e:
            logger.warning(f"Telegram BadRequest during send ({e}). Retrying with plain-text fallback...")
            try:
                plain = re_strip_tags(formatted_text) if formatted_text else "(Empty message)"
                fallback_msg = await bot.send_message(chat_id=chat_id, text=plain)
                sent_msg_ids.append(fallback_msg.message_id)
                text_msg_id = fallback_msg.message_id
            except Exception as fallback_err:
                logger.error(f"Fallback plain-text dispatch failed: {fallback_err}")
                raise
        except TelegramError as e:
            logger.error(f"Telegram error sending announcement: {e}")
            raise

        return SendPostResult(sent_msg_ids, has_media, text_msg_id)

    async def edit_channel_post(
        self,
        chat_id: Union[str, int],
        message_ids: list[int],
        formatted_text: str,
        has_media: bool,
        text_message_id: Optional[int] = None,
        followup_message_id: Optional[int] = None
    ) -> EditPostResult:
        """
        Edits the announcement text of an existing Telegram post.
        Since media never carries captions, this directly edits the text message.
        """
        bot = self.bot
        if not message_ids:
            return EditPostResult(False, [], None)

        updated_msg_ids = list(message_ids)

        # Determine target text message ID
        target_text_id = text_message_id or followup_message_id
        if target_text_id is not None and target_text_id not in updated_msg_ids:
            target_text_id = None

        if target_text_id is None:
            if not has_media:
                target_text_id = updated_msg_ids[0]
            else:
                # If post has media, the text message is the last ID (if distinct from media)
                if len(updated_msg_ids) > 1:
                    target_text_id = updated_msg_ids[-1]

        # Case A: formatted_text is non-empty
        if formatted_text:
            if target_text_id is not None:
                # Edit existing text message
                try:
                    await bot.edit_message_text(
                        chat_id=chat_id,
                        message_id=target_text_id,
                        text=formatted_text,
                        parse_mode=ParseMode.HTML,
                        disable_web_page_preview=False
                    )
                    logger.info(f"Successfully edited Telegram text message {target_text_id} in {chat_id}")
                    return EditPostResult(True, updated_msg_ids, target_text_id)
                except BadRequest as e:
                    err_msg = str(e).lower()
                    if "message is not modified" in err_msg:
                        return EditPostResult(True, updated_msg_ids, target_text_id)
                    if "can't parse entities" in err_msg or "entity" in err_msg:
                        plain = re_strip_tags(formatted_text)
                        await bot.edit_message_text(chat_id=chat_id, message_id=target_text_id, text=plain)
                        return EditPostResult(True, updated_msg_ids, target_text_id)
                    logger.error(f"Failed to edit text message {target_text_id}: {e}")
                    return EditPostResult(False, updated_msg_ids, target_text_id)
            else:
                # Was previously media-only with no text, now text was added in edit
                try:
                    new_msg = await bot.send_message(
                        chat_id=chat_id,
                        text=formatted_text,
                        parse_mode=ParseMode.HTML
                    )
                    target_text_id = new_msg.message_id
                    updated_msg_ids.append(target_text_id)
                    logger.info(f"Appended new text message {target_text_id} to media post")
                    return EditPostResult(True, updated_msg_ids, target_text_id)
                except BadRequest as e:
                    plain = re_strip_tags(formatted_text)
                    new_msg = await bot.send_message(chat_id=chat_id, text=plain)
                    target_text_id = new_msg.message_id
                    updated_msg_ids.append(target_text_id)
                    return EditPostResult(True, updated_msg_ids, target_text_id)

        # Case B: formatted_text is empty
        else:
            if target_text_id is not None:
                if has_media:
                    # Remove the text message leaving only the media
                    try:
                        await bot.delete_message(chat_id=chat_id, message_id=target_text_id)
                        updated_msg_ids.remove(target_text_id)
                        target_text_id = None
                    except Exception as e:
                        logger.warning(f"Could not delete empty text message {target_text_id}: {e}")
                else:
                    try:
                        await bot.edit_message_text(chat_id=chat_id, message_id=target_text_id, text="(Empty message)")
                    except Exception:
                        pass
            return EditPostResult(True, updated_msg_ids, target_text_id)

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

telegram_bot = TelegramClient()
