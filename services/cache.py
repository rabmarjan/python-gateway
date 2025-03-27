import pickle
import time
from typing import Any, Dict, Optional
import redis.asyncio as redis
import asyncio

class CacheManager:
    """Enhanced cache service for API responses with performance optimizations"""
    def __init__(self, redis_client: redis.Redis, local_ttl: int = 10, max_local_cache_size: int = 1000):
        self.redis = redis_client
        self.local_cache: Dict[str, tuple] = {}  # (data, expiry)
        self.local_ttl = local_ttl
        self.max_local_cache_size = max_local_cache_size
        self.cache_lock = asyncio.Lock()
    
    async def _prune_local_cache(self):
        """Prune local cache if it exceeds max size"""
        now = time.time()
        # Remove expired entries
        self.local_cache = {
            k: v for k, v in self.local_cache.items() 
            if v[1] > now
        }
        
        # If still over max size, remove oldest entries
        if len(self.local_cache) > self.max_local_cache_size:
            sorted_keys = sorted(self.local_cache, key=lambda k: self.local_cache[k][1])
            for key in sorted_keys[:len(self.local_cache) - self.max_local_cache_size]:
                del self.local_cache[key]

    async def get(self, key: str) -> Optional[Any]:
        """Optimized get method with lock and efficient cache checking"""
        async with self.cache_lock:
            now = time.time()
            
            # Check local cache first
            if key in self.local_cache and self.local_cache[key][1] > now:
                return self.local_cache[key][0]
        
        # Fall back to Redis with minimal locking
        try:
            cached_data = await self.redis.get(key)
            if cached_data:
                data = pickle.loads(cached_data)
                
                # Update local cache thread-safely
                async with self.cache_lock:
                    self.local_cache[key] = (data, now + self.local_ttl)
                    await self._prune_local_cache()
                
                return data
        except Exception as e:
            print(f"Cache retrieval error: {e}")
        
        return None

    async def set(self, key: str, value: Any, ttl: int) -> None:
        """Enhanced set method with atomic operations"""
        async with self.cache_lock:
            serialized_data = pickle.dumps(value)
            
            # Concurrent Redis and local cache update
            await asyncio.gather(
                self.redis.setex(key, ttl, serialized_data),
                self._update_local_cache(key, value, ttl)
            )

    async def _update_local_cache(self, key: str, value: Any, ttl: int):
        """Internal method to update local cache"""
        now = time.time()
        self.local_cache[key] = (value, now + min(ttl, self.local_ttl))
        await self._prune_local_cache()

    async def invalidate(self, pattern: str) -> None:
        """Enhanced invalidation with atomic operations"""
        async with self.cache_lock:
            # Remove local cache entries
            keys_to_remove = [k for k in self.local_cache if pattern in k]
            for k in keys_to_remove:
                del self.local_cache[k]
            
            # Clear Redis cache
            keys = await self.redis.keys(f"*{pattern}*")
            if keys:
                await self.redis.delete(*keys)