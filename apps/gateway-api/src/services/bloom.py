"""
Bloom Filter implementation for negative caching.

Uses Redis bitmaps for distributed bloom filter storage.
Optimized for tracking 404 responses to reduce upstream calls.
"""

import math
from typing import TYPE_CHECKING

import mmh3
import structlog

from src.services.redis_client import RedisClient, redis_client

if TYPE_CHECKING:
    pass

logger = structlog.get_logger(__name__)


class BloomFilter:
    """
    Distributed Bloom Filter using Redis bitmaps.
    
    A probabilistic data structure that can tell you:
    - Definitely NOT in the set (no false negatives)
    - PROBABLY in the set (possible false positives)
    
    Used for negative caching: if a path returned 404, remember it
    to short-circuit future requests without hitting upstream.
    
    Configuration:
    - expected_items: Expected number of items to store
    - false_positive_rate: Acceptable false positive rate (0.01 = 1%)
    
    The filter automatically calculates:
    - m: Number of bits needed
    - k: Number of hash functions
    """

    def __init__(
        self,
        redis: RedisClient | None = None,
        name: str = "bloom:404",
        expected_items: int = 10000,
        false_positive_rate: float = 0.01,
    ) -> None:
        """
        Initialize bloom filter.
        
        Args:
            redis: Redis client instance
            name: Redis key name for the bitmap
            expected_items: Expected number of items to track
            false_positive_rate: Target false positive rate
        """
        self._redis = redis or redis_client
        self._name = name
        self._expected_items = expected_items
        self._fp_rate = false_positive_rate

        # Calculate optimal parameters
        self._m = self._calculate_m(expected_items, false_positive_rate)
        self._k = self._calculate_k(self._m, expected_items)

        logger.info(
            "Bloom filter initialized",
            name=name,
            expected_items=expected_items,
            fp_rate=false_positive_rate,
            bits=self._m,
            hash_functions=self._k,
        )

    @staticmethod
    def _calculate_m(n: int, p: float) -> int:
        """
        Calculate optimal number of bits.
        
        m = -(n * ln(p)) / (ln(2)^2)
        
        Args:
            n: Expected number of items
            p: False positive probability
        
        Returns:
            Number of bits needed
        """
        if n <= 0:
            return 1000
        if p <= 0 or p >= 1:
            p = 0.01

        m = -(n * math.log(p)) / (math.log(2) ** 2)
        return int(math.ceil(m))

    @staticmethod
    def _calculate_k(m: int, n: int) -> int:
        """
        Calculate optimal number of hash functions.
        
        k = (m/n) * ln(2)
        
        Args:
            m: Number of bits
            n: Expected number of items
        
        Returns:
            Number of hash functions
        """
        if n <= 0:
            return 3
        k = (m / n) * math.log(2)
        return max(1, int(math.ceil(k)))

    def _get_bit_positions(self, item: str) -> list[int]:
        """
        Get bit positions for an item using k hash functions.
        
        Uses double hashing with MurmurHash3:
        h(i) = (h1 + i * h2) mod m
        
        Args:
            item: The item to hash
        
        Returns:
            List of bit positions to set/check
        """
        # Get two independent hash values using mmh3
        h1 = mmh3.hash(item, seed=0, signed=False)
        h2 = mmh3.hash(item, seed=h1, signed=False)

        positions = []
        for i in range(self._k):
            # Double hashing: h(i) = (h1 + i * h2) mod m
            pos = (h1 + i * h2) % self._m
            positions.append(pos)

        return positions

    async def add(self, item: str) -> bool:
        """
        Add an item to the bloom filter.
        
        Args:
            item: The item to add (e.g., a URL path)
        
        Returns:
            True if the item was newly added, False if it might have existed
        """
        positions = self._get_bit_positions(item)
        was_new = False

        for pos in positions:
            old_val = await self._redis.setbit(self._name, pos, 1)
            if old_val == 0:
                was_new = True

        logger.debug("Bloom filter add", item=item, positions=positions, was_new=was_new)
        return was_new

    async def contains(self, item: str) -> bool:
        """
        Check if an item might be in the bloom filter.
        
        Returns True if ALL bits are set (might be in set).
        Returns False if ANY bit is not set (definitely not in set).
        
        Args:
            item: The item to check
        
        Returns:
            True if probably in set, False if definitely not
        """
        positions = self._get_bit_positions(item)

        for pos in positions:
            if await self._redis.getbit(self._name, pos) == 0:
                return False

        return True

    async def might_contain(self, item: str) -> tuple[bool, float]:
        """
        Check if item might be in filter with probability estimate.
        
        Args:
            item: The item to check
        
        Returns:
            Tuple of (might_contain, estimated_probability)
        """
        contains = await self.contains(item)
        if not contains:
            return False, 0.0

        # Estimate probability this is a true positive
        # Based on the theoretical false positive rate
        return True, 1.0 - self._fp_rate

    async def clear(self) -> bool:
        """Clear the bloom filter."""
        result = await self._redis.delete(self._name)
        logger.info("Bloom filter cleared", name=self._name)
        return result > 0

    @property
    def bit_size(self) -> int:
        """Get the number of bits in the filter."""
        return self._m

    @property
    def hash_count(self) -> int:
        """Get the number of hash functions."""
        return self._k

    @property
    def expected_items(self) -> int:
        """Get the expected number of items."""
        return self._expected_items

    @property
    def false_positive_rate(self) -> float:
        """Get the configured false positive rate."""
        return self._fp_rate

    def get_stats(self) -> dict:
        """Get bloom filter statistics."""
        return {
            "name": self._name,
            "bit_size": self._m,
            "hash_functions": self._k,
            "expected_items": self._expected_items,
            "false_positive_rate": self._fp_rate,
            "memory_bytes": math.ceil(self._m / 8),
        }


class NegativeCacheManager:
    """
    Manager for negative caching using bloom filters.
    
    Tracks paths that returned 404 to avoid unnecessary upstream calls.
    Includes automatic expiration and route-specific filters.
    """

    def __init__(
        self,
        redis: RedisClient | None = None,
        default_expected_items: int = 10000,
        default_fp_rate: float = 0.01,
    ) -> None:
        self._redis = redis or redis_client
        self._default_expected = default_expected_items
        self._default_fp_rate = default_fp_rate
        self._filters: dict[str, BloomFilter] = {}

    def _get_filter(self, route_name: str) -> BloomFilter:
        """Get or create a bloom filter for a route."""
        if route_name not in self._filters:
            self._filters[route_name] = BloomFilter(
                redis=self._redis,
                name=f"bloom:404:{route_name}",
                expected_items=self._default_expected,
                false_positive_rate=self._default_fp_rate,
            )
        return self._filters[route_name]

    async def record_404(self, route_name: str, path: str) -> None:
        """
        Record a 404 response for a path.
        
        Args:
            route_name: Name of the route
            path: The path that returned 404
        """
        bloom = self._get_filter(route_name)
        await bloom.add(path)
        logger.debug("Recorded 404 in bloom filter", route=route_name, path=path)

    async def is_likely_404(self, route_name: str, path: str) -> bool:
        """
        Check if a path is likely to return 404.
        
        Use this to short-circuit requests without hitting upstream.
        
        Args:
            route_name: Name of the route
            path: The path to check
        
        Returns:
            True if the path probably returned 404 before
        """
        bloom = self._get_filter(route_name)
        return await bloom.contains(path)

    async def clear_route(self, route_name: str) -> bool:
        """Clear the bloom filter for a specific route."""
        bloom = self._get_filter(route_name)
        return await bloom.clear()

    async def clear_all(self) -> int:
        """Clear all bloom filters."""
        count = 0
        for name, bloom in self._filters.items():
            if await bloom.clear():
                count += 1
        self._filters.clear()
        return count

    def get_all_stats(self) -> dict[str, dict]:
        """Get statistics for all filters."""
        return {name: bloom.get_stats() for name, bloom in self._filters.items()}


# Global instances
bloom_filter = BloomFilter()
negative_cache = NegativeCacheManager()


async def get_bloom_filter() -> BloomFilter:
    """Dependency to get bloom filter."""
    return bloom_filter


async def get_negative_cache() -> NegativeCacheManager:
    """Dependency to get negative cache manager."""
    return negative_cache
