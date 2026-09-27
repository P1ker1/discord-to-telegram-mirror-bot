# Discord Announcement Test Messages & Edge Case Guide

This document contains a curated collection of sample Discord messages designed to test and demonstrate every formatting feature and edge case supported by the bridge bot.

You can copy and paste the **Discord Markdown (Input)** directly into your monitored `#announcements` channel to see how the bot mirrors them to Telegram.

---

## 1. The "Kitchen Sink" Announcement (Full Feature Showcase)

This announcement tests almost every supported syntax simultaneously, including edge cases with raw HTML characters, Discord headers, dynamic timestamps, mentions, emojis, spoilers, code blocks, and blockquotes.

### Discord Markdown (Copy & Paste this into Discord):

````markdown
# 🎮 Weekly Club Night & Dev Workshop!
## Event Overview & Registration
### Hosted by the Club Organizers

Hey @everyone! Join us for a special session with <@&1122334455> and our guest speaker <@123456789>!
Check previous highlights in <#987654321> <:party_hype:1001> <a:blob_dance:1002>.

**Important Note**: The room keycode is ||4829|| (don't share outside the club!).
We will provide snacks & drinks (budget: 50€ < 100€ & lots of pizza).

Here is the setup command to run beforehand:
`git clone https://github.com/your-org/demo.git && cd demo`

```python
def check_admission(member_score: int, threshold: int = 10) -> bool:
    # Notice: <, >, and & characters inside code blocks are safely escaped!
    return member_score >= threshold and (member_score & 1) == 0
```

> **Organizer Notice:**
> Please arrive __15 minutes before the start__!
> ~~Old Room: 101~~ ➔ **New Room: 204**

📅 **When**: <t:1727434800:F>
🔗 **Register here**: [Sign-up Form](https://example.com/events)

-# Organized with love by Community Club • No prerequisites needed!
````

### What this Tests & Demonstrates:

| Feature / Edge Case | Discord Syntax | Bridge Handling |
| :--- | :--- | :--- |
| **Discord Headers** | `# H1`, `## H2`, `### H3` | Converted to `<b>` and `<b><i>` HTML tags without markdown leaking. |
| **Discord Subtext** | `-# Subtext` | Converted to italic `<i>` styling. |
| **Raw HTML Characters** | `&`, `<`, `>` in text | Escaped to `&amp;`, `&lt;`, `&gt;` so Telegram's HTML parser doesn't crash. |
| **Dynamic Timestamps** | `<t:1727434800:F>` | Resolved into localized string (e.g. `2024-09-27 14:00 EEST`) in configured timezone. |
| **Mentions** | `<@123>`, `<@&456>`, `<#789>` | Resolved to display names (`@Alice`, `@Developer`, `#general`) via server cache. |
| **Custom Emojis** | `<:name:id>`, `<a:name:id>` | Stripped of internal IDs and converted to `:name:` text. |
| **Telegram Spoiler** | `\|\|4829\|\|` | Converted to native `<tg-spoiler>4829</tg-spoiler>` tap-to-reveal element. |
| **Code Blocks** | <code>```python ... ```</code> | Enclosed in `<pre><code>...</code></pre>` with inner characters escaped without parsing inner markdown. |
| **Inline Code** | <code>`git clone ...`</code> | Wrapped in `<code>...</code>` with raw text preserved. |
| **Blockquotes** | `> text` | Grouped into native `<blockquote>...</blockquote>` elements. |
| **Markdown Links** | `[Text](URL)` | Converted to clean Telegram HTML links `<a href="URL">Text</a>`. |
| **Standard Formatting** | `**bold**`, `__underline__`, `~~strike~~` | Converted to `<b>`, `<u>`, and `<s>` tags. |

### Expected Telegram Output (HTML):

```html
<b>🎮 Weekly Club Night &amp; Dev Workshop!</b>
<b>Event Overview &amp; Registration</b>
<b><i>Hosted by the Club Organizers</i></b>

Hey @everyone! Join us for a special session with @role_1122334455 and our guest speaker @user_123456789!
Check previous highlights in #channel_987654321 :party_hype: :blob_dance:.

<b>Important Note</b>: The room keycode is <tg-spoiler>4829</tg-spoiler> (don't share outside the club!).
We will provide snacks &amp; drinks (budget: 50€ &lt; 100€ &amp; lots of pizza).

Here is the setup command to run beforehand:
<code>git clone https://github.com/your-org/demo.git &amp;&amp; cd demo</code>

<pre><code>def check_admission(member_score: int, threshold: int = 10) -&gt; bool:
    # Notice: &lt;, &gt;, and &amp; characters inside code blocks are safely escaped!
    return member_score &gt;= threshold and (member_score &amp; 1) == 0</code></pre>

<blockquote><b>Organizer Notice:</b>
Please arrive <u>15 minutes before the start</u>!
<s>Old Room: 101</s> ➔ <b>New Room: 204</b></blockquote>

📅 <b>When</b>: 2024-09-27 14:00 EEST
🔗 <b>Register here</b>: <a href="https://example.com/events">Sign-up Form</a>

<i>Organized with love by Community Club • No prerequisites needed!</i>
```

---

## 2. Header Nesting & Formatting Sanity Test

Discord users frequently combine headers with other markdown (e.g. `## **Bold Header**` or `### *Italic Header*`). In raw HTML, nesting `<b><b>Header</b></b>` is rejected by Telegram’s strict parser. This test confirms tag de-duplication.

### Discord Markdown (Copy & Paste this into Discord):

```markdown
# **Notice: Schedule Update**
## __**Mandatory Meeting for Club Board**__
### *Discussion Topics & Voting Items*

The voting period is now open:
1. Approve budget for Q4: **Yes** / **No**
2. Location for next hackathon: ||Secret Sauna Spot||

-# *Please cast your vote before midnight.*
```

### What this Tests & Demonstrates:
- **`_strip_tags` in `convert_discord_headers`**: Strips inner `<b>` or `<i>` tags from header lines, preventing Telegram `BadRequest: can't parse entities` caused by invalid nested tags.
- **Ordered Lists & Inline Spoilers**: Clean combination of lists, bold choices, and spoilers.

---

## 3. Multi-line Blockquote Test (`>>>`)

Discord supports `>>>` to turn the entire remainder of a message into a single blockquote.

### Discord Markdown (Copy & Paste this into Discord):

```markdown
📢 Message from the Club President:

>>> To all members of Community Club:
Thank you for participating in this weekend's tournament!
We had over **40 participants** and raised __300€__ for new hardware.

Special congratulations to the top 3:
1. 🥇 <@123456789>
2. 🥈 <@234567890>
3. 🥉 <@345678901>

See you all next week!
```

### What this Tests & Demonstrates:
- **`>>> ` prefix**: Formatter automatically wraps the full remainder into Telegram's native `<blockquote>...</blockquote>` styling.
- Preserves all inner mentions, rankings, bold, and underline tags inside the quote.

---

## 4. Complex Media & Attachment Scenarios

Test how the bot handles attachments and captions.

### Scenario A: Single Animated GIF
* **How to test**: In `#announcements`, upload an animated `.gif` file with any caption text.
* **Expected Result**: The bot routes this to `send_animation` instead of `send_photo`. In Telegram, the GIF plays in an infinite loop with native autoplay rather than freezing on frame 1.

### Scenario B: Multi-Image Visual Album
* **How to test**: In `#announcements`, upload 2 to 4 photos (`.png` or `.jpg`) in a single post with text.
* **Expected Result**: 
  - The photos are grouped into a Telegram album.
  - If text is short (≤ 1,000 chars), it is attached as the caption.
  - If text is long (> 1,000 chars), the photos are sent first, and the text message is delivered directly beneath it without truncation.

### Scenario C: Generic File Attachment (PDF / ZIP)
* **How to test**: In `#announcements`, upload a `.pdf` document or `.zip` archive.
* **Expected Result**: Routed to `send_document`, rendering a downloadable file card in Telegram with filename and file size.
