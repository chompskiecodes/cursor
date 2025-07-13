#!/usr/bin/env python3
"""
Debug script to check database relationships for Brendan Smith.
"""

import asyncio
import asyncpg
from dotenv import load_dotenv
import os

# Load environment variables
load_dotenv()

async def check_brendan_smith_data():
    """Check Brendan Smith's business and service relationships"""
    
    # Connect to database
    pool = await asyncpg.create_pool(os.getenv("DATABASE_URL"))
    
    async with pool.acquire() as conn:
        print("=== CHECKING BRENDAN SMITH DATA ===")
        
        # 1. Check if Brendan Smith works at business 1717010852512540252
        print("\n1. Checking if Brendan Smith works at business 1717010852512540252:")
        query1 = """
            SELECT pb.*, b.business_name 
            FROM practitioner_businesses pb
            JOIN businesses b ON pb.business_id = b.business_id
            WHERE pb.practitioner_id = '1702104296348198163'
            AND pb.business_id = '1717010852512540252'
        """
        result1 = await conn.fetch(query1)
        print(f"Result: {result1}")
        
        # 2. Check all businesses where Brendan Smith works
        print("\n2. All businesses where Brendan Smith works:")
        query2 = """
            SELECT pb.*, b.business_name 
            FROM practitioner_businesses pb
            JOIN businesses b ON pb.business_id = b.business_id
            WHERE pb.practitioner_id = '1702104296348198163'
        """
        result2 = await conn.fetch(query2)
        print(f"Result: {result2}")
        
        # 3. Check all services Brendan Smith offers
        print("\n3. All services Brendan Smith offers:")
        query3 = """
            SELECT pat.*, at.name as service_name
            FROM practitioner_appointment_types pat
            JOIN appointment_types at ON pat.appointment_type_id = at.appointment_type_id
            WHERE pat.practitioner_id = '1702104296348198163'
        """
        result3 = await conn.fetch(query3)
        print(f"Result: {result3}")
        
        # 4. Check if Brendan Smith offers "Acupuncture (Follow up)"
        print("\n4. Checking if Brendan Smith offers 'Acupuncture (Follow up)':")
        query4 = """
            SELECT pat.*, at.name as service_name
            FROM practitioner_appointment_types pat
            JOIN appointment_types at ON pat.appointment_type_id = at.appointment_type_id
            WHERE pat.practitioner_id = '1702104296348198163'
            AND LOWER(at.name) LIKE LOWER('%Acupuncture (Follow up)%')
        """
        result4 = await conn.fetch(query4)
        print(f"Result: {result4}")
        
        # 5. Check the exact service name in the database
        print("\n5. All appointment types containing 'Acupuncture':")
        query5 = """
            SELECT appointment_type_id, name
            FROM appointment_types
            WHERE LOWER(name) LIKE LOWER('%acupuncture%')
        """
        result5 = await conn.fetch(query5)
        print(f"Result: {result5}")
    
    await pool.close()

if __name__ == "__main__":
    asyncio.run(check_brendan_smith_data()) 