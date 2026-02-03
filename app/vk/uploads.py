from __future__ import annotations

import os
from typing import Callable, Dict

import httpx

from app.logging_setup import get_logger
from app.utils.retry import retry
from app.vk.client import VKClient
from app.vk.types import VKAPIError


logger = get_logger(__name__)


def _call_with_fallback(
    client: VKClient, method: str, params: Dict, user_token: str | None
) -> Dict:
    try:
        return client.api(method, params)
    except VKAPIError as exc:
        if user_token and exc.is_permission_error():
            logger.warning("vk_permission_fallback", extra={"method": method, "error": str(exc)})
            return client.api(method, params, token_override=user_token)
        raise


def upload_photo(client: VKClient, file_path: str, group_id: int, user_token: str | None = None) -> str:
    server = _call_with_fallback(client, "photos.getWallUploadServer", {"group_id": group_id}, user_token)
    upload_url = server["upload_url"]
    with open(file_path, "rb") as f:
        response = retry(lambda: httpx.post(upload_url, files={"photo": f}, timeout=60))
    response.raise_for_status()
    uploaded = response.json()
    saved = _call_with_fallback(
        client,
        "photos.saveWallPhoto",
        {
            "group_id": group_id,
            "photo": uploaded.get("photo"),
            "server": uploaded.get("server"),
            "hash": uploaded.get("hash"),
        },
        user_token,
    )
    item = saved[0]
    return f"photo{item['owner_id']}_{item['id']}"


def upload_document(
    client: VKClient,
    file_path: str,
    group_id: int,
    title: str | None = None,
    user_token: str | None = None,
) -> str:
    server = _call_with_fallback(client, "docs.getWallUploadServer", {"group_id": group_id}, user_token)
    upload_url = server["upload_url"]
    with open(file_path, "rb") as f:
        response = retry(lambda: httpx.post(upload_url, files={"file": f}, timeout=60))
    response.raise_for_status()
    uploaded = response.json()
    saved = _call_with_fallback(
        client,
        "docs.save",
        {"file": uploaded.get("file"), "title": title or os.path.basename(file_path)},
        user_token,
    )
    doc = saved.get("doc") or saved.get("audio_message") or saved
    return f"doc{doc['owner_id']}_{doc['id']}"


def upload_video(
    client: VKClient,
    file_path: str,
    group_id: int,
    title: str | None = None,
    user_token: str | None = None,
) -> str:
    save = _call_with_fallback(
        client,
        "video.save",
        {"group_id": group_id, "name": title or os.path.basename(file_path)},
        user_token,
    )
    upload_url = save["upload_url"]
    with open(file_path, "rb") as f:
        response = retry(lambda: httpx.post(upload_url, files={"video_file": f}, timeout=120))
    response.raise_for_status()
    owner_id = save.get("owner_id")
    video_id = save.get("video_id")
    return f"video{owner_id}_{video_id}"
