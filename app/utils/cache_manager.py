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

    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics"""
        if not self.redis_client:
            return {
                "status": "disabled",
                "message": "Redis not connected"
            }
        
        try:
            # Get Redis info
            info = self.redis_client.info()
            
            # Get all cache keys
            cache_keys = self.redis_client.keys("traffic_flow:*") + self.redis_client.keys("route:*")
            
            # Calculate memory usage for cache keys
            total_memory = 0
            for key in cache_keys:
                try:
                    total_memory += self.redis_client.memory_usage(key) or 0
                except:
                    pass
            
            return {
                "status": "active",
                "total_keys": len(cache_keys),
                "traffic_flow_keys": len(self.redis_client.keys("traffic_flow:*")),
                "route_keys": len(self.redis_client.keys("route:*")),
                "memory_used_bytes": total_memory,
                "memory_used_mb": round(total_memory / (1024 * 1024), 2),
                "redis_version": info.get("redis_version", "unknown"),
                "uptime_seconds": info.get("uptime_in_seconds", 0),
                "connected_clients": info.get("connected_clients", 0),
                "used_memory_human": info.get("used_memory_human", "unknown"),
                "timestamp": datetime.now().isoformat()
            }
        except redis.RedisError as e:
            logger.error(f"Error getting cache stats: {e}")
            return {
                "status": "error",
                "message": str(e)
            }
    
    def clear_expired(self, minutes: int = 60) -> int:
        """Clear cache entries older than specified minutes (for manual cleanup)"""
        if not self.redis_client:
            return 0
        
        try:
            # Get all cache keys
            all_keys = self.redis_client.keys("traffic_flow:*") + self.redis_client.keys("route:*")
            
            cleared_count = 0
            cutoff_time = datetime.now() - timedelta(minutes=minutes)
            
            for key in all_keys:
                try:
                    # Get TTL (time to live) in seconds
                    ttl = self.redis_client.ttl(key)
                    
                    # If TTL is -1 (no expiry) or expired, delete it
                    # Or if the key is very old (based on TTL)
                    if ttl == -1 or ttl <= 0:
                        self.redis_client.delete(key)
                        cleared_count += 1
                except:
                    pass
            
            logger.info(f"Cleared {cleared_count} cache entries")
            return cleared_count
            
        except redis.RedisError as e:
            logger.error(f"Error clearing cache: {e}")
            return 0

    @staticmethod
    def generate_cache_key(prefix: str, **kwargs) -> str:
        """Generate cache key from parameters"""
        key_parts = [prefix]
        for k, v in sorted(kwargs.items()):
            key_parts.append(f"{k}:{v}")
        return ":".join(key_parts)
