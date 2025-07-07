import asyncio
import asyncpg
from tools.location_router import resolve_location
from models import LocationResolverRequest

async def test_location_webhook():
    # Connect to database
    pool = await asyncpg.create_pool('postgresql://postgres.feywathteocancjzdgtf:seS!llyw3rd@aws-0-ap-southeast-2.pooler.supabase.com:5432/postgres')
    
    # Create request
    request = LocationResolverRequest(
        locationQuery="City Clinic",
        sessionId="test_simple",
        dialedNumber="0478621276",
        callerPhone="0412345678"
    )
    
    # Mock dependencies
    class MockBackgroundTasks:
        def add_task(self, func, *args, **kwargs):
            pass
    
    class MockAuthenticated:
        pass
    
    try:
        # Test the webhook function directly
        from tools.dependencies import get_db, get_cache
        from cache_manager import CacheManager
        
        # Set up dependencies
        cache = CacheManager(pool)
        
        # Mock the dependency functions
        async def mock_get_db():
            return pool
        
        async def mock_get_cache():
            return cache
        
        # Replace the dependency functions
        import tools.dependencies
        tools.dependencies.get_db = mock_get_db
        tools.dependencies.get_cache = mock_get_cache
        
        # Test the webhook
        from fastapi import BackgroundTasks
        background_tasks = BackgroundTasks()
        
        result = await resolve_location(request, background_tasks, MockAuthenticated())
        print(f"Result: {result}")
        
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
    
    await pool.close()

if __name__ == "__main__":
    asyncio.run(test_location_webhook()) 