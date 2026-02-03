from __future__ import annotations

import os
from pathlib import Path


def ensure_dir(path: str) -> str:
    Path(path).mkdir(parents=True, exist_ok=True)
    return path


def build_temp_path(temp_dir: str, filename: str) -> str:
    ensure_dir(temp_dir)
    filename = os.path.basename(filename)
    return str(Path(temp_dir) / filename)


def cleanup_file(path: str | None) -> None:
    if not path:
        return
    try:
        Path(path).unlink(missing_ok=True)
    except Exception:
        pass
