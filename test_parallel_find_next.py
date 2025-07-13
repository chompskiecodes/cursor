#!/usr/bin/env python3
"""Test script for parallel find-next-available endpoint"""

import asyncio
import aiohttp
import json
from datetime import datetime

async def test_parallel_find_next():
    """Test the parallel find-next-available endpoint"""
    
    # Test data
    test_cases = [
        {
            "name": "Acupuncture test",
            "data": {
                "service": "acupuncture",
                "dialedNumber": "0478621276",
                "sessionId": "test-parallel-001",
                "maxDays": 14
            }
        },
        {
            "name": "Massage test", 
            "data": {
                "service": "massage",
                "dialedNumber": "0478621276",
                "sessionId": "test-parallel-002",
                "maxDays": 14
            }
        },
        {
            "name": "Specific practitioner test - Brendan",
            "data": {
                "practitioner": "Brendan",
                "dialedNumber": "0478621276", 
                "sessionId": "test-parallel-003",
                "maxDays": 14
            }
        },
        {
            "name": "Specific practitioner test - Cameron",
            "data": {
                "practitioner": "Cameron",
                "dialedNumber": "0478621276", 
                "sessionId": "test-parallel-004",
                "maxDays": 14
            }
        },
        {
            "name": "Specific practitioner test - Chomps",
            "data": {
                "practitioner": "Chomps",
                "dialedNumber": "0478621276", 
                "sessionId": "test-parallel-005",
                "maxDays": 14
            }
        }
    ]
    
    base_url = "http://localhost:8001"
    
    async with aiohttp.ClientSession() as session:
        for test_case in test_cases:
            print(f"\n=== Testing: {test_case['name']} ===")
            print(f"Request: {json.dumps(test_case['data'], indent=2)}")
            
            try:
                async with session.post(
                    f"{base_url}/find-next-available-parallel",
                    json=test_case['data'],
                    headers={"Content-Type": "application/json"}
                ) as response:
                    result = await response.json()
                    print(f"Status: {response.status}")
                    print(f"Response: {json.dumps(result, indent=2)}")
                    
            except Exception as e:
                print(f"Error: {e}")

if __name__ == "__main__":
    print(f"Starting parallel find-next-available tests at {datetime.now()}")
    asyncio.run(test_parallel_find_next())
    print(f"Tests completed at {datetime.now()}") 