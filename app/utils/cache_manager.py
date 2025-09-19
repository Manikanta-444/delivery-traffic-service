import redis
import json
import os
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
import logging

logger = logging.getLogger(__name__)


class CacheManager:
    def __init__(self):
        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
        try:
            self.redis_client = redis.from_url(redis_url, decode_responses=True)
            # Test connection
            self.redis_client.ping()
            logger.info("Redis connection established")
        except (redis.ConnectionError, redis.RedisError) as e:
            logger.warning(f"Redis connection failed: {e}. Falling back to no caching.")
            self.redis_client = None

    def get(self, key: str) -> Optional[Dict]:
        """Get value from cache"""
        if not self.redis_client:
            return None

        try:
            cached_data = self.redis_client.get(key)
            if cached_data:
                return json.loads(cached_data)
        except (redis.RedisError, json.JSONDecodeError) as e:
            logger.error(f"Cache get error: {e}")

        return None

    def set(self, key: str, value: Dict, ttl_minutes: int = 5) -> bool:
        """Set value in cache with TTL"""
        if not self.redis_client:
            return False

        try:
            ttl_seconds = ttl_minutes * 60
            self.redis_client.setex(key, ttl_seconds, json.dumps(value, default=str))
            return True
        except (redis.RedisError, json.JSONEncodeError) as e:
            logger.error(f"Cache set error: {e}")
            return False

    def delete(self, key: str) -> bool:
        """Delete key from cache"""
        if not self.redis_client:
            return False

        try:
            self.redis_client.delete(key)
            return True
        except redis.RedisError as e:
            logger.error(f"Cache delete error: {e}")
            return False

    @staticmethod
    def generate_cache_key(prefix: str, **kwargs) -> str:
        """Generate cache key from parameters"""
        key_parts = [prefix]
        for k, v in sorted(kwargs.items()):
            key_parts.append(f"{k}:{v}")
        return ":".join(key_parts)
