#!/usr/bin/env python3
"""
Debug test for enhanced endpoints to identify the exact error.
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
        "locationId": "1717010852512540252",
        "locationName": "City Clinic"
    }
    
    try:
        response = requests.post(
            f'{WEBHOOK_BASE_URL}/enhanced/find-next-available',
            headers=webhook_headers,
            json=payload,
            timeout=30
        )
        
        print(f"Status: {response.status_code}")
        print(f"Response: {response.text}")
        
        if response.status_code == 200:
            data = response.json()
            print(f"Success: {data.get('success')}")
            print(f"Message: {data.get('message')}")
            
            # Check for performance metrics
            if 'performance_metrics' in data:
                metrics = data['performance_metrics']
                print(f"Performance metrics:")
                print(f"  Execution time: {metrics.get('execution_time', 'N/A')}")
                print(f"  Total calls: {metrics.get('total_calls', 'N/A')}")
                print(f"  Success rate: {metrics.get('success_rate', 'N/A')}%")
        
    except Exception as e:
        print(f"Error: {e}")

def test_enhanced_get_available_practitioners():
    """Test the enhanced get-available-practitioners endpoint"""
    print("\nTesting enhanced/get-available-practitioners...")
    
    payload = {
        "business_id": "1717010852512540252",
        "businessName": "City Clinic",
        "date": "2025-07-13",
        "dialedNumber": "0478621276",
        "sessionId": "debug_test_123"
    }
    
    try:
        response = requests.post(
            f'{WEBHOOK_BASE_URL}/enhanced/get-available-practitioners',
            headers=webhook_headers,
            json=payload,
            timeout=30
        )
        
        print(f"Status: {response.status_code}")
        print(f"Response: {response.text}")
        
        if response.status_code == 200:
            data = response.json()
            print(f"Success: {data.get('success')}")
            print(f"Message: {data.get('message')}")
            
            # Check for performance metrics
            if 'performance_metrics' in data:
                metrics = data['performance_metrics']
                print(f"Performance metrics:")
                print(f"  Execution time: {metrics.get('execution_time', 'N/A')}")
                print(f"  Total calls: {metrics.get('total_calls', 'N/A')}")
                print(f"  Success rate: {metrics.get('success_rate', 'N/A')}%")
        
    except Exception as e:
        print(f"Error: {e}")

def test_sequential_find_next_available():
    print("\nTesting sequential/find-next-available...")
    payload = {
        "sessionId": "debug_test_123",
        "dialedNumber": "0478621276",
        "maxDays": 14,
        "practitioner": "Brendan Smith",
        "service": "Acupuncture (Follow up)",
        "locationId": "1717010852512540252",
        "locationName": "City Clinic"
    }
    try:
        response = requests.post(
            f'{WEBHOOK_BASE_URL}/find-next-available',
            headers=webhook_headers,
            json=payload,
            timeout=30
        )
        print(f"Status: {response.status_code}")
        print(f"Response: {response.text}")
    except Exception as e:
        print(f"Error: {e}")

def test_sequential_get_available_practitioners():
    print("\nTesting sequential/get-available-practitioners...")
    payload = {
        "business_id": "1717010852512540252",
        "businessName": "City Clinic",
        "date": "2025-07-13",
        "dialedNumber": "0478621276",
        "sessionId": "debug_test_123"
    }
    try:
        response = requests.post(
            f'{WEBHOOK_BASE_URL}/get-available-practitioners',
            headers=webhook_headers,
            json=payload,
            timeout=30
        )
        print(f"Status: {response.status_code}")
        print(f"Response: {response.text}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    print("=== Enhanced Endpoints Debug Test ===")
    test_enhanced_find_next_available()
    test_enhanced_get_available_practitioners()
    print("\n=== Sequential Endpoints Debug Test ===")
    test_sequential_find_next_available()
    test_sequential_get_available_practitioners()
    print("\n=== Debug Test Complete ===") 