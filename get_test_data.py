#!/usr/bin/env python3
"""
Script to get real test data from the database
"""

import asyncio
import asyncpg
import os
from dotenv import load_dotenv

load_dotenv()

async def get_test_data():
    """Get real business IDs and dialed numbers for testing"""
    
    # Database connection
    DATABASE_URL = os.getenv('DATABASE_URL')
    if not DATABASE_URL:
        print("DATABASE_URL not found in environment")
        return
    
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        
        # Check phone_lookup table for available dialed numbers
        print("=== Phone Lookup Table ===")
        phone_lookup = await conn.fetch("""
            SELECT pl.phone_normalized, c.clinic_name
            FROM phone_lookup pl
            JOIN clinics c ON pl.clinic_id = c.clinic_id
            ORDER BY c.clinic_name
        """)
        
        for row in phone_lookup:
            print(f"Normalized: {row['phone_normalized']}")
            print(f"Clinic: {row['clinic_name']}")
            # Convert back to original format for testing
            if row['phone_normalized'].startswith('61'):
                original = '0' + row['phone_normalized'][2:]
                print(f"Original format for testing: {original}")
            print()
        
        # Check clinics table structure
        print("=== Clinics Table Structure ===")
        columns = await conn.fetch("""
            SELECT column_name, data_type 
            FROM information_schema.columns 
            WHERE table_name = 'clinics'
            ORDER BY ordinal_position
        """)
        
        for col in columns:
            print(f"{col['column_name']}: {col['data_type']}")
        print()
        
        # Get businesses
        print("=== Businesses ===")
        businesses = await conn.fetch("""
            SELECT business_id, business_name 
            FROM businesses 
            ORDER BY business_name
        """)
        
        for business in businesses:
            print(f"Business ID: {business['business_id']}")
            print(f"Business Name: {business['business_name']}")
            print()
        
        # Get clinics
        print("=== Clinics ===")
        clinics = await conn.fetch("""
            SELECT clinic_id, clinic_name 
            FROM clinics 
            ORDER BY clinic_name
        """)
        
        for clinic in clinics:
            print(f"Clinic ID: {clinic['clinic_id']}")
            print(f"Clinic Name: {clinic['clinic_name']}")
            print()
        
        # Get practitioners per business
        print("=== Practitioners per Business ===")
        practitioners = await conn.fetch("""
            SELECT 
                b.business_name,
                p.first_name || ' ' || p.last_name as practitioner_name,
                COUNT(DISTINCT at.name) as service_count
            FROM practitioners p
            JOIN practitioner_businesses pb ON p.practitioner_id = pb.practitioner_id
            JOIN businesses b ON pb.business_id = b.business_id
            JOIN practitioner_appointment_types pat ON p.practitioner_id = pat.practitioner_id
            JOIN appointment_types at ON pat.appointment_type_id = at.appointment_type_id
            WHERE p.active = true AND at.active = true
            GROUP BY b.business_name, p.first_name, p.last_name
            ORDER BY b.business_name, practitioner_name
        """)
        
        current_business = None
        for prac in practitioners:
            if prac['business_name'] != current_business:
                current_business = prac['business_name']
                print(f"\n{current_business}:")
            print(f"  - {prac['practitioner_name']} ({prac['service_count']} services)")
        
        await conn.close()
        
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(get_test_data()) 