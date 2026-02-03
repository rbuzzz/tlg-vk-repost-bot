from __future__ import annotations

from dataclasses import dataclass
import os
from typing import List

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    TG_BOT_TOKEN: str
    ADMIN_IDS: List[int]
    SOURCE_CHANNEL_IDS: List[int]
    VK_GROUP_ID: int
    VK_ACCESS_TOKEN: str
    VK_USER_ACCESS_TOKEN: str | None
    VK_API_VERSION: str
    MODE: str
    LIMIT_STRATEGY: str
    ALBUM_FINALIZE_DELAY_SEC: int
    MAX_FILE_SIZE_MB: int
    DATABASE_URL: str
    REDIS_URL: str
    LOG_LEVEL: str
    TEMP_DIR: str


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


def _require(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise ValueError(f"Missing required env var: {name}")
    return value


_settings: Settings | None = None
_env_loaded = False


def get_settings() -> Settings:
    global _settings, _env_loaded
    if _settings is not None:
        return _settings

    if not _env_loaded:
        load_dotenv()
        _env_loaded = True

    tg_bot_token = _require("TG_BOT_TOKEN")
    vk_access_token = _require("VK_ACCESS_TOKEN")
    vk_group_id = int(_require("VK_GROUP_ID"))
    database_url = _require("DATABASE_URL")
    redis_url = _require("REDIS_URL")

    _settings = Settings(
        TG_BOT_TOKEN=tg_bot_token,
        ADMIN_IDS=_parse_int_list(os.getenv("ADMIN_IDS", "")),
        SOURCE_CHANNEL_IDS=_parse_int_list(os.getenv("SOURCE_CHANNEL_IDS", "")),
        VK_GROUP_ID=vk_group_id,
        VK_ACCESS_TOKEN=vk_access_token,
        VK_USER_ACCESS_TOKEN=os.getenv("VK_USER_ACCESS_TOKEN") or None,
        VK_API_VERSION=os.getenv("VK_API_VERSION", "5.199"),
        MODE=os.getenv("MODE", "auto"),
        LIMIT_STRATEGY=os.getenv("LIMIT_STRATEGY", "truncate"),
        ALBUM_FINALIZE_DELAY_SEC=int(os.getenv("ALBUM_FINALIZE_DELAY_SEC", "3")),
        MAX_FILE_SIZE_MB=int(os.getenv("MAX_FILE_SIZE_MB", "200")),
        DATABASE_URL=database_url,
        REDIS_URL=redis_url,
        LOG_LEVEL=os.getenv("LOG_LEVEL", "INFO"),
        TEMP_DIR=os.getenv("TEMP_DIR", "/tmp/tg_vk_bot"),
    )

    return _settings
