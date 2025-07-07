import asyncio
import asyncpg
from location_resolver import LocationResolver, get_clinic_locations_cached
from models import LocationResolverRequest
from cache_manager import CacheManager

async def debug_location_resolver():
    # Connect to database
    pool = await asyncpg.create_pool('postgresql://postgres.feywathteocancjzdgtf:seS!llyw3rd@aws-0-ap-southeast-2.pooler.supabase.com:5432/postgres')
    cache = CacheManager(pool)
    
    # Get clinic ID
    clinic = await pool.fetchrow("SELECT clinic_id FROM clinics WHERE phone_number = '0478621276'")
    clinic_id = clinic['clinic_id']
    print(f"Clinic ID: {clinic_id}")
    
    # Test getting locations
    print("\n=== Testing get_clinic_locations_cached ===")
    try:
        locations = await get_clinic_locations_cached(clinic_id, pool, cache)
        print(f"Found {len(locations)} locations:")
        for loc in locations:
            print(f"  {loc['business_id']}: {loc['business_name']} (primary: {loc['is_primary']})")
            print(f"    Aliases: {loc.get('aliases', [])}")
    except Exception as e:
        print(f"Error getting locations: {e}")
        import traceback
        traceback.print_exc()
    
    # Test location resolver
    print("\n=== Testing LocationResolver ===")
    try:
        resolver = LocationResolver(pool, cache)
        request = LocationResolverRequest(
            locationQuery="City Clinic",
            sessionId="test_debug",
            dialedNumber="0478621276",
            callerPhone="0412345678"
        )
        
        response = await resolver.resolve_location(request, clinic_id)
        print(f"Response: {response}")
    except Exception as e:
        print(f"Error in location resolver: {e}")
        import traceback
        traceback.print_exc()
    
    await pool.close()

if __name__ == "__main__":
    asyncio.run(debug_location_resolver()) 