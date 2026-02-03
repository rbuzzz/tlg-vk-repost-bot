from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Tuple

from app.config import get_settings
from app.crud import (
    create_job,
    get_album_posts,
    get_runtime_settings,
    get_tg_post_by_id,
    get_vk_post,
    list_media_items_for_post,
    list_media_items_for_posts,
    mark_album_finalized,
    record_vk_post,
    update_job,
)
from app.db import session_scope
from app.logging_setup import get_logger, setup_logging
from app.models import AlbumState
from app.tasks.celery_app import celery_app
from app.tasks.utils import build_tg_link, notify_admins
from app.tg.client import TelegramClient
from app.utils.files import cleanup_file, ensure_dir
from app.utils.locks import RedisLock
from app.vk.client import VKClient
from app.vk.uploads import upload_document, upload_photo, upload_video
from app.vk.wall import post_to_wall


settings = get_settings()
setup_logging(settings.LOG_LEVEL)
logger = get_logger(__name__)


def _defaults_from_settings() -> dict:
    return {
        "autoposting_enabled": True,
        "mode": settings.MODE,
        "limit_strategy": settings.LIMIT_STRATEGY,
        "vk_group_id": settings.VK_GROUP_ID,
        "source_channel_ids": ",".join(str(x) for x in settings.SOURCE_CHANNEL_IDS),
    }


def _load_runtime() -> dict:
    with session_scope() as session:
        return get_runtime_settings(session, _defaults_from_settings())


def _chunk_list(items: List[str], size: int) -> List[List[str]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def _build_message(base_text: str | None, notes: List[str]) -> str:
    base = base_text or ""
    if notes:
        note_text = "\n".join(notes)
        if base:
            base += "\n\n" + note_text
        else:
            base = note_text
    return base


def _upload_media_items(
    media_items,
    tg_client: TelegramClient,
    vk_client: VKClient,
    vk_group_id: int,
) -> Tuple[List[str], List[str]]:
    ensure_dir(settings.TEMP_DIR)
    attachments: List[str] = []
    notes: List[str] = []

    max_bytes = settings.MAX_FILE_SIZE_MB * 1024 * 1024

    for item in media_items:
        file_id = item.file_id
        file_name_hint = item.file_name or file_id

        downloaded = tg_client.download_file_by_id(file_id, settings.TEMP_DIR, max_bytes)
        if downloaded is None:
            notes.append(f"Skipped {file_name_hint}: exceeds {settings.MAX_FILE_SIZE_MB}MB")
            continue

        try:
            if item.type == "photo":
                attachment = upload_photo(
                    vk_client,
                    downloaded.path,
                    vk_group_id,
                    user_token=settings.VK_USER_ACCESS_TOKEN,
                )
            elif item.type == "video":
                attachment = upload_video(
                    vk_client,
                    downloaded.path,
                    vk_group_id,
                    title=file_name_hint,
                    user_token=settings.VK_USER_ACCESS_TOKEN,
                )
            elif item.type == "document":
                attachment = upload_document(
                    vk_client,
                    downloaded.path,
                    vk_group_id,
                    title=file_name_hint,
                    user_token=settings.VK_USER_ACCESS_TOKEN,
                )
            else:
                notes.append(f"Skipped unsupported type: {item.type}")
                continue

            attachments.append(attachment)
        finally:
            cleanup_file(downloaded.path)

    return attachments, notes


def _post_with_limit_strategy(
    vk_client: VKClient,
    vk_group_id: int,
    message: str,
    attachments: List[str],
    limit_strategy: str,
    tg_link: str,
    notes: List[str],
) -> List[dict]:
    responses: List[dict] = []

    if len(attachments) <= 10:
        final_message = _build_message(message, notes)
        response = post_to_wall(vk_client, vk_group_id, final_message, attachments)
        responses.append(response)
        return responses

    if limit_strategy == "split_posts":
        chunks = _chunk_list(attachments, 10)
        total = len(chunks)
        for idx, chunk in enumerate(chunks, start=1):
            prefix = f"{idx}/{total} "
            part_message = prefix + (message or "")
            if idx == 1:
                part_message = _build_message(part_message, notes)
            response = post_to_wall(vk_client, vk_group_id, part_message, chunk)
            responses.append(response)
        return responses

    trunc_notes = list(notes)
    trunc_notes.append("Attachments were truncated due to VK limit (10).")
    trunc_notes.append(f"Full post: {tg_link}")
    final_message = _build_message(message, trunc_notes)
    response = post_to_wall(vk_client, vk_group_id, final_message, attachments[:10])
    responses.append(response)
    return responses


@celery_app.task(bind=True)
def repost_tg_post(self, tg_post_id: int) -> None:
    runtime = _load_runtime()
    vk_group_id = runtime["vk_group_id"]

    job_id = None
    with session_scope() as session:
        job = create_job(session, "repost_single", "running", tg_post_id=tg_post_id)
        job_id = job.id

    try:
        with session_scope() as session:
            tg_post = get_tg_post_by_id(session, tg_post_id)
            if tg_post is None:
                update_job(session, job_id, "failed", last_error="TG post not found")
                return
            existing = get_vk_post(session, tg_post_id)
            if existing:
                update_job(session, job_id, "success", last_error="Already posted")
                return
            if tg_post.media_group_id:
                update_job(session, job_id, "success", last_error="Album item; waiting for finalize")
                return
            media_items = list_media_items_for_post(session, tg_post_id)
            payload_json = tg_post.payload_json

        tg_client = TelegramClient(settings.TG_BOT_TOKEN)
        vk_client = VKClient(settings.VK_ACCESS_TOKEN, settings.VK_API_VERSION)

        attachments, notes = _upload_media_items(media_items, tg_client, vk_client, vk_group_id)
        if not attachments and not (tg_post.text or "").strip():
            with session_scope() as session:
                update_job(session, job_id, "success", last_error="Empty post")
            return

        tg_link = build_tg_link(payload_json, tg_post.channel_id, tg_post.message_id)
        responses = _post_with_limit_strategy(
            vk_client,
            vk_group_id,
            tg_post.text or "",
            attachments,
            runtime["limit_strategy"],
            tg_link,
            notes,
        )

        vk_owner_id = -int(vk_group_id)
        vk_post_id = int(responses[0].get("post_id", 0)) if responses else 0
        with session_scope() as session:
            record_vk_post(
                session,
                tg_post_id=tg_post_id,
                vk_owner_id=vk_owner_id,
                vk_post_id=vk_post_id,
                status="posted",
                attachments_count=len(attachments),
                vk_response_json={"responses": responses},
            )
            update_job(session, job_id, "success")
        logger.info("repost_success", extra={"tg_post_id": tg_post_id})
    except Exception as exc:
        with session_scope() as session:
            update_job(session, job_id, "failed", last_error=str(exc))
        notify_admins(f"Repost failed for tg_post_id={tg_post_id}: {exc}")
        logger.error("repost_failed", extra={"tg_post_id": tg_post_id, "error": str(exc)})
        raise


@celery_app.task(bind=True)
def finalize_album(self, media_group_id: str) -> None:
    lock = RedisLock(settings.REDIS_URL, f"album:{media_group_id}", ttl=120)
    if not lock.acquire(timeout=0):
        logger.info("album_lock_busy", extra={"media_group_id": media_group_id})
        return

    runtime = _load_runtime()
    vk_group_id = runtime["vk_group_id"]
    job_id = None
    try:
        with session_scope() as session:
            job = create_job(session, "finalize_album", "running", media_group_id=media_group_id)
            job_id = job.id
            state = session.get(AlbumState, media_group_id)
            if state and state.status == "finalized":
                update_job(session, job_id, "success", last_error="Already finalized")
                return
            if state and state.last_seen_at:
                now = datetime.now(tz=timezone.utc)
                elapsed = (now - state.last_seen_at).total_seconds()
                if elapsed < settings.ALBUM_FINALIZE_DELAY_SEC:
                    delay = max(1, int(settings.ALBUM_FINALIZE_DELAY_SEC - elapsed))
                    finalize_album.apply_async(args=[media_group_id], countdown=delay)
                    update_job(session, job_id, "success", last_error="Rescheduled waiting for album")
                    logger.info(
                        "album_finalize_rescheduled",
                        extra={"media_group_id": media_group_id, "delay": delay},
                    )
                    return

        with session_scope() as session:
            posts = get_album_posts(session, media_group_id)
            if not posts:
                update_job(session, job_id, "failed", last_error="No posts for album")
                return
            for post in posts:
                if get_vk_post(session, post.id):
                    mark_album_finalized(session, media_group_id)
                    update_job(session, job_id, "success", last_error="Album already posted")
                    return
            post_ids = [p.id for p in posts]
            media_items = list_media_items_for_posts(session, post_ids)
            payload_json = posts[0].payload_json
            message = next((p.text for p in posts if p.text), "")

        post_order = {post.id: post.message_id for post in posts}
        media_items.sort(key=lambda item: (post_order.get(item.tg_post_id, 0), item.order_index))

        if not media_items and not message:
            with session_scope() as session:
                update_job(session, job_id, "success", last_error="Empty album")
            return

        tg_client = TelegramClient(settings.TG_BOT_TOKEN)
        vk_client = VKClient(settings.VK_ACCESS_TOKEN, settings.VK_API_VERSION)

        attachments, notes = _upload_media_items(media_items, tg_client, vk_client, vk_group_id)

        tg_link = build_tg_link(payload_json, posts[0].channel_id, posts[0].message_id)
        responses = _post_with_limit_strategy(
            vk_client,
            vk_group_id,
            message,
            attachments,
            runtime["limit_strategy"],
            tg_link,
            notes,
        )

        vk_owner_id = -int(vk_group_id)
        vk_post_id = int(responses[0].get("post_id", 0)) if responses else 0

        with session_scope() as session:
            mark_album_finalized(session, media_group_id)
            for post in posts:
                record_vk_post(
                    session,
                    tg_post_id=post.id,
                    vk_owner_id=vk_owner_id,
                    vk_post_id=vk_post_id,
                    status="posted",
                    attachments_count=len(attachments),
                    vk_response_json={"responses": responses},
                )
            update_job(session, job_id, "success")
        logger.info("album_finalize_success", extra={"media_group_id": media_group_id})
    except Exception as exc:
        with session_scope() as session:
            if job_id:
                update_job(session, job_id, "failed", last_error=str(exc))
        notify_admins(f"Album finalize failed for media_group_id={media_group_id}: {exc}")
        logger.error("album_finalize_failed", extra={"media_group_id": media_group_id, "error": str(exc)})
        raise
    finally:
        lock.release()
