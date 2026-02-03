from __future__ import annotations

import random
import time
from typing import Callable, Iterable, Type

import httpx


def retry(
    func: Callable[[], object],
    *,
    tries: int = 5,
    base_delay: float = 0.5,
    max_delay: float = 10.0,
    jitter: float = 0.1,
    exceptions: Iterable[Type[BaseException]] = (httpx.RequestError, httpx.TimeoutException),
    on_retry: Callable[[int, BaseException, float], None] | None = None,
) -> object:
    attempt = 0
    while True:
        attempt += 1
        try:
            return func()
        except tuple(exceptions) as exc:
            if attempt >= tries:
                raise
            delay = min(max_delay, base_delay * (2 ** (attempt - 1)))
            delay *= 1 + (random.random() * jitter)
            if on_retry:
                on_retry(attempt, exc, delay)
            time.sleep(delay)
