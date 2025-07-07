import asyncio
import asyncpg
import requests
import json

async def test_location_webhook_direct():
    print("=== Testing Location Resolver Webhook Directly ===")
    
    # Set up database pool and cache
    pool = await asyncpg.create_pool('postgresql://postgres.feywathteocancjzdgtf:seS!llyw3rd@aws-0-ap-southeast-2.pooler.supabase.com:5432/postgres')
    
    # Set up shared dependencies manually
    from tools.shared_dependencies import set_db_pool, set_cache_manager
    from cache_manager import CacheManager
    
    cache = CacheManager(pool)
    set_db_pool(pool)
    set_cache_manager(cache)
    
    print("Dependencies set up successfully")
    
    # Test the webhook
    url = "http://localhost:8000/location-resolver"
    headers = {
        "X-API-Key": "development-key",
        "Content-Type": "application/json"
    }
    payload = {
        "locationQuery": "City Clinic",
        "sessionId": "test_direct",
        "dialedNumber": "0478621276",
        "callerPhone": "0412345678"
    }
    
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=30)
        print(f"Status: {response.status_code}")
        print(f"Response: {response.text}")
        
        if response.status_code == 200:
            result = response.json()
            if result.get('success'):
                print("SUCCESS: Location resolver worked!")
            else:
                print(f"FAILED: {result.get('message')}")
        else:
            print(f"HTTP ERROR: {response.status_code}")
            
    except Exception as e:
        print(f"Exception: {e}")
    
    await pool.close()

if __name__ == "__main__":
    asyncio.run(test_location_webhook_direct()) 