#!/usr/bin/env python3
"""Debug script for availability checker"""

import asyncio
import httpx
import json
from datetime import datetime, timedelta

async def test_availability_checker():
    """Test the availability checker directly"""
    
    # Test data
    payload = {
        "practitioner": "Brendan Smith",
        "appointmentType": "Massage",
        "date": "2025-07-07",
        "sessionId": "debug_test_123",
        "dialedNumber": "0478621276",
        "business_id": "1701928805762869230"  # City Clinic
    }
    
    print("Testing availability checker...")
    print(f"Payload: {json.dumps(payload, indent=2)}")
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "http://localhost:8000/availability-checker",
                json=payload,
                timeout=30.0
            )
            
            print(f"Status: {response.status_code}")
            print(f"Response: {response.text}")
            
            if response.status_code == 200:
                data = response.json()
                print(f"Success: {data.get('success')}")
                print(f"Message: {data.get('message')}")
                print(f"Error: {data.get('error')}")
                print(f"Resolved: {data.get('resolved')}")
                print(f"NeedsClarification: {data.get('needsClarification')}")
                
                if data.get('next_available'):
                    print(f"Next available: {data.get('next_available')}")
            
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(test_availability_checker())
