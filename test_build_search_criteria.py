#!/usr/bin/env python3
"""
Debug test for build_search_criteria function.
"""

import asyncio
import asyncpg
from dotenv import load_dotenv
from tools.enhanced_availability_router import build_search_criteria
from models import ClinicData

# Load environment variables
load_dotenv()

async def test_build_search_criteria():
    """Test the build_search_criteria function"""
    print("Testing build_search_criteria function...")
    
    # Create database connection
    pool = await asyncpg.create_pool(os.getenv("DATABASE_URL"))
    
    try:
        # Create a mock clinic
        clinic = ClinicData(
            clinic_id="test_clinic",
            clinic_name="Test Clinic",
            cliniko_api_key="test_key",
            cliniko_shard="test",
            contact_email="test@example.com",
            timezone="Australia/Sydney"
        )
        
        # Test with various parameters
        test_cases = [
            {
                "name": "Basic test",
                "service_name": "Acupuncture (Follow up)",
                "practitioner_name": "Brendan Smith",
                "business_id": "1717010852512540252"
            },
            {
                "name": "Service only",
                "service_name": "Acupuncture (Follow up)",
                "practitioner_name": None,
                "business_id": None
            },
            {
                "name": "Practitioner only",
                "service_name": None,
                "practitioner_name": "Brendan Smith",
                "business_id": None
            }
        ]
        
        for test_case in test_cases:
            print(f"\n--- {test_case['name']} ---")
            try:
                criteria = await build_search_criteria(
                    service_name=test_case['service_name'],
                    practitioner_name=test_case['practitioner_name'],
                    business_id=test_case['business_id'],
                    clinic=clinic,
                    pool=pool
                )
                
                print(f"Success! Found {len(criteria)} search criteria")
                for i, c in enumerate(criteria):
                    print(f"  {i+1}: {c['practitioner_name']} - {c['service_name']} at {c['business_name']}")
                    
            except Exception as e:
                print(f"Error: {e}")
                import traceback
                print(f"Traceback: {traceback.format_exc()}")
    
    finally:
        await pool.close()

if __name__ == "__main__":
    import os
    asyncio.run(test_build_search_criteria()) 