#!/usr/bin/env python3
"""
Simple debug test for enhanced find-next-available endpoint.
"""

import requests
import json
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configuration
WEBHOOK_BASE_URL = 'http://localhost:8000'
WEBHOOK_API_KEY = 'development-key'

webhook_headers = {
    'X-API-Key': WEBHOOK_API_KEY,
    'Content-Type': 'application/json'
}

def test_enhanced_find_next_available():
    """Test the enhanced find-next-available endpoint"""
    print("Testing enhanced/find-next-available...")
    
    payload = {
        "sessionId": "debug_test_123",
        "dialedNumber": "0478621276",
        "maxDays": 14,
        "practitioner": "Brendan Smith",
        "service": "Acupuncture (Follow up)",
        "business_id": "1717010852512540252",
        "businessName": "City Clinic"
    }
    
    print(f"Payload: {json.dumps(payload, indent=2)}")
    
    try:
        response = requests.post(
            f'{WEBHOOK_BASE_URL}/enhanced/find-next-available',
            headers=webhook_headers,
            json=payload,
            timeout=60
        )
        
        print(f"Status: {response.status_code}")
        print(f"Response: {response.text}")
        
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    print("=== Simple Enhanced Debug Test ===")
    test_enhanced_find_next_available()
    print("=== Test Complete ===") 