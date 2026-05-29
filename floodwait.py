"""
Redis-based access cache for ultra-fast message filtering.

Architecture:
  access:group:{group_id}:users  → Redis SET of authorized user_ids
  access:group:{group_id}:admins → Redis SET of admin user_ids
  access:group:{group_id}:loaded → flag indicating cache is warm

All checks are O(1) SISMEMBER operations.
Cache is invalidated on access grant/revoke and refreshed lazily.
"""

import asyncio
from typing import Optional, Set
from redis.asyncio import Redis
from loguru import logger
from bot.config import settings


class AccessCache:
    def __init__(self, redis: Redis):
        self.redis = redis
        self.ttl = settings.ACCESS_CACHE_TTL
        self._prefix = settings.ACCESS_CACHE_KEY_PREFIX

    def _users_key(self, group_id: int) -> str:
        return f"{self._prefix}:group:{group_id}:users"

    def _admins_key(self, group_id: int) -> str:
        return f"{self._prefix}:group:{group_id}:admins"

    def _loaded_key(self, group_id: int) -> str:
        return f"{self._prefix}:group:{group_id}:loaded"

    async def is_cache_warm(self, group_id: int) -> bool:
        return bool(await self.redis.exists(self._loaded_key(group_id)))

    async def check_user_access(self, group_id: int, user_id: int) -> bool:
        """O(1) check. Returns True if user has access."""
        pipe = self.redis.pipeline(transaction=False)
        pipe.sismember(self._users_key(group_id), user_id)
        pipe.sismember(self._admins_key(group_id), user_id)
        results = await pipe.execute()
        return bool(results[0]) or bool(results[1])

    async def check_is_admin(self, group_id: int, user_id: int) -> bool:
        return bool(await self.redis.sismember(self._admins_key(group_id), user_id))

    async def grant_access(self, group_id: int, user_id: int) -> None:
        pipe = self.redis.pipeline(transaction=True)
        pipe.sadd(self._users_key(group_id), user_id)
        pipe.expire(self._users_key(group_id), self.ttl)
        await pipe.execute()

    async def revoke_access(self, group_id: int, user_id: int) -> None:
        await self.redis.srem(self._users_key(group_id), user_id)

    async def grant_admin(self, group_id: int, user_id: int) -> None:
        pipe = self.redis.pipeline(transaction=True)
        pipe.sadd(self._admins_key(group_id), user_id)
        pipe.expire(self._admins_key(group_id), self.ttl)
        await pipe.execute()

    async def revoke_admin(self, group_id: int, user_id: int) -> None:
        await self.redis.srem(self._admins_key(group_id), user_id)

    async def warm_group_cache(
        self,
        group_id: int,
        user_ids: Set[int],
        admin_ids: Set[int],
    ) -> None:
        """Bulk load access data into Redis. Called once per group."""
        pipe = self.redis.pipeline(transaction=True)

        users_key = self._users_key(group_id)
        admins_key = self._admins_key(group_id)
        loaded_key = self._loaded_key(group_id)

        pipe.delete(users_key, admins_key, loaded_key)

        if user_ids:
            pipe.sadd(users_key, *user_ids)
        if admin_ids:
            pipe.sadd(admins_key, *admin_ids)

        pipe.set(loaded_key, "1", ex=self.ttl)
        pipe.expire(users_key, self.ttl)
        pipe.expire(admins_key, self.ttl)

        await pipe.execute()
        logger.debug(
            f"Cache warmed for group {group_id}: "
            f"{len(user_ids)} users, {len(admin_ids)} admins"
        )

    async def invalidate_group(self, group_id: int) -> None:
        """Force cache rebuild on next message."""
        await self.redis.delete(
            self._users_key(group_id),
            self._admins_key(group_id),
            self._loaded_key(group_id),
        )
        logger.debug(f"Cache invalidated for group {group_id}")

    async def bulk_revoke_expired(self, group_id: int, user_ids: Set[int]) -> None:
        if not user_ids:
            return
        await self.redis.srem(self._users_key(group_id), *user_ids)

    async def get_cached_users(self, group_id: int) -> Set[int]:
        members = await self.redis.smembers(self._users_key(group_id))
        return {int(m) for m in members}

    async def ping(self) -> bool:
        try:
            return await self.redis.ping()
        except Exception:
            return False

    async def set_temp(self, key: str, value: str, ttl: int = 300) -> None:
        await self.redis.set(key, value, ex=ttl)

    async def get_temp(self, key: str) -> Optional[str]:
        val = await self.redis.get(key)
        return val.decode() if val else None

    async def delete_temp(self, key: str) -> None:
        await self.redis.delete(key)

    async def incr(self, key: str, ttl: int = 86400) -> int:
        pipe = self.redis.pipeline(transaction=True)
        pipe.incr(key)
        pipe.expire(key, ttl)
        results = await pipe.execute()
        return results[0]

    async def get_stats_key(self, key: str) -> int:
        val = await self.redis.get(key)
        return int(val) if val else 0

    async def invalidate_all_groups(self, group_ids: list[int]) -> None:
        """Bulk invalidate multiple groups via single pipeline."""
        if not group_ids:
            return
        keys = []
        for gid in group_ids:
            keys.extend([self._users_key(gid), self._admins_key(gid), self._loaded_key(gid)])
        await self.redis.delete(*keys)
        logger.debug(f"Bulk cache invalidated: {len(group_ids)} groups")

    async def batch_check_access(self, group_id: int, user_ids: list[int]) -> dict[int, bool]:
        """Check multiple users at once using pipeline. O(N) round-trip but single command batch."""
        if not user_ids:
            return {}
        users_key = self._users_key(group_id)
        pipe = self.redis.pipeline(transaction=False)
        for uid in user_ids:
            pipe.sismember(users_key, uid)
        results = await pipe.execute()
        return {uid: bool(res) for uid, res in zip(user_ids, results)}

    async def get_delete_stats(self, group_id: int) -> int:
        return await self.get_stats_key(f"stats:deleted:{group_id}")

    async def get_total_delete_stats(self) -> int:
        return await self.get_stats_key("stats:deleted:total")

    async def preload_users_batch(self, group_id: int, user_ids: set[int]) -> None:
        """Incrementally add users to an already-warm cache (e.g. after bulk grant)."""
        if not user_ids:
            return
        await self.redis.sadd(self._users_key(group_id), *user_ids)
