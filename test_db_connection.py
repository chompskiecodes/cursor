import asyncio
import asyncpg
from datetime import datetime

# Hardcoded Supabase DB URL
DB_URL = "postgresql://postgres.feywathteocancjzdgtf:seS!llyw3rd@aws-0-ap-southeast-2.pooler.supabase.com:5432/postgres"

async def test_connection():
    """Test database connection with different parameters"""
    db_url = DB_URL
    print(f"Testing connection to: {db_url.split('@')[1] if '@' in db_url else 'unknown'}")
    
    # Test 1: Basic connection without SSL
    print("\n1. Testing basic connection...")
    try:
        conn = await asyncpg.connect(db_url, timeout=10)
        await conn.close()
        print("✅ Basic connection successful")
    except Exception as e:
        print(f"❌ Basic connection failed: {e}")
    
    # Test 2: Connection with SSL require
    print("\n2. Testing connection with SSL require...")
    try:
        conn = await asyncpg.connect(db_url, ssl='require', timeout=10)
        await conn.close()
        print("✅ SSL connection successful")
    except Exception as e:
        print(f"❌ SSL connection failed: {e}")
    
    # Test 3: Connection with SSL allow
    print("\n3. Testing connection with SSL allow...")
    try:
        conn = await asyncpg.connect(db_url, ssl='allow', timeout=10)
        await conn.close()
        print("✅ SSL allow connection successful")
    except Exception as e:
        print(f"❌ SSL allow connection failed: {e}")
    
    # Test 4: Connection with no SSL
    print("\n4. Testing connection with no SSL...")
    try:
        conn = await asyncpg.connect(db_url, ssl=False, timeout=10)
        await conn.close()
        print("✅ No SSL connection successful")
    except Exception as e:
        print(f"❌ No SSL connection failed: {e}")
    
    # Test 5: Simple query
    print("\n5. Testing simple query...")
    try:
        conn = await asyncpg.connect(db_url, ssl='require', timeout=10)
        result = await conn.fetchval("SELECT NOW()")
        print(f"✅ Query successful: {result}")
        await conn.close()
    except Exception as e:
        print(f"❌ Query failed: {e}")

if __name__ == "__main__":
    asyncio.run(test_connection()) 