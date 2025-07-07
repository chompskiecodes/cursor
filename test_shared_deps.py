import asyncio
import asyncpg
from tools.shared_dependencies import get_db_pool, get_cache_manager, set_db_pool, set_cache_manager
from cache_manager import CacheManager

async def test_shared_deps():
    print("=== Testing Shared Dependencies ===")
    
    # Check initial state
    print(f"Initial db_pool: {get_db_pool()}")
    print(f"Initial cache_manager: {get_cache_manager()}")
    
    # Create pool and cache
    pool = await asyncpg.create_pool('postgresql://postgres.feywathteocancjzdgtf:seS!llyw3rd@aws-0-ap-southeast-2.pooler.supabase.com:5432/postgres')
    cache = CacheManager(pool)
    
    # Set them
    set_db_pool(pool)
    set_cache_manager(cache)
    
    # Check after setting
    print(f"After setting db_pool: {get_db_pool()}")
    print(f"After setting cache_manager: {get_cache_manager()}")
    
    # Test the dependencies
    from tools.dependencies import get_db, get_cache
    
    try:
        db_result = await get_db()
        print(f"get_db() result: {db_result}")
    except Exception as e:
        print(f"get_db() error: {e}")
    
    try:
        cache_result = await get_cache()
        print(f"get_cache() result: {cache_result}")
    except Exception as e:
        print(f"get_cache() error: {e}")
    
    await pool.close()

if __name__ == "__main__":
    asyncio.run(test_shared_deps()) 