#!/usr/bin/env python3
"""Check practitioner-business relationships"""

import asyncio
import asyncpg
import os
from dotenv import load_dotenv

load_dotenv()

async def check_practitioner_businesses():
    pool = await asyncpg.create_pool(os.getenv('DATABASE_URL'))
    
    async with pool.acquire() as conn:
        # Check practitioner-business assignments
        rows = await conn.fetch("""
            SELECT 
                pb.practitioner_id, 
                pb.business_id, 
                p.first_name || ' ' || p.last_name as practitioner_name, 
                b.business_name 
            FROM practitioner_businesses pb 
            JOIN practitioners p ON pb.practitioner_id = p.practitioner_id 
            JOIN businesses b ON pb.business_id = b.business_id 
            ORDER BY b.business_name, p.first_name
        """)
        
        print("=== Practitioner-Business Assignments ===")
        if rows:
            for row in rows:
                print(f"  {row['practitioner_name']} -> {row['business_name']} (ID: {row['business_id']})")
        else:
            print("  No practitioner-business assignments found!")
        
        # Check all businesses
        print("\n=== All Businesses ===")
        businesses = await conn.fetch("SELECT business_id, business_name FROM businesses ORDER BY business_name")
        for business in businesses:
            print(f"  {business['business_name']} (ID: {business['business_id']})")
        
        # Check all practitioners
        print("\n=== All Practitioners ===")
        practitioners = await conn.fetch("SELECT practitioner_id, first_name || ' ' || last_name as name FROM practitioners ORDER BY first_name")
        for practitioner in practitioners:
            print(f"  {practitioner['name']} (ID: {practitioner['practitioner_id']})")
    
    await pool.close()

if __name__ == "__main__":
    asyncio.run(check_practitioner_businesses()) 