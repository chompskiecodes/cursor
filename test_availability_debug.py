#!/usr/bin/env python3
"""Debug availability checker response"""

import asyncio
import httpx
import json
import os

async def test_availability_without_location():
    """Test availability checker without location parameter"""
    
    payload = {
        "sessionId": "test-debug",
        "dialedNumber": "0478621276",
        "practitioner": "Brendan Smith",
        "appointmentType": "Acupuncture (Follow up)",
        "date": "2025-07-07"
        # No location parameter
    }
    
    headers = {
        "Content-Type": "application/json"
    }
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            "http://localhost:8000/availability-checker",
            headers=headers,
            json=payload
        )
        
        data = response.json()
        print("Response:")
        print(json.dumps(data, indent=2))
        
        if data.get("needs_clarification"):
            print(f"\n✓ Needs clarification: {data.get('message')}")
            print(f"Options: {data.get('options')}")
        else:
            print(f"\n✗ No clarification needed")
            print(f"Success: {data.get('success')}")
            print(f"Message: {data.get('message')}")

if __name__ == "__main__":
    asyncio.run(test_availability_without_location()) 