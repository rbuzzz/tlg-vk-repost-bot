from __future__ import annotations

from app.config import get_settings
from app.tg.client import TelegramClient


settings = get_settings()


def notify_admins(text: str) -> None:
    if not settings.ADMIN_IDS:
        return
    tg_client = TelegramClient(settings.TG_BOT_TOKEN)
    for admin_id in settings.ADMIN_IDS:
        try:
            tg_client.send_message(admin_id, text)
        except Exception:
            continue


def channel_id_to_internal(channel_id: int) -> str:
    cid = str(abs(channel_id))
    if cid.startswith("100"):
        cid = cid[3:]
    return cid


def build_tg_link(payload_json: dict | None, channel_id: int, message_id: int) -> str:
    username = None
    if payload_json:
        chat = payload_json.get("channel_post", {}).get("chat", {})
        username = chat.get("username")
    if username:
        return f"https://t.me/{username}/{message_id}"
    internal = channel_id_to_internal(channel_id)
    return f"https://t.me/c/{internal}/{message_id}"
