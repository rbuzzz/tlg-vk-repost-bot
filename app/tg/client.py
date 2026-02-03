from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Any, Dict, List

import httpx

from app.logging_setup import get_logger
from app.utils.retry import retry


class TelegramAPIError(RuntimeError):
    pass


@dataclass
class DownloadedFile:
    path: str
    size: int
    file_name: str


class TelegramClient:
    def __init__(self, token: str, timeout: int = 30) -> None:
        self.token = token
        self.base_url = f"https://api.telegram.org/bot{token}"
        self.file_base_url = f"https://api.telegram.org/file/bot{token}"
        self.timeout = timeout
        self._client = httpx.Client()
        self.logger = get_logger(__name__)

    def _request(self, method: str, params: Dict[str, Any] | None = None, timeout: int | None = None) -> Any:
        url = f"{self.base_url}/{method}"

        def do_request() -> httpx.Response:
            return self._client.post(url, data=params, timeout=timeout or self.timeout)

        response = retry(
            do_request,
            on_retry=lambda attempt, exc, delay: self.logger.warning(
                "tg_request_retry",
                extra={"method": method, "attempt": attempt, "delay": delay, "error": str(exc)},
            ),
        )
        response.raise_for_status()
        payload = response.json()
        if not payload.get("ok"):
            raise TelegramAPIError(payload.get("description", "Telegram API error"))
        return payload.get("result")

    def get_updates(self, offset: int, timeout: int = 30) -> List[Dict[str, Any]]:
        params = {
            "offset": offset,
            "timeout": timeout,
            "allowed_updates": ["channel_post", "edited_channel_post", "message"],
        }
        result = self._request("getUpdates", params=params, timeout=timeout + 10)
        return result or []

    def send_message(self, chat_id: int, text: str) -> None:
        params = {"chat_id": chat_id, "text": text}
        self._request("sendMessage", params=params)

    def get_file(self, file_id: str) -> Dict[str, Any]:
        params = {"file_id": file_id}
        return self._request("getFile", params=params)

    def get_chat(self, chat_id_or_username: str) -> Dict[str, Any]:
        params = {"chat_id": chat_id_or_username}
        return self._request("getChat", params=params)

    def download_file(self, file_path: str, dest_path: str) -> int:
        url = f"{self.file_base_url}/{file_path}"
        temp_path = dest_path + ".part"

        def do_download() -> int:
            with self._client.stream("GET", url, timeout=self.timeout + 30) as response:
                response.raise_for_status()
                size = 0
                with open(temp_path, "wb") as f:
                    for chunk in response.iter_bytes():
                        f.write(chunk)
                        size += len(chunk)
                return size

        size = retry(
            do_download,
            on_retry=lambda attempt, exc, delay: self.logger.warning(
                "tg_download_retry",
                extra={"attempt": attempt, "delay": delay, "error": str(exc)},
            ),
        )
        os.replace(temp_path, dest_path)
        return size

    def download_file_by_id(self, file_id: str, dest_dir: str, max_size_bytes: int) -> DownloadedFile | None:
        info = self.get_file(file_id)
        file_path = info.get("file_path")
        file_size = int(info.get("file_size", 0))
        if file_size and file_size > max_size_bytes:
            return None
        if not file_path:
            raise TelegramAPIError("Missing file_path in getFile response")
        file_name = os.path.basename(file_path)
        dest_path = os.path.join(dest_dir, file_name)
        actual_size = self.download_file(file_path, dest_path)
        if actual_size > max_size_bytes:
            try:
                os.remove(dest_path)
            except Exception:
                pass
            return None
        return DownloadedFile(path=dest_path, size=actual_size, file_name=file_name)
