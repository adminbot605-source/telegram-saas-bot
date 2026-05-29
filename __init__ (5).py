"""
Redis-based message delete queue with retry and dead-letter queue (DLQ).

Architecture:
  delete_queue          → Redis LIST (LPUSH/BRPOP) — primary queue
  delete_queue:retry    → Redis ZSET score=next_attempt_ts — retry queue
  delete_queue:dlq      → Redis ZSET score=failed_at_ts — dead letter queue
  delete_queue:inflight → Redis HASH msg_id → payload — in-flight tracking

Workers consume from the queue and handle FloodWait, 429, etc.
"""

import asyncio
import json
import time
from typing import Optional
from dataclasses import dataclass, asdict
from redis.asyncio import Redis
from loguru import logger


QUEUE_KEY = "delete_queue"
RETRY_KEY = "delete_queue:retry"
DLQ_KEY = "delete_queue:dlq"
INFLIGHT_KEY = "delete_queue:inflight"

MAX_ATTEMPTS = 5
RETRY_DELAYS = [1, 3, 10, 30, 120]  # seconds per attempt


@dataclass
class DeleteTask:
    chat_id: int
    message_id: int
    user_id: int
    attempt: int = 0
    enqueued_at: float = 0.0
    reason: str = "unauthorized"

    def to_json(self) -> str:
        d = asdict(self)
        d["enqueued_at"] = d["enqueued_at"] or time.time()
        return json.dumps(d)

    @classmethod
    def from_json(cls, data: str) -> "DeleteTask":
        return cls(**json.loads(data))

    @property
    def key(self) -> str:
        return f"{self.chat_id}:{self.message_id}"


class DeleteQueue:
    def __init__(self, redis: Redis):
        self.redis = redis
        self._running = False

    async def enqueue(self, chat_id: int, message_id: int, user_id: int, reason: str = "unauthorized") -> None:
        task = DeleteTask(chat_id=chat_id, message_id=message_id, user_id=user_id, reason=reason, enqueued_at=time.time())
        await self.redis.lpush(QUEUE_KEY, task.to_json())

    async def enqueue_batch(self, tasks: list[tuple[int, int, int]]) -> None:
        """Batch enqueue: list of (chat_id, message_id, user_id)."""
        if not tasks:
            return
        pipe = self.redis.pipeline(transaction=False)
        for chat_id, msg_id, user_id in tasks:
            task = DeleteTask(chat_id=chat_id, message_id=msg_id, user_id=user_id, enqueued_at=time.time())
            pipe.lpush(QUEUE_KEY, task.to_json())
        await pipe.execute()

    async def dequeue(self, timeout: int = 1) -> Optional[DeleteTask]:
        result = await self.redis.brpop(QUEUE_KEY, timeout=timeout)
        if not result:
            return None
        _, data = result
        try:
            return DeleteTask.from_json(data)
        except Exception as e:
            logger.error(f"DeleteQueue: malformed task {data!r}: {e}")
            return None

    async def requeue_for_retry(self, task: DeleteTask, flood_wait: int = 0) -> None:
        task.attempt += 1
        if task.attempt >= MAX_ATTEMPTS:
            await self._send_to_dlq(task, reason="max_attempts")
            return
        delay = flood_wait if flood_wait > 0 else RETRY_DELAYS[min(task.attempt - 1, len(RETRY_DELAYS) - 1)]
        next_at = time.time() + delay
        await self.redis.zadd(RETRY_KEY, {task.to_json(): next_at})
        logger.debug(f"Task {task.key} queued for retry #{task.attempt} in {delay}s")

    async def flush_ready_retries(self) -> int:
        """Move due retry tasks back to main queue. Call periodically."""
        now = time.time()
        tasks = await self.redis.zrangebyscore(RETRY_KEY, 0, now)
        if not tasks:
            return 0
        pipe = self.redis.pipeline(transaction=True)
        for raw in tasks:
            pipe.lpush(QUEUE_KEY, raw)
            pipe.zrem(RETRY_KEY, raw)
        await pipe.execute()
        if tasks:
            logger.debug(f"Flushed {len(tasks)} retry tasks to queue")
        return len(tasks)

    async def _send_to_dlq(self, task: DeleteTask, reason: str = "") -> None:
        task.reason = reason
        await self.redis.zadd(DLQ_KEY, {task.to_json(): time.time()})
        logger.warning(f"Task {task.key} → DLQ (reason={reason})")

    async def dlq_size(self) -> int:
        return await self.redis.zcard(DLQ_KEY)

    async def queue_size(self) -> int:
        return await self.redis.llen(QUEUE_KEY)

    async def retry_size(self) -> int:
        return await self.redis.zcard(RETRY_KEY)

    async def drain_dlq(self, limit: int = 100) -> list[DeleteTask]:
        raw = await self.redis.zrange(DLQ_KEY, 0, limit - 1)
        return [DeleteTask.from_json(r) for r in raw]

    async def purge_old_dlq(self, max_age_hours: int = 48) -> int:
        cutoff = time.time() - max_age_hours * 3600
        count = await self.redis.zremrangebyscore(DLQ_KEY, 0, cutoff)
        return count
