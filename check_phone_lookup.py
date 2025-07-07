import asyncio
import asyncpg
import os
from dotenv import load_dotenv

load_dotenv()

async def check_phone_lookup():
    pool = await asyncpg.create_pool(os.getenv('DATABASE_URL'))
    
    async with pool.acquire() as conn:
        # Check phone_lookup table
        print("=== Phone Lookup Table ===")
        phone_lookups = await conn.fetch("""
            SELECT 
                pl.phone_normalized,
                pl.clinic_id,
                c.clinic_name
            FROM phone_lookup pl
            JOIN clinics c ON pl.clinic_id = c.clinic_id
            ORDER BY pl.phone_normalized
        """)
        
        for lookup in phone_lookups:
            print(f"  Normalized: {lookup['phone_normalized']} -> {lookup['clinic_name']} (ID: {lookup['clinic_id']})")
        
        # Check what the test number would normalize to
        test_number = "+61412345678"
        print(f"\n=== Test Number Normalization ===")
        print(f"Original: {test_number}")
        
        # Check if there's a normalize_phone function we can call
        try:
            # Try to import and use the normalize_phone function
            from database import normalize_phone
            normalized = normalize_phone(test_number)
            print(f"Normalized: {normalized}")
            
            # Check if this normalized number exists in phone_lookup
            exists = await conn.fetchrow("""
                SELECT pl.phone_normalized, c.clinic_name 
                FROM phone_lookup pl
                JOIN clinics c ON pl.clinic_id = c.clinic_id
                WHERE pl.phone_normalized = $1
            """, normalized)
            
            if exists:
                print(f"  ✓ Found in phone_lookup: {exists['clinic_name']}")
            else:
                print(f"  ✗ NOT found in phone_lookup")
                
        except ImportError:
            print("Could not import normalize_phone function")
        
        # Show all clinics
        print(f"\n=== All Clinics ===")
        clinics = await conn.fetch("SELECT clinic_id, clinic_name FROM clinics ORDER BY clinic_name")
        for clinic in clinics:
            print(f"  {clinic['clinic_name']} (ID: {clinic['clinic_id']})")
    
    await pool.close()

if __name__ == "__main__":
    asyncio.run(check_phone_lookup()) 