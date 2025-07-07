import asyncio
import asyncpg
from location_resolver import LocationResolver
from models import LocationResolverRequest
from cache_manager import CacheManager

async def test_core_location_resolver():
    print("=== Testing Core Location Resolver Logic ===")
    
    # Set up database and cache
    pool = await asyncpg.create_pool('postgresql://postgres.feywathteocancjzdgtf:seS!llyw3rd@aws-0-ap-southeast-2.pooler.supabase.com:5432/postgres')
    cache = CacheManager(pool)
    
    # Get clinic ID
    clinic = await pool.fetchrow("SELECT clinic_id FROM clinics WHERE phone_number = '0478621276'")
    clinic_id = clinic['clinic_id']
    print(f"Clinic ID: {clinic_id}")
    
    # Create request
    request = LocationResolverRequest(
        locationQuery="City Clinic",
        sessionId="test_core",
        dialedNumber="0478621276",
        callerPhone="0412345678"
    )
    
    # Test the resolver directly
    try:
        resolver = LocationResolver(pool, cache)
        response = await resolver.resolve_location(request, clinic_id)
        print(f"SUCCESS: {response}")
    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
    
    await pool.close()

if __name__ == "__main__":
    asyncio.run(test_core_location_resolver()) 