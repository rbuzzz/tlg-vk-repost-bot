from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable, List, Tuple

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import (
    AlbumState,
    Job,
    Setting,
    TgMediaItem,
    TgPost,
    TgState,
    VkPost,
)


def utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


def ensure_defaults(session: Session) -> None:
    if session.get(TgState, 1) is None:
        session.add(TgState(id=1, last_update_id=0))
    if session.get(Setting, "autoposting_enabled") is None:
        session.add(Setting(key="autoposting_enabled", value="true"))
    session.commit()


def get_last_update_id(session: Session) -> int:
    state = session.get(TgState, 1)
    if state is None or state.last_update_id is None:
        return 0
    return int(state.last_update_id)


def set_last_update_id(session: Session, value: int) -> None:
    state = session.get(TgState, 1)
    if state is None:
        state = TgState(id=1, last_update_id=value)
        session.add(state)
    else:
        state.last_update_id = value
    session.commit()


def get_setting(session: Session, key: str, default: str | None = None) -> str | None:
    setting = session.get(Setting, key)
    if setting is None:
        return default
    return setting.value


def set_setting(session: Session, key: str, value: str) -> None:
    setting = session.get(Setting, key)
    if setting is None:
        session.add(Setting(key=key, value=value))
    else:
        setting.value = value
    session.commit()


def _parse_int_list(value: str | None) -> List[int]:
    if not value:
        return []
    items: List[int] = []
    for part in value.split(","):
        part = part.strip()
        if not part:
            continue
        items.append(int(part))
    return items


def get_runtime_settings(session: Session, defaults: dict) -> dict:
    autoposting_raw = get_setting(session, "autoposting_enabled", str(defaults["autoposting_enabled"]))
    mode = get_setting(session, "mode", defaults["mode"])
    limit_strategy = get_setting(session, "limit_strategy", defaults["limit_strategy"])
    vk_group_id_raw = get_setting(session, "vk_group_id", str(defaults["vk_group_id"]))
    source_raw = get_setting(session, "source_channel_ids", defaults.get("source_channel_ids", ""))

    return {
        "autoposting_enabled": str(autoposting_raw).lower() == "true",
        "mode": (mode or "auto"),
        "limit_strategy": (limit_strategy or "truncate"),
        "vk_group_id": int(vk_group_id_raw or defaults["vk_group_id"]),
        "source_channel_ids": _parse_int_list(source_raw),
    }


def create_tg_post(
    session: Session,
    channel_id: int,
    message_id: int,
    date: datetime,
    text: str | None,
    media_group_id: str | None,
    payload_json: dict,
) -> Tuple[TgPost, bool]:
    tg_post = TgPost(
        channel_id=channel_id,
        message_id=message_id,
        date=date,
        text=text,
        media_group_id=media_group_id,
        status="ingested",
        payload_json=payload_json,
    )
    try:
        session.add(tg_post)
        session.flush()
        created = True
    except IntegrityError:
        session.rollback()
        tg_post = session.execute(
            select(TgPost).where(
                TgPost.channel_id == channel_id, TgPost.message_id == message_id
            )
        ).scalar_one()
        created = False
    return tg_post, created


def add_media_items(session: Session, tg_post_id: int, items: Iterable[dict]) -> None:
    for item in items:
        session.add(
            TgMediaItem(
                tg_post_id=tg_post_id,
                type=item["type"],
                file_id=item["file_id"],
                file_unique_id=item.get("file_unique_id"),
                mime_type=item.get("mime_type"),
                file_name=item.get("file_name"),
                size=item.get("size"),
                order_index=item.get("order_index", 0),
            )
        )


def touch_album_state(
    session: Session,
    media_group_id: str,
    first_tg_post_id: int | None = None,
) -> AlbumState:
    state = session.get(AlbumState, media_group_id)
    now = utcnow()
    if state is None:
        state = AlbumState(
            media_group_id=media_group_id,
            status="pending",
            last_seen_at=now,
            first_tg_post_id=first_tg_post_id,
        )
        session.add(state)
    else:
        state.last_seen_at = now
        if state.status != "finalized":
            state.status = "pending"
        if state.first_tg_post_id is None and first_tg_post_id:
            state.first_tg_post_id = first_tg_post_id
    return state


def mark_album_finalized(session: Session, media_group_id: str) -> None:
    state = session.get(AlbumState, media_group_id)
    if state is None:
        return
    state.status = "finalized"
    state.finalized_at = utcnow()


def get_album_posts(session: Session, media_group_id: str) -> List[TgPost]:
    return (
        session.execute(
            select(TgPost).where(TgPost.media_group_id == media_group_id).order_by(TgPost.message_id)
        )
        .scalars()
        .all()
    )


def get_tg_post_by_ids(session: Session, channel_id: int, message_id: int) -> TgPost | None:
    return (
        session.execute(
            select(TgPost).where(
                TgPost.channel_id == channel_id, TgPost.message_id == message_id
            )
        )
        .scalars()
        .first()
    )


def get_tg_post_by_id(session: Session, tg_post_id: int) -> TgPost | None:
    return session.get(TgPost, tg_post_id)


def list_recent_tg_posts(session: Session, limit: int) -> List[TgPost]:
    return (
        session.execute(select(TgPost).order_by(TgPost.id.desc()).limit(limit))
        .scalars()
        .all()
    )


def list_media_items_for_posts(session: Session, tg_post_ids: List[int]) -> List[TgMediaItem]:
    if not tg_post_ids:
        return []
    return (
        session.execute(
            select(TgMediaItem)
            .where(TgMediaItem.tg_post_id.in_(tg_post_ids))
            .order_by(TgMediaItem.tg_post_id, TgMediaItem.order_index)
        )
        .scalars()
        .all()
    )


def list_media_items_for_post(session: Session, tg_post_id: int) -> List[TgMediaItem]:
    return (
        session.execute(
            select(TgMediaItem)
            .where(TgMediaItem.tg_post_id == tg_post_id)
            .order_by(TgMediaItem.order_index)
        )
        .scalars()
        .all()
    )


def get_vk_post(session: Session, tg_post_id: int) -> VkPost | None:
    return (
        session.execute(select(VkPost).where(VkPost.tg_post_id == tg_post_id))
        .scalars()
        .first()
    )


def record_vk_post(
    session: Session,
    tg_post_id: int,
    vk_owner_id: int,
    vk_post_id: int,
    status: str,
    attachments_count: int,
    vk_response_json: dict,
) -> None:
    vk_post = VkPost(
        tg_post_id=tg_post_id,
        vk_owner_id=vk_owner_id,
        vk_post_id=vk_post_id,
        status=status,
        attachments_count=attachments_count,
        vk_response_json=vk_response_json,
    )
    try:
        session.add(vk_post)
        session.flush()
    except IntegrityError:
        session.rollback()


def create_job(
    session: Session,
    job_type: str,
    status: str,
    retries: int = 0,
    last_error: str | None = None,
    tg_post_id: int | None = None,
    media_group_id: str | None = None,
) -> Job:
    job = Job(
        type=job_type,
        status=status,
        retries=retries,
        last_error=last_error,
        tg_post_id=tg_post_id,
        media_group_id=media_group_id,
    )
    session.add(job)
    session.flush()
    return job


def update_job(
    session: Session,
    job_id: int,
    status: str,
    retries: int | None = None,
    last_error: str | None = None,
) -> None:
    job = session.get(Job, job_id)
    if job is None:
        return
    job.status = status
    if retries is not None:
        job.retries = retries
    if last_error is not None:
        job.last_error = last_error


def list_failed_jobs(session: Session, limit: int) -> List[Job]:
    return (
        session.execute(
            select(Job).where(Job.status == "failed").order_by(Job.id.desc()).limit(limit)
        )
        .scalars()
        .all()
    )


def count_jobs_by_status(session: Session) -> dict:
    rows = session.execute(select(Job.status, Job.id)).all()
    counts: dict[str, int] = {}
    for status, _ in rows:
        counts[status] = counts.get(status, 0) + 1
    return counts


def get_last_job_errors(session: Session, limit: int = 5) -> List[Job]:
    return (
        session.execute(
            select(Job)
            .where(Job.last_error.is_not(None))
            .order_by(Job.id.desc())
            .limit(limit)
        )
        .scalars()
        .all()
    )
