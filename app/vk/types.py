from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict


@dataclass
class VKAPIError(RuntimeError):
    code: int
    message: str
    params: Dict[str, Any] | None = None

    def __str__(self) -> str:
        return f"VKAPIError(code={self.code}, message={self.message})"

    def is_permission_error(self) -> bool:
        return self.code in {5, 7, 15, 27, 30, 200}
