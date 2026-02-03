from __future__ import annotations

import time
from typing import Any, Dict

import httpx

from app.config import get_settings
from app.crud import get_setting, set_setting
from app.db import session_scope
from app.logging_setup import get_logger
from app.utils.locks import RedisLock
from app.utils.retry import retry


settings = get_settings()
logger = get_logger(__name__)


def _now() -> int:
    return int(time.time())


def _settings_get(key: str, fallback: str | None = None) -> str | None:
    with session_scope() as session:
        return get_setting(session, key, fallback)


def _settings_set(key: str, value: str) -> None:
    with session_scope() as session:
        set_setting(session, key, value)


def _load_token_state() -> Dict[str, Any]:
    return {
        "access_token": _settings_get("vk_user_access_token", settings.VK_USER_ACCESS_TOKEN),
        "refresh_token": _settings_get("vk_user_refresh_token", settings.VK_USER_REFRESH_TOKEN),
        "expires_at": _settings_get(
            "vk_user_token_expires_at",
            str(settings.VK_USER_TOKEN_EXPIRES_AT) if settings.VK_USER_TOKEN_EXPIRES_AT else None,
        ),
        "client_id": _settings_get("vk_user_client_id", settings.VK_USER_CLIENT_ID),
        "device_id": _settings_get("vk_user_device_id", settings.VK_USER_DEVICE_ID),
        "state": _settings_get("vk_user_state", settings.VK_USER_STATE),
    }


def _save_token_state(access_token: str, refresh_token: str, expires_at: int) -> None:
    _settings_set("vk_user_access_token", access_token)
    _settings_set("vk_user_refresh_token", refresh_token)
    _settings_set("vk_user_token_expires_at", str(expires_at))


def _refresh_token(state: Dict[str, Any]) -> str:
    params = {
        "grant_type": "refresh_token",
        "refresh_token": state["refresh_token"],
        "client_id": state["client_id"],
    }
    if state.get("device_id"):
        params["device_id"] = state["device_id"]
    if state.get("state"):
        params["state"] = state["state"]

    def do_request() -> httpx.Response:
        return httpx.post(settings.VK_ID_OAUTH_URL, data=params, timeout=30)

    response = retry(
        do_request,
        on_retry=lambda attempt, exc, delay: logger.warning(
            "vk_token_refresh_retry",
            extra={"attempt": attempt, "delay": delay, "error": str(exc)},
        ),
    )
    response.raise_for_status()
    data = response.json()
    access_token = data.get("access_token")
    refresh_token = data.get("refresh_token")
    expires_in = int(data.get("expires_in", 0))
    if not access_token or not refresh_token or not expires_in:
        raise RuntimeError(f"Unexpected token refresh response: {data}")
    expires_at = _now() + expires_in
    _save_token_state(access_token, refresh_token, expires_at)
    logger.info("vk_token_refreshed", extra={"expires_in": expires_in})
    return access_token


def get_user_access_token(min_ttl_seconds: int = 120) -> str | None:
    lock = RedisLock(settings.REDIS_URL, "vk_user_token_refresh", ttl=60)
    if not lock.acquire(timeout=5):
        logger.warning("vk_token_refresh_lock_busy")
        return _settings_get("vk_user_access_token", settings.VK_USER_ACCESS_TOKEN)

    try:
        state = _load_token_state()
        access_token = state.get("access_token")
        refresh_token = state.get("refresh_token")
        expires_at_raw = state.get("expires_at")
        client_id = state.get("client_id")

        if not access_token:
            return None

        if not refresh_token or not client_id:
            return access_token

        expires_at = int(expires_at_raw) if expires_at_raw else 0
        if expires_at and (_now() + min_ttl_seconds) < expires_at:
            return access_token

        return _refresh_token(state)
    finally:
        lock.release()
