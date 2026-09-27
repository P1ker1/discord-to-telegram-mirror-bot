import html
import re

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
    last_open = text.rfind("<")
    last_close = text.rfind(">")
    if last_open > last_close:
        text = text[:last_open]

    tag_pattern = re.compile(r"<\s*(/)?\s*([a-zA-Z0-9-]+)(?:\s+[^>]*)?>")
    stack: list[str] = []
    for m in tag_pattern.finditer(text):
        is_closing, tag_name = m.group(1), m.group(2).lower()
        if is_closing:
            if stack and stack[-1] == tag_name:
                stack.pop()
        else:
            stack.append(tag_name)

    closing_tags = "".join(f"</{t}>" for t in reversed(stack))
    return text + closing_tags
