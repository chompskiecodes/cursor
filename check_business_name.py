import asyncio
import asyncpg
import os

async def check_business_name():
    pool = await asyncpg.create_pool(os.getenv('DATABASE_URL'))
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            'SELECT business_id, business_name FROM businesses WHERE business_id = $1', 
            '1701928805762869230'
        )
        if row:
            print(f"Business ID: {row['business_id']}")
            print(f"Business Name: {row['business_name']}")
        else:
            print("Business not found")
    await pool.close()

if __name__ == "__main__":
    asyncio.run(check_business_name()) 