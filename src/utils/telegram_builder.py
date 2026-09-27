import re
from typing import Optional
from zoneinfo import ZoneInfo
import discord

from src.core.config import config
from src.utils.text_utils import escape_html, _close_unclosed_tags
from src.utils.discord_parser import convert_discord_headers, resolve_mentions

def discord_markdown_to_telegram_html(text: str) -> str:
    """
    Converts Discord markdown formatting into Telegram-supported HTML tags.
    """
    if not text:
        return ""

    code_placeholders: dict[str, str] = {}

    def save_code_block(match):
        lang = match.group(1).strip()
        code_content = match.group(2)
        placeholder = f"PLACEHOLDERCODEBLOCK{len(code_placeholders)}X"
        escaped_code = escape_html(code_content)
        if lang:
            code_placeholders[placeholder] = f'<pre><code class="language-{escape_html(lang)}">{escaped_code}</code></pre>'
        else:
            code_placeholders[placeholder] = f"<pre><code>{escaped_code}</code></pre>"
        return placeholder

    def save_inline_code(match):
        code_content = match.group(1)
        placeholder = f"PLACEHOLDERINLINECODE{len(code_placeholders)}X"
        escaped_code = escape_html(code_content)
        code_placeholders[placeholder] = f"<code>{escaped_code}</code>"
        return placeholder

    text = re.sub(r"```([a-zA-Z0-9_-]*)\n?([\s\S]*?)```", save_code_block, text)
    text = re.sub(r"`([^`]+)`", save_inline_code, text)
    text = escape_html(text)
    text = re.sub(r"\|\|([^\|\n]+?)\|\|", r"<tg-spoiler>\1</tg-spoiler>", text)
    text = re.sub(r"\*\*([^\*\n]+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"__([^_\n]+?)__", r"<u>\1</u>", text)
    text = re.sub(r"~~([^~\n]+?)~~", r"<s>\1</s>", text)
    text = re.sub(r"(?<!\w)\*([^\*\n]+?)\*(?!\w)", r"<i>\1</i>", text)
    text = re.sub(r"(?<!\w)_([^_\n]+?)_(?!\w)", r"<i>\1</i>", text)
    text = re.sub(r"\[([^\]]+)\]\((https?://[^\s\)]+)\)", r'<a href="\2">\1</a>', text)

    text = convert_discord_headers(text)

    lines = text.split("\n")
    in_quote = False
    is_multi_quote = False
    quote_lines = []
    new_lines = []
    for line in lines:
        if is_multi_quote:
            quote_lines.append(line)
            continue

        if line.startswith("&gt;&gt;&gt; "):
            is_multi_quote = True
            quote_lines.append(line[len("&gt;&gt;&gt; "):])
        elif line.startswith("&gt;&gt;&gt;"):
            is_multi_quote = True
            quote_lines.append(line[len("&gt;&gt;&gt;"):])
        elif line.startswith("&gt; "):
            in_quote = True
            quote_lines.append(line[5:])
        elif line.startswith("&gt;"):
            in_quote = True
            quote_lines.append(line[4:])
        else:
            if in_quote:
                new_lines.append(f"<blockquote>{chr(10).join(quote_lines)}</blockquote>")
                quote_lines = []
                in_quote = False
            new_lines.append(line)

    if in_quote or is_multi_quote:
        new_lines.append(f"<blockquote>{chr(10).join(quote_lines)}</blockquote>")
    text = "\n".join(new_lines)

    for placeholder, html_snippet in code_placeholders.items():
        text = text.replace(placeholder, html_snippet)

    return text

def format_embed(embed: discord.Embed) -> str:
    parts = []
    if embed.author and embed.author.name:
        parts.append(f"<b>{escape_html(embed.author.name)}</b>")
    if embed.title:
        if embed.url:
            parts.append(f'<b><a href="{escape_html(embed.url)}">{escape_html(embed.title)}</a></b>')
        else:
            parts.append(f"<b>{escape_html(embed.title)}</b>")
    if embed.description:
        parts.append(discord_markdown_to_telegram_html(embed.description))
    if embed.fields:
        field_texts = []
        for field in embed.fields:
            name = escape_html(field.name)
            value = discord_markdown_to_telegram_html(field.value)
            field_texts.append(f"<b>{name}</b>\n{value}")
        parts.append("\n\n".join(field_texts))
    if embed.footer and embed.footer.text:
        parts.append(f"<i>{escape_html(embed.footer.text)}</i>")
    return "\n\n".join(parts)

def format_announcement(
    content: str,
    embeds: Optional[list[discord.Embed]] = None,
    guild: Optional[discord.Guild] = None,
    author_name: Optional[str] = None,
    show_author: bool = False,
    header: Optional[str] = None,
    max_length: int = 4096,
    tz: Optional[ZoneInfo] = None,
    message: Optional[discord.Message] = None,
    user_map: Optional[dict[int, str]] = None,
    role_map: Optional[dict[int, str]] = None,
    channel_map: Optional[dict[int, str]] = None
) -> str:
    sections = []
    if header:
        sections.append(f"<b>{escape_html(header)}</b>")
    if show_author and author_name:
        sections.append(f"📢 <b>Announced by {escape_html(author_name)}:</b>")
    if content:
        resolved_content = resolve_mentions(
            content, guild=guild, tz=tz, user_map=user_map, role_map=role_map, channel_map=channel_map, message=message
        )
        formatted_content = discord_markdown_to_telegram_html(resolved_content)
        sections.append(formatted_content)
    if embeds:
        for embed in embeds:
            if getattr(embed, "type", None) in ("link", "article", "gifv", "image"):
                continue
            embed_text = format_embed(embed)
            if embed_text:
                sections.append(embed_text)
    result = "\n\n".join(sections).strip()
    if len(result) > max_length:
        suffix = "\n\n<i>[Message truncated due to Telegram size limit]</i>"
        allowed = max(0, max_length - len(suffix) - 50)
        result = _close_unclosed_tags(result[:allowed]) + suffix
    return result

def format_upcoming_events_telegram(
    events: list[discord.ScheduledEvent],
    header: Optional[str] = None,
    tz: Optional[ZoneInfo] = None
) -> str:
    target_tz = tz or config.tz
    sections = []
    if header:
        sections.append(f"<b>{escape_html(header)}</b>")
    if not events:
        sections.append("<i>No upcoming events scheduled for the next 7 days. Stay tuned!</i>")
        return "\n\n".join(sections)
    event_blocks = []
    for ev in events:
        title = escape_html(ev.name)
        title_line = f"🔹 <b>{title}</b>"
        if ev.start_time:
            local_time = ev.start_time.astimezone(target_tz)
            time_str = local_time.strftime("%A, %b %d at %H:%M %Z")
            lines = [title_line, f"⏰ <i>{time_str}</i>"]
        else:
            lines = [title_line, "⏰ <i>TBD</i>"]
        location = getattr(ev, "location", None)
        channel = getattr(ev, "channel", None)
        if location:
            lines.append(f"📍 {escape_html(location)}")
        elif channel:
            lines.append(f"📍 #{escape_html(channel.name)}")
        if getattr(ev, "description", None):
            desc = ev.description.strip()
            if len(desc) > 200:
                desc = desc[:197] + "..."
            lines.append(discord_markdown_to_telegram_html(desc))
        event_blocks.append("\n".join(lines))
    sections.append("\n\n".join(event_blocks))
    return "\n\n".join(sections)

def format_upcoming_events_discord(events: list[discord.ScheduledEvent]) -> str:
    if not events:
        return "# 📅 Upcoming Events (Next 7 Days)\n\n*No upcoming events scheduled for the next 7 days.*"
    lines = ["# 📅 Upcoming Events (Next 7 Days)", ""]
    for ev in events:
        lines.append(f"### 🔹 {ev.name}")
        if ev.start_time:
            unix_ts = int(ev.start_time.timestamp())
            lines.append(f"⏰ <t:{unix_ts}:F> (<t:{unix_ts}:R>)")
        else:
            lines.append("⏰ *TBD*")
        location = getattr(ev, "location", None)
        channel = getattr(ev, "channel", None)
        if location:
            lines.append(f"📍 {location}")
        elif channel:
            lines.append(f"📍 #{channel.name}")
        if getattr(ev, "description", None):
            lines.append(ev.description.strip())
        lines.append("")
    return "\n".join(lines).strip()
