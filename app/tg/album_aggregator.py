from __future__ import annotations

from app.tasks.repost import finalize_album


def schedule_album_finalize(media_group_id: str, delay: int) -> None:
    finalize_album.apply_async(args=[media_group_id], countdown=delay)
