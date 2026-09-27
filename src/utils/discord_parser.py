import re
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo
import discord

from src.core.config import config
from src.utils.text_utils import _strip_tags

def format_timestamp(match, tz: Optional[ZoneInfo] = None) -> str:
    """Converts a Discord timestamp match (<t:unix:style>) to local time string."""
    try:
        ts = int(match.group(1))
        target_tz = tz or config.tz
        dt = datetime.fromtimestamp(ts, tz=target_tz)
        return dt.strftime("%Y-%m-%d %H:%M %Z")
    except Exception:
        return match.group(0)

def resolve_mentions(
    text: str,
    guild: Optional[discord.Guild] = None,
    tz: Optional[ZoneInfo] = None,
    user_map: Optional[dict[int, str]] = None,
    role_map: Optional[dict[int, str]] = None,
    channel_map: Optional[dict[int, str]] = None,
    message: Optional[discord.Message] = None
) -> str:
    """
    Replaces Discord internal mention syntaxes (<@ID>, <#ID>, <:emoji:ID>, <t:ts:style>)
    with readable, display-friendly text using guild cache, pre-fetched maps, or message metadata.
    """
    if not text:
        return ""

    text = re.sub(r"<a?:([a-zA-Z0-9_]+):\d+>", r":\1:", text)

    text = re.sub(
        r"<t:(\d+)(?::([a-zA-Z]))?>",
        lambda m: format_timestamp(m, tz=tz),
        text
    )

    user_names = dict(user_map or {})
    role_names = dict(role_map or {})
    channel_names = dict(channel_map or {})

    if message:
        for u in getattr(message, "mentions", []):
            name = getattr(u, "display_name", None) or getattr(u, "global_name", None) or getattr(u, "name", None)
            if name:
                user_names[u.id] = name
        for r in getattr(message, "role_mentions", []):
            if hasattr(r, "name"):
                role_names[r.id] = r.name
        for c in getattr(message, "channel_mentions", []):
            if hasattr(c, "name"):
                channel_names[c.id] = c.name

    def replace_user(m):
        uid = int(m.group(1))
        if uid in user_names:
            return f"@{user_names[uid]}"
        if guild:
            member = guild.get_member(uid)
            if member:
                name = getattr(member, "display_name", None) or getattr(member, "global_name", None) or member.name
                return f"@{name}"
        return f"@user_{uid}"

    def replace_role(m):
        rid = int(m.group(1))
        if rid in role_names:
            return f"@{role_names[rid]}"
        if guild:
            role = guild.get_role(rid)
            if role:
                return f"@{role.name}"
        return f"@role_{rid}"

    def replace_channel(m):
        cid = int(m.group(1))
        if cid in channel_names:
            return f"#{channel_names[cid]}"
        if guild:
            channel = guild.get_channel(cid)
            if channel:
                return f"#{channel.name}"
        return f"#channel_{cid}"

    text = re.sub(r"<@!?(\d+)>", replace_user, text)
    text = re.sub(r"<@&(\d+)>", replace_role, text)
    text = re.sub(r"<#(\d+)>", replace_channel, text)

    return text

def convert_discord_headers(text: str) -> str:
    """
    Converts Discord markdown headers (# Header, ## Header, ### Header, -# Subtext)
    into Telegram-compliant HTML tags. Strips inner tags to prevent invalid nested
    <b> or <i> tags which cause Telegram API errors.
    """
    lines = text.split("\n")
    converted_lines = []
    for line in lines:
        m3 = re.match(r"^###\s+(.+)$", line)
        if m3:
            content = _strip_tags(m3.group(1).strip(), "b", "i")
            converted_lines.append(f"<b><i>{content}</i></b>")
            continue

        m2 = re.match(r"^##\s+(.+)$", line)
        if m2:
            content = _strip_tags(m2.group(1).strip(), "b")
            converted_lines.append(f"<b>{content}</b>")
            continue

        m1 = re.match(r"^#\s+(.+)$", line)
        if m1:
            content = _strip_tags(m1.group(1).strip(), "b")
            converted_lines.append(f"<b>{content}</b>")
            continue

        m_sub = re.match(r"^-\#\s+(.+)$", line)
        if m_sub:
            content = _strip_tags(m_sub.group(1).strip(), "i")
            converted_lines.append(f"<i>{content}</i>")
            continue

        converted_lines.append(line)

    return "\n".join(converted_lines)
