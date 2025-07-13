#!/usr/bin/env python3
"""
Debug test for enhanced find-next-available endpoint
"""

import requests
import json
import time

# Configuration
WEBHOOK_BASE_URL = "http://localhost:8000"
WEBHOOK_API_KEY = "development-key"

webhook_headers = {
    'X-API-Key': WEBHOOK_API_KEY,
    'Content-Type': 'application/json'
}

def test_enhanced_find_next():
    """Test the enhanced find-next-available endpoint"""
    print("=== Enhanced Find Next Available Debug Test ===")
    
    payload = {
        "sessionId": "debug_test_123",
        "dialedNumber": "0478621276",
        "maxDays": 14,
        "practitioner": "Brendan Smith",
        "service": "Acupuncture (Follow up)",
        "locationId": "1717010852512540252",
        "locationName": "City Clinic"
    }
    
    print(f"Testing enhanced/find-next-available...")
    print(f"Payload: {json.dumps(payload, indent=2)}")
    
    start_time = time.time()
    
    try:
        response = requests.post(
            f'{WEBHOOK_BASE_URL}/enhanced/find-next-available',
            headers=webhook_headers,
            json=payload,
            timeout=120
        )
        
        duration = time.time() - start_time
        
        print(f"Status: {response.status_code}")
        print(f"Duration: {duration:.2f}s")
        print(f"Response: {response.text}")
        
        if response.status_code == 200:
            data = response.json()
            print(f"Success: {data.get('success')}")
            print(f"Found: {data.get('found')}")
            print(f"Message: {data.get('message')}")
            
            if 'performance_metrics' in data:
                metrics = data['performance_metrics']
                print(f"Performance metrics:")
                print(f"  Total calls: {metrics.get('total_calls')}")
                print(f"  Successful calls: {metrics.get('successful_calls')}")
                print(f"  Failed calls: {metrics.get('failed_calls')}")
                print(f"  Cache hits: {metrics.get('cache_hits')}")
                print(f"  Success rate: {metrics.get('success_rate')}%")
        else:
            print(f"Error: HTTP {response.status_code}")
            
    except Exception as e:
        duration = time.time() - start_time
        print(f"Error: {str(e)}")
        print(f"Duration: {duration:.2f}s")

if __name__ == "__main__":
    test_enhanced_find_next() 