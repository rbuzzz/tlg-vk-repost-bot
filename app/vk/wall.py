from __future__ import annotations

from typing import List

from app.vk.client import VKClient


def post_to_wall(client: VKClient, group_id: int, message: str, attachments: List[str]) -> dict:
    params = {
        "owner_id": -int(group_id),
        "from_group": 1,
        "message": message,
    }
    if attachments:
        params["attachments"] = ",".join(attachments)
    return client.api("wall.post", params)
