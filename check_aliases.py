import asyncio
import asyncpg

async def check_aliases():
    conn = await asyncpg.connect('postgresql://postgres.feywathteocancjzdgtf:seS!llyw3rd@aws-0-ap-southeast-2.pooler.supabase.com:5432/postgres')
    
    # Check if location_aliases table exists
    tables = await conn.fetch("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' AND table_name LIKE '%alias%'")
    print("Alias tables:", [t['table_name'] for t in tables])
    
    # Check if location_aliases table exists specifically
    try:
        aliases = await conn.fetch("SELECT * FROM location_aliases LIMIT 5")
        print(f"Location aliases ({len(aliases)}):")
        for a in aliases:
            print(f"  {a}")
    except Exception as e:
        print(f"Location aliases table doesn't exist: {e}")
    
    await conn.close()

if __name__ == "__main__":
    asyncio.run(check_aliases()) 