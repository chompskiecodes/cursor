#!/usr/bin/env python3
"""
Test that phone number 0478621276 works with location-resolver
"""

import asyncio
import httpx
import json
import os
from dotenv import load_dotenv

load_dotenv()

BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")
API_KEY = os.getenv("API_KEY", "development-key")

# MUST use this exact phone number
CLINIC_PHONE = "0478621276"

HEADERS = {
    "X-API-Key": API_KEY,
    "Content-Type": "application/json"
}

async def test_phone():
    """Test the hardcoded phone number"""
    print(f"\nTesting with clinic phone number: {CLINIC_PHONE}")
    print("="*60)
    
    async with httpx.AsyncClient() as client:
        # Test 1: Empty query to get all locations
        print("\n1. Testing empty query (should return all locations)...")
        response = await client.post(
            f"{BASE_URL}/location-resolver",
            json={
                "locationQuery": "",
                "sessionId": "test_123",
                "dialedNumber": CLINIC_PHONE,  # Must be this exact number
                "callerPhone": "0412345678"
            },
            headers=HEADERS,
            timeout=10.0
        )
        
        data = response.json()
        print(f"Response: {json.dumps(data, indent=2)}")
        
        if data.get("success"):
            if data.get("needsClarification") and data.get("options"):
                print(f"\n✅ SUCCESS! Found {len(data['options'])} locations:")
                for opt in data['options']:
                    print(f"   - {opt.get('name')} (ID: {opt.get('id')})")
                
                # Test 2: Use first location name
                if data['options']:
                    first_location = data['options'][0]['name']
                    print(f"\n2. Testing with specific location: '{first_location}'...")
                    
                    response2 = await client.post(
                        f"{BASE_URL}/location-resolver",
                        json={
                            "locationQuery": first_location,
                            "sessionId": "test_123",
                            "dialedNumber": CLINIC_PHONE,
                            "callerPhone": "0412345678"
                        },
                        headers=HEADERS,
                        timeout=10.0
                    )
                    
                    data2 = response2