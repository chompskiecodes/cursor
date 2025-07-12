#!/usr/bin/env python3
"""Debug script for find-next-available endpoint"""

import asyncio
import httpx
import json
from datetime import datetime, timedelta

async def test_find_next_available():
    """Test the /find-next-available endpoint directly with production-like payload"""
    
    # Test data matching the failing production call
    payload = {
        "practitioner": "Cameron",
        "service": "Acupuncture (Initial)",
        "sessionId": "1",
        "dialedNumber": "0478621276",
        "business_id": "1717010852512540252"
    }
    
    print("Testing /find-next-available...")
    print(f"Payload: {json.dumps(payload, indent=2)}")
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "http://localhost:8000/find-next-available",
                json=payload,
                timeout=60.0
            )
            
            print(f"Status: {response.status_code}")
            print(f"Response: {response.text}")
            if response.status_code == 200:
                data = response.json()
                print(json.dumps(data, indent=2))
    
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(test_find_next_available())
