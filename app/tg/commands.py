from __future__ import annotations

from dataclasses import dataclass
from typing import List


@dataclass
class Command:
    name: str
    args: List[str]


def parse_command(text: str | None) -> Command | None:
    if not text:
        return None
    text = text.strip()
    if not text.startswith("/"):
        return None
    parts = text.split()
    if not parts:
        return None
    name = parts[0].split("@")[0].lower()
    if name.startswith("/"):
        name = name[1:]
    args = parts[1:]
    return Command(name=name, args=args)


def is_admin(user_id: int, admin_ids: List[int]) -> bool:
    return user_id in admin_ids
