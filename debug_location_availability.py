#!/usr/bin/env python3
"""
Debug script to check actual availability data for each location.
This will help understand why all requests return Location 2 slots.
"""

import asyncio
import httpx
import json
from datetime import datetime, timedelta

async def check_location_availability():
    """Check availability for each location separately"""
    
    # Test data from the previous tests
    locations = {
        "City Clinic": "1701928805762869230",
        "Location 2": "1709781060880966929", 
        "balmain": "1717010852512540252"
    }
    
    print("=== DEBUGGING LOCATION AVAILABILITY ===")
    print(f"Testing date range: {datetime.now().date()} to {(datetime.now() + timedelta(days=7)).date()}")
    print()
    
    async with httpx.AsyncClient() as client:
        for location_name, location_id in locations.items():
            print(f"--- {location_name} (ID: {location_id}) ---")
            
            # Test Cameron at this location
            payload = {
                "practitioner": "Cameron",
                "service": "Acupuncture (Initial)",
                "sessionId": f"debug-{location_name.lower().replace(' ', '-')}",
                "dialedNumber": "0478621276",
                "business_id": location_id
            }
            
            print(f"  Request payload: {json.dumps(payload, indent=2)}")
            
            try:
                response = await client.post(
                    "http://localhost:8000/find-next-available-parallel",
                    json=payload,
                    timeout=30.0
                )
                
                if response.status_code == 200:
                    data = response.json()
                    print(f"  Response:")
                    print(f"    Success: {data.get('success')}")
                    print(f"    Found: {data.get('found')}")
                    print(f"    Message: {data.get('message', 'N/A')}")
                    if data.get('found'):
                        location_data = data.get('location', {})
                        print(f"    Location returned: {location_data.get('name', 'N/A')} (ID: {location_data.get('id', 'N/A')})")
                        print(f"    Requested location: {location_name} (ID: {location_id})")
                        if location_data.get('id') != location_id:
                            print(f"    ⚠️  MISMATCH: Requested {location_id} but got {location_data.get('id')}")
                        else:
                            print(f"    ✅ MATCH: Correct location returned")
                else:
                    print(f"  Error: {response.status_code} - {response.text}")
                    
            except Exception as e:
                print(f"  Exception: {str(e)}")
            
            print()
    
    print("=== SUMMARY ===")
    print("If all locations return Location 2, it means:")
    print("1. Location 2 has the earliest available slots")
    print("2. OR there's a bug in the location filtering")
    print("3. OR the other locations have no availability")
    print()
    print("Check the server logs for detailed API calls to each location.")

if __name__ == "__main__":
    asyncio.run(check_location_availability()) 