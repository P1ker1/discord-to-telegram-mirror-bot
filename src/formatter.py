from datetime import datetime, timezone
import html
import re
from typing import Optional
from zoneinfo import ZoneInfo
import discord

from src.core.config import config


# ==============================================================================
# 1. HTML Sanitization & Tag Balancing
# ==============================================================================

def escape_html(text: str) -> str:
    """Escapes HTML special characters: &, <, >."""
    return html.escape(text, quote=False)


def _strip_tags(text: str, *tags: str) -> str:
    """Helper to remove specific HTML tags to avoid invalid entity nesting."""
    cleaned = text
    for tag in tags:
        cleaned = cleaned.replace(f"<{tag}>", "").replace(f"</{tag}>", "")
    return cleaned


def _close_unclosed_tags(text: str) -> str:
    """
    Safely closes any unclosed HTML tags resulting from text truncation,
    preventing Telegram API 'Can't parse entities: unclosed start tag' errors.
    """
    # If sliced mid-tag (e.g. '<a hr' or '<b'), strip the incomplete tag fragment
    last_open = text.rfind("<")
    last_close = text.rfind(">")
    if last_open > last_close:
        text = text[:last_open]

    # Find all opening and closing tags supported by Telegram HTML
    tag_pattern = re.compile(r"<\s*(/)?\s*([a-zA-Z0-9-]+)(?:\s+[^>]*)?>")
    stack = []
    for m in tag_pattern.finditer(text):
        is_closing, tag_name = m.group(1), m.group(2).lower()
        if is_closing:
            if stack and stack[-1] == tag_name:
                stack.pop()
        else:
            stack.append(tag_name)

    # Close remaining open tags in reverse order
    closing_tags = "".join(f"</{t}>" for t in reversed(stack))
    return text + closing_tags


# ==============================================================================
# 2. Discord Mentions, Emojis & Timestamps
# ==============================================================================

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

    # 1. Custom emojis: <:pepe:123456> or <a:pepe:123456> -> :pepe:
    text = re.sub(r"<a?:([a-zA-Z0-9_]+):\d+>", r":\1:", text)

    # 2. Dynamic timestamps: <t:1726050000:R> or <t:1726050000>
    text = re.sub(
        r"<t:(\d+)(?::([a-zA-Z]))?>",
        lambda m: format_timestamp(m, tz=tz),
        text
    )

    # 3. User, role, and channel mentions lookup tables
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


# ==============================================================================
# 3. Markdown Parser (Discord Markdown -> Telegram HTML)
# ==============================================================================

def convert_discord_headers(text: str) -> str:
    """
    Converts Discord markdown headers (# Header, ## Header, ### Header, -# Subtext)
    into Telegram-compliant HTML tags. Strips inner tags to prevent invalid nested
    <b> or <i> tags which cause Telegram API errors.
    """
    lines = text.split("\n")
    converted_lines = []
    for line in lines:
        # ### Header 3 -> <b><i>Header 3</i></b>
        m3 = re.match(r"^###\s+(.+)$", line)
        if m3:
            content = _strip_tags(m3.group(1).strip(), "b", "i")
            converted_lines.append(f"<b><i>{content}</i></b>")
            continue

        # ## Header 2 -> <b>Header 2</b>
        m2 = re.match(r"^##\s+(.+)$", line)
        if m2:
            content = _strip_tags(m2.group(1).strip(), "b")
            converted_lines.append(f"<b>{content}</b>")
            continue

        # # Header 1 -> <b>Header 1</b>
        m1 = re.match(r"^#\s+(.+)$", line)
        if m1:
            content = _strip_tags(m1.group(1).strip(), "b")
            converted_lines.append(f"<b>{content}</b>")
            continue

        # -# Subtext -> <i>Subtext</i>
        m_sub = re.match(r"^-\#\s+(.+)$", line)
        if m_sub:
            content = _strip_tags(m_sub.group(1).strip(), "i")
            converted_lines.append(f"<i>{content}</i>")
            continue

        converted_lines.append(line)

    return "\n".join(converted_lines)


def discord_markdown_to_telegram_html(text: str) -> str:
    """
    Converts Discord markdown formatting into Telegram-supported HTML tags.
    Handles:
    - Code blocks (```lang ... ```)
    - Inline code (`...`)
    - Bold (**...**)
    - Underline (__...__)
    - Strikethrough (~~...~~)
    - Italic (*...* or _..._)
    - Spoilers (||...||)
    - Block quotes (> or >>>)
    - Hyperlinks ([text](url))
    - Discord headers (#, ##, ###, -#)
    """
    if not text:
        return ""

    # Temporary placeholder storage for code blocks so their contents aren't parsed
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

    # 1. Extract multiline code blocks (```lang\ncode``` or ```code```)
    text = re.sub(r"```([a-zA-Z0-9_-]*)\n?([\s\S]*?)```", save_code_block, text)

    # 2. Extract inline code (`code`)
    text = re.sub(r"`([^`]+)`", save_inline_code, text)

    # 3. Escape HTML special characters for the remaining text
    text = escape_html(text)

    # 4. Spoilers: ||text|| -> <tg-spoiler>text</tg-spoiler>
    text = re.sub(r"\|\|([^\|\n]+?)\|\|", r"<tg-spoiler>\1</tg-spoiler>", text)

    # 5. Bold: **text** -> <b>text</b>
    text = re.sub(r"\*\*([^\*\n]+?)\*\*", r"<b>\1</b>", text)

    # 6. Underline: __text__ -> <u>text</u> (prevent matching across newlines)
    text = re.sub(r"__([^_\n]+?)__", r"<u>\1</u>", text)

    # 7. Strikethrough: ~~text~~ -> <s>text</s>
    text = re.sub(r"~~([^~\n]+?)~~", r"<s>\1</s>", text)

    # 8. Italic: *text* or _text_ -> <i>text</i>
    text = re.sub(r"(?<!\w)\*([^\*\n]+?)\*(?!\w)", r"<i>\1</i>", text)
    text = re.sub(r"(?<!\w)_([^_\n]+?)_(?!\w)", r"<i>\1</i>", text)

    # 9. Hyperlinks: [text](url) -> <a href="url">text</a>
    text = re.sub(r"\[([^\]]+)\]\((https?://[^\s\)]+)\)", r'<a href="\2">\1</a>', text)

    # 10. Discord Headers & Subtext
    text = convert_discord_headers(text)

    # 11. Multi-line blockquotes: starting with >>> or consecutive > lines
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

    # 12. Restore preserved code blocks
    for placeholder, html_snippet in code_placeholders.items():
        text = text.replace(placeholder, html_snippet)

    return text


# ==============================================================================
# 4. Announcement & Embed Pipelines
# ==============================================================================

def format_embed(embed: discord.Embed) -> str:
    """Converts a Discord embed into Telegram HTML text."""
    parts = []

    # Author
    if embed.author and embed.author.name:
        parts.append(f"<b>{escape_html(embed.author.name)}</b>")

    # Title (with optional URL hyperlink)
    if embed.title:
        if embed.url:
            parts.append(f'<b><a href="{escape_html(embed.url)}">{escape_html(embed.title)}</a></b>')
        else:
            parts.append(f"<b>{escape_html(embed.title)}</b>")

    # Description
    if embed.description:
        parts.append(discord_markdown_to_telegram_html(embed.description))

    # Fields
    if embed.fields:
        field_texts = []
        for field in embed.fields:
            name = escape_html(field.name)
            value = discord_markdown_to_telegram_html(field.value)
            field_texts.append(f"<b>{name}</b>\n{value}")
        parts.append("\n\n".join(field_texts))

    # Footer
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
    """
    Main formatting pipeline for an announcement.
    Combines header, author credit, message content, and embeds into Telegram HTML.
    """
    sections = []

    if header:
        sections.append(f"<b>{escape_html(header)}</b>")

    if show_author and author_name:
        sections.append(f"📢 <b>Announced by {escape_html(author_name)}:</b>")

    if content:
        # Resolve mentions first, then convert Discord Markdown into HTML tags
        resolved_content = resolve_mentions(
            content,
            guild=guild,
            tz=tz,
            user_map=user_map,
            role_map=role_map,
            channel_map=channel_map,
            message=message
        )
        formatted_content = discord_markdown_to_telegram_html(resolved_content)
        sections.append(formatted_content)

    if embeds:
        for embed in embeds:
            # Skip automatic URL link previews and GIF embeds generated by Discord
            # (Telegram displays its own native link preview card or animation)
            if getattr(embed, "type", None) in ("link", "article", "gifv", "image"):
                continue
            embed_text = format_embed(embed)
            if embed_text:
                sections.append(embed_text)

    result = "\n\n".join(sections).strip()

    # Enforce Telegram 4096 character limit
    if len(result) > max_length:
        suffix = "\n\n<i>[Message truncated due to Telegram size limit]</i>"
        # Reserve a small margin for closing tags
        allowed = max(0, max_length - len(suffix) - 50)
        result = _close_unclosed_tags(result[:allowed]) + suffix

    return result


# ==============================================================================
# 5. Scheduled Events Digest Templates
# ==============================================================================

def format_upcoming_events_telegram(
    events: list[discord.ScheduledEvent],
    header: Optional[str] = None,
    tz: Optional[ZoneInfo] = None
) -> str:
    """
    Formats Discord Scheduled Events into a clean Telegram HTML digest.
    Includes local event time, location, and description.
    """
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
    """
    Formats Discord Scheduled Events into Discord Markdown for posting in Discord channels.
    Uses native dynamic Discord timestamps <t:timestamp:F> and <t:timestamp:R> for live countdowns.
    """
    if not events:
        return "# 📅 Upcoming Events (Next 7 Days)\n\n*No upcoming events scheduled for the next 7 days.*"

    lines = ["# 📅 Upcoming Events (Next 7 Days)", ""]
    for ev in events:
        lines.append(f"### 🔹 {ev.name}")

        if ev.start_time:
            unix_ts = int(ev.start_time.timestamp())
            # <t:unix:F> is localized date/time, <t:unix:R> is dynamic live countdown
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
