import asyncpg
from typing import Optional, Any

# Global instances
db_pool: Optional[asyncpg.Pool] = None
cache_manager: Optional[Any] = None  # Use Any to avoid importing CacheManager

def set_db_pool(pool: asyncpg.Pool):
    """Set the database pool (called from main.py)"""
    global db_pool
    db_pool = pool

def set_cache_manager(cache: Any):
    """Set the cache manager (called from main.py)"""
    global cache_manager
    cache_manager = cache

def get_db_pool() -> Optional[asyncpg.Pool]:
    """Get the database pool"""
    return db_pool

def get_cache_manager() -> Optional[Any]:
    """Get the cache manager"""
    return cache_manager 