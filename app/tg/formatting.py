from __future__ import annotations

from datetime import datetime


def shorten(text: str | None, max_len: int = 120) -> str:
    if not text:
        return ""
    text = text.replace("\n", " ").strip()
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."


def format_post_preview(post_id: int, channel_id: int, message_id: int, date: datetime, text: str | None, media_count: int) -> str:
    preview = shorten(text, 80)
    date_str = date.isoformat()
    return f"#{post_id} channel={channel_id} msg={message_id} date={date_str} media={media_count} text=\"{preview}\""
