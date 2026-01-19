"""Redis client with connection management and demo mode fallback."""

import asyncio
from typing import Any

import redis.asyncio as redis
import structlog

from src.config import get_settings

logger = structlog.get_logger(__name__)


class RedisClient:
    """
    Redis client wrapper with connection pooling and demo mode fallback.
    
    In demo mode (no Redis configured), provides in-memory implementations
    with limited functionality (no cross-instance sharing).
    """

    _instance: "RedisClient | None" = None
    _redis: redis.Redis | None = None
    _in_memory: dict[str, Any] = {}
    _in_memory_expiry: dict[str, float] = {}
    _locks: dict[str, asyncio.Lock] = {}

    def __new__(cls) -> "RedisClient":
        """Singleton pattern for Redis client."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @property
    def is_demo_mode(self) -> bool:
        """Check if running in demo mode (no Redis)."""
        settings = get_settings()
        return settings.is_demo_mode

    async def connect(self) -> None:
        """Initialize Redis connection."""
        if self.is_demo_mode:
            logger.info("Running in demo mode - using in-memory cache")
            return

        settings = get_settings()
        try:
            self._redis = redis.from_url(
                settings.redis_url,
                encoding="utf-8",
                decode_responses=True,
                socket_connect_timeout=5,
                socket_timeout=5,
            )
            await self._redis.ping()
            logger.info("Connected to Redis", url=settings.redis_url.split("@")[-1])
        except Exception as e:
            logger.warning("Failed to connect to Redis, falling back to demo mode", error=str(e))
            self._redis = None

    async def disconnect(self) -> None:
        """Close Redis connection."""
        if self._redis:
            await self._redis.close()
            self._redis = None

    async def get(self, key: str) -> str | None:
        """Get a value from Redis or in-memory cache."""
        if self._redis:
            return await self._redis.get(key)

        # Demo mode - check expiry
        await self._cleanup_expired()
        return self._in_memory.get(key)

    async def set(
        self,
        key: str,
        value: str,
        ex: int | None = None,
        px: int | None = None,
        nx: bool = False,
    ) -> bool:
        """Set a value in Redis or in-memory cache."""
        if self._redis:
            result = await self._redis.set(key, value, ex=ex, px=px, nx=nx)
            return bool(result)

        # Demo mode
        if nx and key in self._in_memory:
            return False

        self._in_memory[key] = value
        if ex:
            import time

            self._in_memory_expiry[key] = time.time() + ex
        elif px:
            import time

            self._in_memory_expiry[key] = time.time() + (px / 1000)
        return True

    async def delete(self, *keys: str) -> int:
        """Delete keys from Redis or in-memory cache."""
        if self._redis:
            return await self._redis.delete(*keys)

        count = 0
        for key in keys:
            if key in self._in_memory:
                del self._in_memory[key]
                self._in_memory_expiry.pop(key, None)
                count += 1
        return count

    async def exists(self, *keys: str) -> int:
        """Check if keys exist."""
        if self._redis:
            return await self._redis.exists(*keys)

        await self._cleanup_expired()
        return sum(1 for k in keys if k in self._in_memory)

    async def expire(self, key: str, seconds: int) -> bool:
        """Set expiration on a key."""
        if self._redis:
            return await self._redis.expire(key, seconds)

        if key in self._in_memory:
            import time

            self._in_memory_expiry[key] = time.time() + seconds
            return True
        return False

    async def ttl(self, key: str) -> int:
        """Get TTL of a key in seconds."""
        if self._redis:
            return await self._redis.ttl(key)

        import time

        expiry = self._in_memory_expiry.get(key)
        if expiry is None:
            return -2 if key not in self._in_memory else -1
        remaining = int(expiry - time.time())
        return max(0, remaining)

    async def incr(self, key: str) -> int:
        """Increment a counter."""
        if self._redis:
            return await self._redis.incr(key)

        value = int(self._in_memory.get(key, 0)) + 1
        self._in_memory[key] = str(value)
        return value

    async def incrby(self, key: str, amount: int) -> int:
        """Increment by a specific amount."""
        if self._redis:
            return await self._redis.incrby(key, amount)

        value = int(self._in_memory.get(key, 0)) + amount
        self._in_memory[key] = str(value)
        return value

    async def incrbyfloat(self, key: str, amount: float) -> float:
        """Increment by a float amount."""
        if self._redis:
            return await self._redis.incrbyfloat(key, amount)

        value = float(self._in_memory.get(key, 0)) + amount
        self._in_memory[key] = str(value)
        return value

    async def hset(self, name: str, key: str | None = None, value: str | None = None, mapping: dict | None = None) -> int:
        """Set hash field(s)."""
        if self._redis:
            return await self._redis.hset(name, key, value, mapping=mapping)

        if name not in self._in_memory:
            self._in_memory[name] = {}
        
        count = 0
        if key is not None and value is not None:
            if key not in self._in_memory[name]:
                count = 1
            self._in_memory[name][key] = value
        if mapping:
            for k, v in mapping.items():
                if k not in self._in_memory[name]:
                    count += 1
                self._in_memory[name][k] = v
        return count

    async def hget(self, name: str, key: str) -> str | None:
        """Get a hash field value."""
        if self._redis:
            return await self._redis.hget(name, key)

        return self._in_memory.get(name, {}).get(key)

    async def hgetall(self, name: str) -> dict[str, str]:
        """Get all hash fields."""
        if self._redis:
            return await self._redis.hgetall(name)

        return dict(self._in_memory.get(name, {}))

    async def hdel(self, name: str, *keys: str) -> int:
        """Delete hash fields."""
        if self._redis:
            return await self._redis.hdel(name, *keys)

        if name not in self._in_memory:
            return 0
        count = 0
        for key in keys:
            if key in self._in_memory[name]:
                del self._in_memory[name][key]
                count += 1
        return count

    async def setbit(self, name: str, offset: int, value: int) -> int:
        """Set a bit at offset."""
        if self._redis:
            return await self._redis.setbit(name, offset, value)

        # Demo mode - simplified bit storage
        if name not in self._in_memory:
            self._in_memory[name] = set()
        
        old_value = 1 if offset in self._in_memory[name] else 0
        if value:
            self._in_memory[name].add(offset)
        else:
            self._in_memory[name].discard(offset)
        return old_value

    async def getbit(self, name: str, offset: int) -> int:
        """Get a bit at offset."""
        if self._redis:
            return await self._redis.getbit(name, offset)

        if name not in self._in_memory:
            return 0
        return 1 if offset in self._in_memory[name] else 0

    async def eval(self, script: str, keys: list[str], args: list[Any]) -> Any:
        """Execute a Lua script."""
        if self._redis:
            return await self._redis.eval(script, len(keys), *keys, *args)

        # Demo mode - can't execute Lua scripts
        raise NotImplementedError("Lua scripts not supported in demo mode")

    async def acquire_lock(
        self,
        name: str,
        timeout: int = 10,
        blocking_timeout: float | None = None,
    ) -> bool:
        """
        Acquire a distributed lock.
        
        In demo mode, uses asyncio.Lock (single-instance only).
        """
        if self._redis:
            # Use Redis SET NX with expiry for distributed lock
            lock_key = f"lock:{name}"
            import time
            import uuid

            lock_value = str(uuid.uuid4())
            end_time = time.time() + (blocking_timeout or 0)

            while True:
                acquired = await self.set(lock_key, lock_value, ex=timeout, nx=True)
                if acquired:
                    return True
                if blocking_timeout is None or time.time() >= end_time:
                    return False
                await asyncio.sleep(0.05)

        # Demo mode - use asyncio.Lock
        if name not in self._locks:
            self._locks[name] = asyncio.Lock()

        try:
            if blocking_timeout:
                await asyncio.wait_for(
                    self._locks[name].acquire(),
                    timeout=blocking_timeout,
                )
            else:
                return self._locks[name].locked() is False and await self._try_acquire_lock(name)
            return True
        except asyncio.TimeoutError:
            return False

    async def _try_acquire_lock(self, name: str) -> bool:
        """Try to acquire a lock without blocking."""
        if name not in self._locks:
            self._locks[name] = asyncio.Lock()
        
        if not self._locks[name].locked():
            await self._locks[name].acquire()
            return True
        return False

    async def release_lock(self, name: str) -> bool:
        """Release a distributed lock."""
        if self._redis:
            lock_key = f"lock:{name}"
            result = await self.delete(lock_key)
            return result > 0

        # Demo mode
        if name in self._locks and self._locks[name].locked():
            self._locks[name].release()
            return True
        return False

    async def zadd(
        self,
        name: str,
        mapping: dict[str, float],
        nx: bool = False,
        xx: bool = False,
        gt: bool = False,
        lt: bool = False,
    ) -> int:
        """Add members to a sorted set."""
        if self._redis:
            return await self._redis.zadd(name, mapping, nx=nx, xx=xx, gt=gt, lt=lt)

        # Demo mode - simplified sorted set
        if name not in self._in_memory:
            self._in_memory[name] = {}
        
        added = 0
        for member, score in mapping.items():
            if nx and member in self._in_memory[name]:
                continue
            if xx and member not in self._in_memory[name]:
                continue
            if member not in self._in_memory[name]:
                added += 1
            self._in_memory[name][member] = score
        return added

    async def zremrangebyscore(self, name: str, min_score: float, max_score: float) -> int:
        """Remove members with scores in range."""
        if self._redis:
            return await self._redis.zremrangebyscore(name, min_score, max_score)

        if name not in self._in_memory:
            return 0
        
        to_remove = [
            member
            for member, score in self._in_memory[name].items()
            if min_score <= score <= max_score
        ]
        for member in to_remove:
            del self._in_memory[name][member]
        return len(to_remove)

    async def zcount(self, name: str, min_score: float | str, max_score: float | str) -> int:
        """Count members with scores in range."""
        if self._redis:
            return await self._redis.zcount(name, min_score, max_score)

        if name not in self._in_memory:
            return 0
        
        min_val = float("-inf") if min_score == "-inf" else float(min_score)
        max_val = float("inf") if max_score == "+inf" else float(max_score)
        
        return sum(
            1 for score in self._in_memory[name].values()
            if min_val <= score <= max_val
        )

    async def pipeline(self) -> "RedisPipeline":
        """Create a pipeline for batch operations."""
        return RedisPipeline(self)

    async def _cleanup_expired(self) -> None:
        """Clean up expired keys in demo mode."""
        import time

        now = time.time()
        expired = [k for k, exp in self._in_memory_expiry.items() if exp < now]
        for key in expired:
            self._in_memory.pop(key, None)
            self._in_memory_expiry.pop(key, None)

    def clear_demo_cache(self) -> None:
        """Clear all in-memory data (for testing)."""
        self._in_memory.clear()
        self._in_memory_expiry.clear()


class RedisPipeline:
    """Pipeline wrapper for batch Redis operations."""

    def __init__(self, client: RedisClient) -> None:
        self._client = client
        self._commands: list[tuple[str, tuple, dict]] = []

    def set(self, key: str, value: str, **kwargs: Any) -> "RedisPipeline":
        """Queue a SET command."""
        self._commands.append(("set", (key, value), kwargs))
        return self

    def get(self, key: str) -> "RedisPipeline":
        """Queue a GET command."""
        self._commands.append(("get", (key,), {}))
        return self

    def incr(self, key: str) -> "RedisPipeline":
        """Queue an INCR command."""
        self._commands.append(("incr", (key,), {}))
        return self

    def expire(self, key: str, seconds: int) -> "RedisPipeline":
        """Queue an EXPIRE command."""
        self._commands.append(("expire", (key, seconds), {}))
        return self

    async def execute(self) -> list[Any]:
        """Execute all queued commands."""
        if self._client._redis:
            async with self._client._redis.pipeline(transaction=True) as pipe:
                for cmd, args, kwargs in self._commands:
                    getattr(pipe, cmd)(*args, **kwargs)
                return await pipe.execute()

        # Demo mode - execute sequentially
        results = []
        for cmd, args, kwargs in self._commands:
            method = getattr(self._client, cmd)
            result = await method(*args, **kwargs)
            results.append(result)
        return results


# Global instance
redis_client = RedisClient()


async def get_redis() -> RedisClient:
    """Dependency to get Redis client."""
    return redis_client
