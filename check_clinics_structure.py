import asyncio
import asyncpg
import os
from dotenv import load_dotenv

load_dotenv()

async def check_clinics_structure():
    pool = await asyncpg.create_pool(os.getenv('DATABASE_URL'))
    
    async with pool.acquire() as conn:
        # Check clinics table structure
        print("=== Clinics Table Structure ===")
        columns = await conn.fetch("""
            SELECT column_name, data_type 
            FROM information_schema.columns 
            WHERE table_name = 'clinics' 
            ORDER BY ordinal_position
        """)
        
        for col in columns:
            print(f"  {col['column_name']}: {col['data_type']}")
        
        # Check clinics data
        print("\n=== Clinics Data ===")
        clinics = await conn.fetch("SELECT * FROM clinics")
        
        for clinic in clinics:
            print(f"  Clinic: {clinic}")
    
    await pool.close()

if __name__ == "__main__":
    asyncio.run(check_clinics_structure()) 