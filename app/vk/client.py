from __future__ import annotations

from typing import Any, Dict

import httpx

from app.logging_setup import get_logger
from app.utils.retry import retry
from app.vk.types import VKAPIError


class VKClient:
    def __init__(self, access_token: str, api_version: str = "5.199") -> None:
        self.access_token = access_token
        self.api_version = api_version
        self.base_url = "https://api.vk.com/method"
        self._client = httpx.Client()
        self.logger = get_logger(__name__)

    def api(self, method: str, params: Dict[str, Any], token_override: str | None = None) -> Dict[str, Any]:
        token = token_override or self.access_token
        payload = dict(params)
        payload["access_token"] = token
        payload["v"] = self.api_version
        url = f"{self.base_url}/{method}"

        def do_request() -> httpx.Response:
            return self._client.post(url, data=payload, timeout=30)

        response = retry(
            do_request,
            on_retry=lambda attempt, exc, delay: self.logger.warning(
                "vk_request_retry",
                extra={"method": method, "attempt": attempt, "delay": delay, "error": str(exc)},
            ),
        )
        response.raise_for_status()
        data = response.json()
        if "error" in data:
            error = data["error"]
            raise VKAPIError(code=int(error.get("error_code", -1)), message=error.get("error_msg", ""), params=error)
        return data.get("response") or {}
