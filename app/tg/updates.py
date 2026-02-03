from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple


@dataclass
class ParsedTGPost:
    channel_id: int
    message_id: int
    date: datetime
    text: str | None
    media_group_id: str | None
    payload_json: Dict[str, Any]
    media_items: List[Dict[str, Any]]


def _best_photo(photo_sizes: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not photo_sizes:
        return {}
    return max(photo_sizes, key=lambda p: p.get("file_size", 0))


def parse_channel_post(update: Dict[str, Any]) -> ParsedTGPost:
    message = update.get("channel_post") or {}
    channel_id = int(message["chat"]["id"])
    message_id = int(message["message_id"])
    date = datetime.fromtimestamp(message["date"], tz=timezone.utc)
    text = message.get("text") or message.get("caption")
    media_group_id = message.get("media_group_id")

    media_items: List[Dict[str, Any]] = []
    order = 0

    if "photo" in message:
        photo = _best_photo(message.get("photo") or [])
        if photo:
            media_items.append(
                {
                    "type": "photo",
                    "file_id": photo["file_id"],
                    "file_unique_id": photo.get("file_unique_id"),
                    "size": photo.get("file_size"),
                    "order_index": order,
                }
            )
            order += 1

    if "video" in message:
        video = message["video"]
        media_items.append(
            {
                "type": "video",
                "file_id": video["file_id"],
                "file_unique_id": video.get("file_unique_id"),
                "mime_type": video.get("mime_type"),
                "file_name": video.get("file_name"),
                "size": video.get("file_size"),
                "order_index": order,
            }
        )
        order += 1

    if "document" in message:
        document = message["document"]
        media_items.append(
            {
                "type": "document",
                "file_id": document["file_id"],
                "file_unique_id": document.get("file_unique_id"),
                "mime_type": document.get("mime_type"),
                "file_name": document.get("file_name"),
                "size": document.get("file_size"),
                "order_index": order,
            }
        )
        order += 1

    return ParsedTGPost(
        channel_id=channel_id,
        message_id=message_id,
        date=date,
        text=text,
        media_group_id=media_group_id,
        payload_json=update,
        media_items=media_items,
    )
