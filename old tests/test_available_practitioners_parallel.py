#!/usr/bin/env python3
"""
Test script to compare sequential vs parallel get-available-practitioners endpoints
"""

import asyncio
import aiohttp
import json
import time
from typing import Dict, Any

# Test configuration
BASE_URL = "http://localhost:8001"
API_KEY = "your-api-key-here"  # Replace with actual API key

# Real business IDs and dialed number from the database
BALMAIN_ID = "1717010852512540252"
CITY_CLINIC_ID = "1701928805762869230"
LOCATION2_ID = "1709781060880966929"
DIALED_NUMBER = "0478621276"  # Client's phone number that dialed the clinic

# Test data
TEST_CASES = [
    {
        "name": "City Clinic - Today",
        "payload": {
            "business_id": CITY_CLINIC_ID,
            "businessName": "City Clinic",
            "date": "today",
            "dialedNumber": DIALED_NUMBER,
            "sessionId": "test-session-001"
        }
    },
    {
        "name": "Balmain - Tomorrow", 
        "payload": {
            "business_id": BALMAIN_ID,
            "businessName": "balmain",
            "date": "tomorrow",
            "dialedNumber": DIALED_NUMBER,
            "sessionId": "test-session-002"
        }
    },
    {
        "name": "Location 2 - Next Week",
        "payload": {
            "business_id": LOCATION2_ID,
            "businessName": "Location 2",
            "date": "next monday",
            "dialedNumber": DIALED_NUMBER,
            "sessionId": "test-session-003"
        }
    }
]

async def make_request(session: aiohttp.ClientSession, endpoint: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Make a request to the specified endpoint"""
    headers = {
        "Content-Type": "application/json",
        "X-API-Key": API_KEY
    }
    
    url = f"{BASE_URL}{endpoint}"
    
    try:
        async with session.post(url, json=payload, headers=headers) as response:
            response_text = await response.text()
            try:
                return json.loads(response_text)
            except json.JSONDecodeError:
                return {"error": "Invalid JSON response", "text": response_text}
    except Exception as e:
        return {"error": f"Request failed: {str(e)}"}

async def test_endpoint(session: aiohttp.ClientSession, endpoint: str, payload: Dict[str, Any], test_name: str) -> Dict[str, Any]:
    """Test a single endpoint and return timing and results"""
    print(f"\n--- Testing {test_name} on {endpoint} ---")
    
    start_time = time.time()
    result = await make_request(session, endpoint, payload)
    elapsed_time = time.time() - start_time
    
    print(f"Response time: {elapsed_time:.2f}s")
    print(f"Success: {result.get('success', False)}")
    
    if result.get('success'):
        practitioners = result.get('practitioners', [])
        print(f"Found {len(practitioners)} available practitioners:")
        for prac in practitioners:
            print(f"  - {prac.get('name', 'Unknown')}")
    else:
        print(f"Error: {result.get('message', 'Unknown error')}")
    
    return {
        "endpoint": endpoint,
        "test_name": test_name,
        "elapsed_time": elapsed_time,
        "success": result.get('success', False),
        "practitioners_count": len(result.get('practitioners', [])),
        "error": result.get('message') if not result.get('success') else None
    }

async def run_comparison_tests():
    """Run comparison tests between sequential and parallel endpoints"""
    print("=== Available Practitioners Endpoint Performance Comparison ===")
    print(f"Testing against: {BASE_URL}")
    
    async with aiohttp.ClientSession() as session:
        all_results = []
        
        for test_case in TEST_CASES:
            test_name = test_case["name"]
            payload = test_case["payload"]
            
            # Test sequential endpoint
            sequential_result = await test_endpoint(
                session, 
                "/get-available-practitioners", 
                payload, 
                f"{test_name} (Sequential)"
            )
            all_results.append(sequential_result)
            
            # Test parallel endpoint
            parallel_result = await test_endpoint(
                session, 
                "/get-available-practitioners-parallel", 
                payload, 
                f"{test_name} (Parallel)"
            )
            all_results.append(parallel_result)
            
            # Calculate improvement
            if sequential_result["success"] and parallel_result["success"]:
                improvement = ((sequential_result["elapsed_time"] - parallel_result["elapsed_time"]) / sequential_result["elapsed_time"]) * 100
                print(f"Performance improvement: {improvement:.1f}%")
            elif not sequential_result["success"] and parallel_result["success"]:
                print("Parallel endpoint succeeded where sequential failed!")
            elif sequential_result["success"] and not parallel_result["success"]:
                print("WARNING: Parallel endpoint failed where sequential succeeded!")
            
            print("-" * 60)
        
        # Summary
        print("\n=== SUMMARY ===")
        sequential_results = [r for r in all_results if "Sequential" in r["test_name"]]
        parallel_results = [r for r in all_results if "Parallel" in r["test_name"]]
        
        if sequential_results and parallel_results:
            avg_sequential = sum(r["elapsed_time"] for r in sequential_results) / len(sequential_results)
            avg_parallel = sum(r["elapsed_time"] for r in parallel_results) / len(parallel_results)
            
            print(f"Average sequential time: {avg_sequential:.2f}s")
            print(f"Average parallel time: {avg_parallel:.2f}s")
            
            if avg_sequential > 0:
                overall_improvement = ((avg_sequential - avg_parallel) / avg_sequential) * 100
                print(f"Overall performance improvement: {overall_improvement:.1f}%")
        
        # Success rates
        sequential_success = sum(1 for r in sequential_results if r["success"])
        parallel_success = sum(1 for r in parallel_results if r["success"])
        
        print(f"Sequential success rate: {sequential_success}/{len(sequential_results)} ({sequential_success/len(sequential_results)*100:.1f}%)")
        print(f"Parallel success rate: {parallel_success}/{len(parallel_results)} ({parallel_success/len(parallel_results)*100:.1f}%)")

async def test_single_endpoint():
    """Test just the parallel endpoint with a single case"""
    print("=== Testing Parallel Available Practitioners Endpoint ===")
    
    # Use the first test case
    test_case = TEST_CASES[0]
    payload = test_case["payload"]
    
    async with aiohttp.ClientSession() as session:
        result = await test_endpoint(
            session,
            "/get-available-practitioners-parallel",
            payload,
            test_case["name"]
        )
        
        print(f"\nDetailed result: {json.dumps(result, indent=2)}")

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "single":
        asyncio.run(test_single_endpoint())
    else:
        asyncio.run(run_comparison_tests()) 