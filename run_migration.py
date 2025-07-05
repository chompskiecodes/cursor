import asyncio
import asyncpg

# Hardcoded Supabase DB URL
DB_URL = "postgresql://postgres.feywathteocancjzdgtf:seS!llyw3rd@aws-0-ap-southeast-2.pooler.supabase.com:5432/postgres"

async def run_migration():
    """Run the schema migration script"""
    print("Connecting to database...")
    conn = await asyncpg.connect(DB_URL, ssl='require')
    
    try:
        print("Reading migration script...")
        with open('schema_migration.sql', 'r') as f:
            sql = f.read()
        
        print("Executing migration...")
        result = await conn.execute(sql)
        print("✅ Migration completed successfully!")
        
    except Exception as e:
        print(f"❌ Migration failed: {e}")
        raise
    finally:
        await conn.close()

if __name__ == "__main__":
    asyncio.run(run_migration()) 