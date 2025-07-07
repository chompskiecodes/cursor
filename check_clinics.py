import asyncio
import asyncpg
import os
from dotenv import load_dotenv

load_dotenv()

async def check_clinics():
    pool = await asyncpg.create_pool(os.getenv('DATABASE_URL'))
    
    async with pool.acquire() as conn:
        # Check all clinics
        print("=== All Clinics ===")
        clinics = await conn.fetch("""
            SELECT 
                clinic_id,
                clinic_name,
                dialed_number,
                cliniko_api_key,
                cliniko_shard,
                contact_email
            FROM clinics 
            ORDER BY clinic_name
        """)
        
        for clinic in clinics:
            print(f"  {clinic['clinic_name']} (ID: {clinic['clinic_id']})")
            print(f"    Dialed Number: {clinic['dialed_number']}")
            print(f"    Cliniko Shard: {clinic['cliniko_shard']}")
            print(f"    Contact Email: {clinic['contact_email']}")
            print()
        
        # Check if the test dialed number exists
        test_dialed = "+61412345678"
        test_clinic = await conn.fetchrow("""
            SELECT clinic_id, clinic_name, dialed_number 
            FROM clinics 
            WHERE dialed_number = $1
        """, test_dialed)
        
        print(f"=== Test Dialed Number Check ===")
        print(f"Looking for: {test_dialed}")
        if test_clinic:
            print(f"  Found: {test_clinic['clinic_name']} (ID: {test_clinic['clinic_id']})")
        else:
            print(f"  NOT FOUND: No clinic with dialed number {test_dialed}")
            
            # Show what dialed numbers are available
            available_numbers = await conn.fetch("SELECT dialed_number FROM clinics WHERE dialed_number IS NOT NULL")
            if available_numbers:
                print(f"  Available dialed numbers:")
                for row in available_numbers:
                    print(f"    {row['dialed_number']}")
            else:
                print("  No dialed numbers configured!")
    
    await pool.close()

if __name__ == "__main__":
    asyncio.run(check_clinics()) 