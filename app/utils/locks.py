from __future__ import annotations

import time
import uuid

import redis


class RedisLock:
    def __init__(self, redis_url: str, key: str, ttl: int = 60):
        self.client = redis.Redis.from_url(redis_url)
        self.key = f"lock:{key}"
        self.ttl = ttl
        self.token = uuid.uuid4().hex

    def acquire(self, timeout: int = 0) -> bool:
        end = time.time() + timeout
        while True:
            if self.client.set(self.key, self.token, nx=True, ex=self.ttl):
                return True
            if timeout == 0 or time.time() >= end:
                return False
            time.sleep(0.1)

    def release(self) -> None:
        try:
            value = self.client.get(self.key)
            if value and value.decode() == self.token:
                self.client.delete(self.key)
        except Exception:
            pass

    def __enter__(self) -> "RedisLock":
        acquired = self.acquire()
        if not acquired:
            raise RuntimeError("Failed to acquire Redis lock")
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.release()
