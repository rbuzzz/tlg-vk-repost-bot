from __future__ import annotations

import time
from typing import Any, Dict

from app.config import get_settings
from app.crud import (
    add_media_items,
    count_jobs_by_status,
    create_tg_post,
    ensure_defaults,
    get_last_job_errors,
    get_last_update_id,
    get_runtime_settings,
    get_tg_post_by_ids,
    list_failed_jobs,
    list_media_items_for_post,
    list_recent_tg_posts,
    set_last_update_id,
    set_setting,
    touch_album_state,
)
from app.db import session_scope
from app.logging_setup import get_logger, setup_logging
from app.tasks.repost import finalize_album, repost_tg_post
from app.tg.album_aggregator import schedule_album_finalize
from app.tg.client import TelegramClient
from app.tg.commands import is_admin, parse_command
from app.tg.formatting import format_post_preview
from app.tg.updates import parse_channel_post


logger = get_logger(__name__)


def _defaults_from_settings(settings) -> dict:
    return {
        "autoposting_enabled": True,
        "mode": settings.MODE,
        "limit_strategy": settings.LIMIT_STRATEGY,
        "vk_group_id": settings.VK_GROUP_ID,
        "source_channel_ids": ",".join(str(x) for x in settings.SOURCE_CHANNEL_IDS),
    }


def should_autopost(runtime: dict) -> bool:
    return runtime["autoposting_enabled"] and runtime["mode"] == "auto"


def handle_channel_post(update: Dict[str, Any], settings, runtime: dict) -> None:
    parsed = parse_channel_post(update)
    if runtime["source_channel_ids"] and parsed.channel_id not in runtime["source_channel_ids"]:
        logger.info("tg_channel_ignored", extra={"channel_id": parsed.channel_id})
        return

    tg_post_id = None
    created = False

    with session_scope() as session:
        tg_post, created = create_tg_post(
            session,
            channel_id=parsed.channel_id,
            message_id=parsed.message_id,
            date=parsed.date,
            text=parsed.text,
            media_group_id=parsed.media_group_id,
            payload_json=parsed.payload_json,
        )
        tg_post_id = tg_post.id
        if created and parsed.media_items:
            add_media_items(session, tg_post.id, parsed.media_items)
        if created and parsed.media_group_id:
            touch_album_state(session, parsed.media_group_id, first_tg_post_id=tg_post.id)

    if not created:
        logger.info(
            "tg_post_duplicate",
            extra={"channel_id": parsed.channel_id, "message_id": parsed.message_id},
        )
        return

    if parsed.media_group_id:
        if should_autopost(runtime):
            schedule_album_finalize(parsed.media_group_id, settings.ALBUM_FINALIZE_DELAY_SEC)
        logger.info(
            "album_item_ingested",
            extra={"media_group_id": parsed.media_group_id, "tg_post_id": tg_post_id},
        )
        return

    if should_autopost(runtime):
        repost_tg_post.apply_async(args=[tg_post_id])
        logger.info("tg_post_enqueued", extra={"tg_post_id": tg_post_id})


def _format_status(runtime: dict, last_update_id: int, job_counts: dict, last_errors) -> str:
    lines = [
        "Status:",
        f"MODE={runtime['mode']}",
        f"AUTOPOST={'enabled' if runtime['autoposting_enabled'] else 'disabled'}",
        f"LIMIT_STRATEGY={runtime['limit_strategy']}",
        f"VK_GROUP_ID={runtime['vk_group_id']}",
        f"last_update_id={last_update_id}",
        f"jobs={job_counts}",
    ]
    if last_errors:
        lines.append("Recent errors:")
        for job in last_errors:
            lines.append(f"- job#{job.id} {job.type}: {job.last_error}")
    return "\n".join(lines)


def handle_admin_message(message: Dict[str, Any], settings, tg_client: TelegramClient) -> None:
    user = message.get("from") or {}
    user_id = user.get("id")
    if user_id is None or not is_admin(int(user_id), settings.ADMIN_IDS):
        return

    cmd = parse_command(message.get("text"))
    if cmd is None:
        return

    chat_id = message["chat"]["id"]

    with session_scope() as session:
        defaults = _defaults_from_settings(settings)
        runtime = get_runtime_settings(session, defaults)

        if cmd.name == "help":
            response = (
                "Commands:\n"
                "/help\n"
                "/status\n"
                "/enable /disable\n"
                "/last N\n"
                "/repost <channel_id> <message_id> OR /repost <message_id>\n"
                "/retry_failed N\n"
                "/set_target <vk_group_id>\n"
                "/set_source <channel_id or @channel>\n"
                "/set_mode auto|moderation"
            )
            tg_client.send_message(chat_id, response)
            return

        if cmd.name == "status":
            last_update_id = get_last_update_id(session)
            counts = count_jobs_by_status(session)
            errors = get_last_job_errors(session, limit=3)
            response = _format_status(runtime, last_update_id, counts, errors)
            tg_client.send_message(chat_id, response)
            return

        if cmd.name == "enable":
            set_setting(session, "autoposting_enabled", "true")
            tg_client.send_message(chat_id, "Autoposting enabled")
            return

        if cmd.name == "disable":
            set_setting(session, "autoposting_enabled", "false")
            tg_client.send_message(chat_id, "Autoposting disabled")
            return

        if cmd.name == "set_mode":
            if not cmd.args or cmd.args[0] not in {"auto", "moderation"}:
                tg_client.send_message(chat_id, "Usage: /set_mode auto|moderation")
                return
            set_setting(session, "mode", cmd.args[0])
            tg_client.send_message(chat_id, f"Mode set to {cmd.args[0]}")
            return

        if cmd.name == "set_target":
            if not cmd.args:
                tg_client.send_message(chat_id, "Usage: /set_target <vk_group_id>")
                return
            set_setting(session, "vk_group_id", cmd.args[0])
            tg_client.send_message(chat_id, f"Target VK group set to {cmd.args[0]}")
            return

        if cmd.name == "set_source":
            if not cmd.args:
                tg_client.send_message(chat_id, "Usage: /set_source <channel_id or @channel>")
                return
            arg = cmd.args[0]
            if arg.startswith("@"):
                try:
                    chat = tg_client.get_chat(arg)
                    channel_id = chat["id"]
                except Exception as exc:
                    tg_client.send_message(chat_id, f"Failed to resolve {arg}: {exc}")
                    return
            else:
                channel_id = int(arg)
            set_setting(session, "source_channel_ids", str(channel_id))
            tg_client.send_message(chat_id, f"Source channel set to {channel_id}")
            return

        if cmd.name == "last":
            limit = int(cmd.args[0]) if cmd.args else 5
            posts = list_recent_tg_posts(session, limit)
            if not posts:
                tg_client.send_message(chat_id, "No posts found")
                return
            lines = []
            for post in posts:
                media_items = list_media_items_for_post(session, post.id)
                lines.append(
                    format_post_preview(
                        post.id,
                        post.channel_id,
                        post.message_id,
                        post.date,
                        post.text,
                        len(media_items),
                    )
                )
            tg_client.send_message(chat_id, "\n".join(lines))
            return

        if cmd.name == "repost":
            if not cmd.args:
                tg_client.send_message(chat_id, "Usage: /repost <channel_id> <message_id> OR /repost <message_id>")
                return
            if len(cmd.args) == 1:
                message_id = int(cmd.args[0])
                source_ids = runtime["source_channel_ids"] or settings.SOURCE_CHANNEL_IDS
                if len(source_ids) != 1:
                    tg_client.send_message(chat_id, "Ambiguous channel. Provide /repost <channel_id> <message_id>.")
                    return
                channel_id = source_ids[0]
            else:
                channel_id = int(cmd.args[0])
                message_id = int(cmd.args[1])
            tg_post = get_tg_post_by_ids(session, channel_id, message_id)
            if not tg_post:
                tg_client.send_message(chat_id, "Post not found in DB. Wait for ingestion or check IDs.")
                return
            if tg_post.media_group_id:
                finalize_album.apply_async(args=[tg_post.media_group_id])
                tg_client.send_message(chat_id, f"Album finalize queued for media_group_id={tg_post.media_group_id}")
            else:
                repost_tg_post.apply_async(args=[tg_post.id])
                tg_client.send_message(chat_id, f"Repost queued for tg_post_id={tg_post.id}")
            return

        if cmd.name == "retry_failed":
            limit = int(cmd.args[0]) if cmd.args else 5
            jobs = list_failed_jobs(session, limit)
            if not jobs:
                tg_client.send_message(chat_id, "No failed jobs")
                return
            for job in jobs:
                if job.tg_post_id:
                    repost_tg_post.apply_async(args=[job.tg_post_id])
                elif job.media_group_id:
                    finalize_album.apply_async(args=[job.media_group_id])
            tg_client.send_message(chat_id, f"Requeued {len(jobs)} job(s)")
            return

        tg_client.send_message(chat_id, "Unknown command. Use /help")


def main() -> None:
    settings = get_settings()
    setup_logging(settings.LOG_LEVEL)
    logger.info("poller_start", extra={"mode": settings.MODE})

    tg_client = TelegramClient(settings.TG_BOT_TOKEN)

    with session_scope() as session:
        ensure_defaults(session)

    while True:
        with session_scope() as session:
            defaults = _defaults_from_settings(settings)
            runtime = get_runtime_settings(session, defaults)
            last_update_id = get_last_update_id(session)

        try:
            updates = tg_client.get_updates(offset=last_update_id + 1, timeout=30)
        except Exception as exc:
            logger.error("tg_getupdates_failed", extra={"error": str(exc)})
            time.sleep(2)
            continue

        for update in updates:
            update_id = int(update["update_id"])
            try:
                if update.get("channel_post"):
                    handle_channel_post(update, settings, runtime)
                elif update.get("edited_channel_post"):
                    logger.info("edited_channel_post_ignored")
                elif update.get("message"):
                    handle_admin_message(update["message"], settings, tg_client)
            except Exception as exc:
                logger.error("update_processing_failed", extra={"error": str(exc), "update_id": update_id})
            finally:
                with session_scope() as session:
                    set_last_update_id(session, update_id)


if __name__ == "__main__":
    main()
