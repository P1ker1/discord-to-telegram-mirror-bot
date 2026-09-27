import unittest
from src.formatter import (
    escape_html,
    discord_markdown_to_telegram_html,
    resolve_mentions,
    format_announcement,
    format_embed
)

class TestFormatter(unittest.TestCase):
    def test_escape_html(self):
        self.assertEqual(escape_html("Hello <world> & 'friends'"), "Hello &lt;world&gt; &amp; 'friends'")

    def test_basic_markdown_conversions(self):
        # Bold
        self.assertEqual(discord_markdown_to_telegram_html("**bold text**"), "<b>bold text</b>")
        # Underline
        self.assertEqual(discord_markdown_to_telegram_html("__underlined text__"), "<u>underlined text</u>")
        # Strikethrough
        self.assertEqual(discord_markdown_to_telegram_html("~~strike text~~"), "<s>strike text</s>")
        # Italic
        self.assertEqual(discord_markdown_to_telegram_html("*italic text*"), "<i>italic text</i>")
        self.assertEqual(discord_markdown_to_telegram_html("_italic text_"), "<i>italic text</i>")
        # Spoiler
        self.assertEqual(discord_markdown_to_telegram_html("||secret spoiler||"), "<tg-spoiler>secret spoiler</tg-spoiler>")
        # Link
        self.assertEqual(
            discord_markdown_to_telegram_html("[Click Here](https://example.com)"),
            '<a href="https://example.com">Click Here</a>'
        )

    def test_code_blocks(self):
        # Inline code
        result = discord_markdown_to_telegram_html("Run `git status` command")
        self.assertEqual(result, "Run <code>git status</code> command")

        # Code block should preserve content and not parse markdown inside it
        code_input = "```python\ndef foo():\n    return **not_bold**\n```"
        formatted = discord_markdown_to_telegram_html(code_input)
        self.assertIn("<pre><code>", formatted)
        self.assertIn("return **not_bold**", formatted)
        self.assertNotIn("<b>", formatted)

    def test_blockquotes(self):
        # Blockquote with space
        quote_input = "> Important announcement note\nNormal text"
        formatted = discord_markdown_to_telegram_html(quote_input)
        self.assertIn("<blockquote>Important announcement note</blockquote>", formatted)
        self.assertIn("Normal text", formatted)

        # Blockquote without space
        quote_input2 = ">Compact quote"
        formatted2 = discord_markdown_to_telegram_html(quote_input2)
        self.assertIn("<blockquote>Compact quote</blockquote>", formatted2)

    def test_resolve_mentions_fallback(self):
        text = "Hello <@123456>, check <#789012> and <@&345678>"
        resolved = resolve_mentions(text, guild=None)
        self.assertEqual(resolved, "Hello @user_123456, check #channel_789012 and @role_345678")

    def test_custom_emojis_and_timestamps(self):
        # Static custom emoji
        self.assertEqual(resolve_mentions("Great job <:pepeHappy:1234567890123>!"), "Great job :pepeHappy:!")
        # Animated custom emoji
        self.assertEqual(resolve_mentions("Dancing <a:partyBlob:9876543210>"), "Dancing :partyBlob:")
        # Discord timestamp formatted in local timezone (e.g. EEST or EET)
        formatted_ts = resolve_mentions("Event at <t:1726050000:F>")
        self.assertTrue("EEST" in formatted_ts or "EET" in formatted_ts or "UTC" in formatted_ts)
        # Discord timestamp formatted in local timezone (clean and static for Telegram)
        rel_ts = resolve_mentions("Starts <t:1726050000:R>")
        self.assertTrue("EEST" in rel_ts or "EET" in rel_ts or "UTC" in rel_ts)

    def test_headers_and_tag_sanitization(self):
        # Header 1
        self.assertEqual(discord_markdown_to_telegram_html("# Main Heading"), "<b>Main Heading</b>")
        # Header 2
        self.assertEqual(discord_markdown_to_telegram_html("## Sub Heading"), "<b>Sub Heading</b>")
        # Header 3
        self.assertEqual(discord_markdown_to_telegram_html("### Minor Heading"), "<b><i>Minor Heading</i></b>")
        # Subtext
        self.assertEqual(discord_markdown_to_telegram_html("-# Small subtext"), "<i>Small subtext</i>")

        # Crucial test: Header containing bold text must NOT produce nested <b><b> or <b>...<b>
        res_bold_header = discord_markdown_to_telegram_html("# **Bold Header**")
        self.assertEqual(res_bold_header, "<b>Bold Header</b>")
        self.assertNotIn("<b><b>", res_bold_header)

        res_partial_bold = discord_markdown_to_telegram_html("# Note: **Please Read Carefully**")
        self.assertEqual(res_partial_bold, "<b>Note: Please Read Carefully</b>")
        self.assertNotIn("<b><b>", res_partial_bold)
        self.assertEqual(res_partial_bold.count("<b>"), 1)

    def test_format_announcement_header(self):
        result = format_announcement("Hello world", header="-- Announcement --")
        self.assertIn("<b>-- Announcement --</b>", result)
        self.assertIn("Hello world", result)

    def test_upcoming_events_formatting(self):
        from unittest.mock import MagicMock
        from datetime import datetime, timezone
        from src.formatter import format_upcoming_events_telegram, format_upcoming_events_discord

        mock_event = MagicMock()
        mock_event.name = "Weekly Game Night"
        mock_event.start_time = datetime(2026, 9, 15, 18, 0, tzinfo=timezone.utc)
        mock_event.url = "https://discord.gg/events/123"
        mock_event.location = "Voice Channel 1"
        mock_event.description = "Come play games with us!"

        # Telegram formatting
        tg_res = format_upcoming_events_telegram([mock_event], header="-- Upcoming Events --")
        self.assertIn("<b>-- Upcoming Events --</b>", tg_res)
        self.assertIn("Weekly Game Night", tg_res)
        self.assertIn("Voice Channel 1", tg_res)
        self.assertIn("Come play games with us!", tg_res)

        # Discord formatting
        dc_res = format_upcoming_events_discord([mock_event])
        self.assertIn("# 📅 Upcoming Events", dc_res)
        self.assertIn("Weekly Game Night", dc_res)

        # Empty events test
        empty_tg = format_upcoming_events_telegram([])
        self.assertIn("No upcoming events scheduled", empty_tg)

    def test_format_announcement_truncation(self):
        long_content = "A" * 5000
        announcement = format_announcement(long_content, max_length=1000)
        self.assertLessEqual(len(announcement), 1000)
        self.assertIn("[Message truncated due to Telegram size limit]", announcement)

    def test_format_announcement_truncation_with_tags(self):
        # Long formatted text wrapped in tags
        long_tagged = "**" + ("Important bold content " * 100) + "**"
        announcement = format_announcement(long_tagged, max_length=500)
        self.assertLessEqual(len(announcement), 500)
        # Ensure that every opening <b> tag has a matching closing </b> tag
        self.assertEqual(announcement.count("<b>"), announcement.count("</b>"))
        self.assertEqual(announcement.count("<i>"), announcement.count("</i>"))

    def test_resolve_mentions_with_guild(self):
        from unittest.mock import MagicMock

        guild = MagicMock()
        member = MagicMock(display_name="Alice")
        role = MagicMock()
        role.name = "Moderator"
        channel = MagicMock()
        channel.name = "announcements"

        guild.get_member.side_effect = lambda uid: member if uid == 123 else None
        guild.get_role.side_effect = lambda rid: role if rid == 456 else None
        guild.get_channel.side_effect = lambda cid: channel if cid == 789 else None

        text = "Hey <@123>, please post in <#789> (ask <@&456>)"
        resolved = resolve_mentions(text, guild=guild)
        self.assertEqual(resolved, "Hey @Alice, please post in #announcements (ask @Moderator)")

    def test_format_embed(self):
        from unittest.mock import MagicMock

        embed = MagicMock()
        embed.author.name = "Announcement Bot"
        embed.title = "Important Update"
        embed.url = "https://example.com"
        embed.description = "Here is some **bold description**"

        field = MagicMock()
        field.name = "Status"
        field.value = "Active"
        embed.fields = [field]
        embed.footer.text = "Page 1 of 1"

        result = format_embed(embed)
        self.assertIn("<b>Announcement Bot</b>", result)
        self.assertIn('<a href="https://example.com">Important Update</a>', result)
        self.assertIn("<b>bold description</b>", result)
        self.assertIn("<b>Status</b>\nActive", result)
        self.assertIn("<i>Page 1 of 1</i>", result)

    def test_format_announcement_skips_link_preview_embed(self):
        from unittest.mock import MagicMock

        embed = MagicMock()
        embed.type = "link"
        embed.title = "Discord Preview Card"

        result = format_announcement("Content with link", embeds=[embed])
        self.assertNotIn("Discord Preview Card", result)


if __name__ == "__main__":
    unittest.main()

