"""
Redis distributed locks (single-node Redlock variant).

Usage:
    async with DistributedLock(redis, "payment:approve:42", ttl=10):
        await approve_payment(42)

Non-blocking try:
    acquired = await lock.try_acquire()
    if acquired:
        ...
        await lock.release()
"""

import asyncio
import time
import uuid
from typing import Optional
from redis.asyncio import Redis
from loguru import logger


class LockNotAcquiredError(Exception):
    pass


class DistributedLock:
    def __init__(
        self,
        redis: Redis,
        name: str,
        ttl: int = 30,
        retry_times: int = 3,
        retry_delay: float = 0.1,
        prefix: str = "lock",
    ):
        self.redis = redis
        self.key = f"{prefix}:{name}"
        self.ttl = ttl
        self.retry_times = retry_times
        self.retry_delay = retry_delay
        self._token: Optional[str] = None

    async def acquire(self) -> bool:
        token = str(uuid.uuid4())
        for attempt in range(self.retry_times):
            ok = await self.redis.set(self.key, token, nx=True, ex=self.ttl)
            if ok:
                self._token = token
                return True
            if attempt < self.retry_times - 1:
                await asyncio.sleep(self.retry_delay * (attempt + 1))
        return False

    async def try_acquire(self) -> bool:
        token = str(uuid.uuid4())
        ok = await self.redis.set(self.key, token, nx=True, ex=self.ttl)
        if ok:
            self._token = token
            return True
        return False

    async def release(self) -> None:
        if not self._token:
            return
        current = await self.redis.get(self.key)
        if current and current.decode() == self._token:
            await self.redis.delete(self.key)
            self._token = None

    async def extend(self, extra_seconds: int) -> bool:
        if not self._token:
            return False
        current = await self.redis.get(self.key)
        if current and current.decode() == self._token:
            await self.redis.expire(self.key, self.ttl + extra_seconds)
            return True
        return False

    async def __aenter__(self) -> "DistributedLock":
        acquired = await self.acquire()
        if not acquired:
            raise LockNotAcquiredError(f"Could not acquire lock: {self.key}")
        return self

    async def __aexit__(self, *args) -> None:
        await self.release()


def payment_lock(redis: Redis, payment_id: int) -> DistributedLock:
    return DistributedLock(redis, f"payment:{payment_id}", ttl=15)


def access_grant_lock(redis: Redis, user_id: int, group_id: int) -> DistributedLock:
    return DistributedLock(redis, f"access:{user_id}:{group_id}", ttl=10)


def cache_warm_lock(redis: Redis, group_id: int) -> DistributedLock:
    return DistributedLock(redis, f"cache_warm:{group_id}", ttl=30, retry_times=1)
