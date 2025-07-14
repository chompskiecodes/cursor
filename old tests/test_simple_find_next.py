#!/usr/bin/env python3
"""
Simple test to debug find-next-available endpoints
"""

import asyncio
import aiohttp
import json

async def test_simple():
    """Test a simple find-next-available request"""
    
    test_data = {
        "service": "acupuncture",
        "business_id": "1701928805762869230",
        "locationName": "City Clinic",
        "maxDays": 7,  # Shorter for testing
        "dialedNumber": "0478621276",
        "sessionId": "test-simple-001"
    }
    
    print("Testing sequential endpoint...")
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post("http://localhost:8001/find-next-available", json=test_data) as response:
                print(f"Status: {response.status}")
                response_data = await response.json()
                print(f"Response: {json.dumps(response_data, indent=2)}")
    except Exception as e:
        print(f"Error: {e}")
    
    print("\nTesting parallel endpoint...")
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post("http://localhost:8001/find-next-available-parallel", json=test_data) as response:
                print(f"Status: {response.status}")
                response_data = await response.json()
                print(f"Response: {json.dumps(response_data, indent=2)}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(test_simple()) 