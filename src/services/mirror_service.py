import asyncio
import logging
import re
from typing import Optional

import aiohttp
import discord
from discord import RawMessageUpdateEvent, RawMessageDeleteEvent, RawBulkMessageDeleteEvent

from src.core.config import config
from src.core.database import Database
from src.utils.telegram_builder import format_announcement

logger = logging.getLogger("MirrorService")

class MirrorService:
    def __init__(self, discord_client: discord.Client, telegram_client, db: Database):
        self.discord_client = discord_client
        self.telegram_client = telegram_client
        self.db = db

    async def _resolve_users_for_message(self, message: discord.Message) -> dict[int, str]:
        user_map: dict[int, str] = {}
        for m in getattr(message, "mentions", []):
            name = getattr(m, "display_name", None) or getattr(m, "global_name", None) or getattr(m, "name", None)
            if name:
                user_map[m.id] = name

        if message.content:
            for match in re.finditer(r"<@!?(\d+)>", message.content):
                uid = int(match.group(1))
                if uid in user_map:
                    continue
                if message.guild:
                    member = message.guild.get_member(uid)
                    if member:
                        name = getattr(member, "display_name", None) or getattr(member, "global_name", None) or getattr(member, "name", None)
                        if name:
                            user_map[uid] = name
                            continue
                try:
                    u = await self.discord_client.fetch_user(uid)
                    name = getattr(u, "display_name", None) or getattr(u, "global_name", None) or getattr(u, "name", None)
                    if name:
                        user_map[uid] = name
                except Exception:
                    pass
        return user_map

    def _extract_animation(self, message: discord.Message) -> tuple[Optional[str], str]:
        content = message.content or ""
        if message.attachments:
            return None, content

        anim_url = None
        for emb in getattr(message, "embeds", []):
            if getattr(emb, "type", None) == "gifv":
                if emb.video and emb.video.url:
                    anim_url = emb.video.url
                    break
                elif emb.thumbnail and emb.thumbnail.url:
                    anim_url = emb.thumbnail.url
                    break

            for cand in [
                getattr(emb.video, "url", None) if emb.video else None,
                getattr(emb.image, "url", None) if emb.image else None,
                getattr(emb.thumbnail, "url", None) if emb.thumbnail else None,
                getattr(emb, "url", None),
            ]:
                if cand and (".gif" in cand.lower() or cand.lower().endswith(".mp4")):
                    anim_url = cand
                    break
            if anim_url:
                break

        if not anim_url and content:
            m = re.search(r"(https?://\S+?\.(?:gif|mp4)(?:\?\S*)?)", content, re.IGNORECASE)
            if m:
                anim_url = m.group(1)

        if anim_url:
            cleaned = content
            base_name = anim_url.split("?")[0].split("/")[-1]
            if base_name:
                cleaned = re.sub(rf"https?://\S*{re.escape(base_name)}\S*", "", cleaned).strip()
            cleaned = re.sub(r"https?://(?:tenor\.com/view/|media\.tenor\.com/|giphy\.com/gifs/|media\.giphy\.com/)\S*", "", cleaned).strip()
            return anim_url, cleaned

        return None, content

    async def refresh_discord_url(self, url: str) -> str:
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

    async def _prepare_announcement(self, message: discord.Message) -> tuple[str, Optional[str]]:
        anim_url, cleaned_content = self._extract_animation(message)
        if not anim_url and not message.attachments and not message.embeds and message.content:
            if re.search(r"https?://\S+?\.(?:gif|mp4)|https?://(?:tenor\.com/view/|giphy\.com/gifs/)", message.content, re.IGNORECASE):
                await asyncio.sleep(0.5)
                try:
                    message = await message.channel.fetch_message(message.id)
                    anim_url, cleaned_content = self._extract_animation(message)
                except Exception:
                    pass

        if anim_url and ("discordapp.com/attachments/" in anim_url or "discordapp.net/attachments/" in anim_url) and "ex=" not in anim_url:
            anim_url = await self.refresh_discord_url(anim_url)

        user_map = await self._resolve_users_for_message(message)
        author_name = message.author.display_name if hasattr(message.author, "display_name") else str(message.author)
        header = config.announcement_header if config.enable_message_headers else None

        formatted_text = format_announcement(
            content=cleaned_content,
            embeds=message.embeds,
            guild=message.guild,
            author_name=author_name,
            show_author=config.show_author_header,
            header=header,
            tz=config.tz,
            message=message,
            user_map=user_map
        )
        return formatted_text, anim_url

    async def process_message(self, message: discord.Message):
        if message.channel.id != config.discord_channel_id:
            return
        if message.author == self.discord_client.user:
            return
        if message.author.bot and not config.mirror_bot_messages:
            return
        if not message.content and not message.embeds and not message.attachments:
            return

        logger.info(f"New announcement from {message.author} (Discord ID: {message.id})")

        try:
            formatted_text, anim_url = await self._prepare_announcement(message)

            post_res = await self.telegram_client.send_channel_post(
                chat_id=config.telegram_chat_id,
                formatted_text=formatted_text,
                attachments=message.attachments,
                animation_url=anim_url
            )
            sent_msg_ids, has_media = post_res[0], post_res[1]
            followup_msg_id = getattr(post_res, "followup_message_id", None)

            save_kwargs = {
                "discord_msg_id": message.id,
                "telegram_chat_id": config.telegram_chat_id,
                "telegram_msg_ids": sent_msg_ids,
                "has_media": has_media
            }
            if followup_msg_id is not None:
                save_kwargs["followup_message_id"] = followup_msg_id

            await self.db.save_mapping(**save_kwargs)
            logger.info(f"Mirrored message {message.id} to Telegram message(s): {sent_msg_ids}")
        except Exception as e:
            logger.error(f"Failed to mirror message {message.id}: {e}", exc_info=True)

    async def process_message_edit(self, payload: RawMessageUpdateEvent):
        if payload.channel_id != config.discord_channel_id:
            return

        mapping = await self.db.get_mapping(payload.message_id)
        if not mapping:
            return

        logger.info(f"Edit detected for Discord ID: {payload.message_id}")

        try:
            channel = self.discord_client.get_channel(payload.channel_id) or await self.discord_client.fetch_channel(payload.channel_id)
            message = await channel.fetch_message(payload.message_id)

            formatted_text, _ = await self._prepare_announcement(message)

            edit_kwargs = {
                "chat_id": mapping["telegram_chat_id"],
                "message_ids": mapping["telegram_message_ids"],
                "formatted_text": formatted_text,
                "has_media": mapping["has_media"],
            }
            if mapping.get("followup_message_id") is not None:
                edit_kwargs["followup_message_id"] = mapping["followup_message_id"]

            edit_res = await self.telegram_client.edit_channel_post(**edit_kwargs)
            if edit_res:
                updated_msg_ids = getattr(edit_res, "updated_message_ids", mapping["telegram_message_ids"])
                updated_followup_id = getattr(edit_res, "updated_followup_message_id", mapping.get("followup_message_id"))
                if updated_msg_ids != mapping["telegram_message_ids"] or updated_followup_id != mapping.get("followup_message_id"):
                    save_kwargs = {
                        "discord_msg_id": payload.message_id,
                        "telegram_chat_id": mapping["telegram_chat_id"],
                        "telegram_msg_ids": updated_msg_ids,
                        "has_media": mapping["has_media"]
                    }
                    if updated_followup_id is not None:
                        save_kwargs["followup_message_id"] = updated_followup_id

                    save_coro = self.db.save_mapping(**save_kwargs)
                    if asyncio.iscoroutine(save_coro):
                        await save_coro
                logger.info(f"Updated Telegram message for Discord ID: {payload.message_id}")

        except discord.NotFound:
            logger.debug(f"Message {payload.message_id} was deleted before edit could be processed.")
        except Exception as e:
            logger.error(f"Error handling message edit for {payload.message_id}: {e}", exc_info=True)

    async def process_message_delete(self, payload: RawMessageDeleteEvent):
        if payload.channel_id != config.discord_channel_id:
            return

        mapping = await self.db.delete_mapping(payload.message_id)
        if not mapping:
            return

        logger.info(f"Deletion detected for Discord ID: {payload.message_id}. Removing from Telegram...")
        try:
            await self.telegram_client.delete_channel_post(
                chat_id=mapping["telegram_chat_id"],
                message_ids=mapping["telegram_message_ids"]
            )
            logger.info(f"Deleted Telegram message(s) {mapping['telegram_message_ids']}")
        except Exception as e:
            logger.error(f"Error deleting Telegram message for Discord ID {payload.message_id}: {e}", exc_info=True)

    async def process_bulk_message_delete(self, payload: RawBulkMessageDeleteEvent):
        if payload.channel_id != config.discord_channel_id:
            return

        logger.info(f"Bulk deletion detected ({len(payload.message_ids)} messages)")
        deleted_mappings = await self.db.delete_mappings_bulk(list(payload.message_ids))

        for mapping in deleted_mappings:
            try:
                await self.telegram_client.delete_channel_post(
                    chat_id=mapping["telegram_chat_id"],
                    message_ids=mapping["telegram_message_ids"]
                )
            except Exception as e:
                logger.error(f"Error deleting bulk message mapping: {e}")
