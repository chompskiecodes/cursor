#!/usr/bin/env python3
"""
Comprehensive test script for parallel availability endpoint using real Cliniko data.
Tests various scenarios with actual practitioner names, business IDs, and treatments.
"""

import asyncio
import httpx
import json
import time
from typing import Dict, Any, List

# Real test data from Cliniko (based on the logs we've seen)
TEST_DATA = {
    "clinic": {
        "dialedNumber": "0478621276",
        "clinic_name": "Noam Field"
    },
    "practitioners": [
        {
            "name": "Cameron",
            "full_name": "Cameron Lockey",
            "practitioner_id": "1702107281644070164"
        }
    ],
    "services": [
        {
            "name": "Acupuncture (Initial)",
            "appointment_type_id": "1701928805083391378"
        },
        {
            "name": "Physiotherapy",
            "appointment_type_id": "1701928805083391379"  # Example ID
        }
    ],
    "locations": [
        {
            "name": "City Clinic",
            "business_id": "1701928805762869230"
        },
        {
            "name": "Location 2", 
            "business_id": "1709781060880966929"
        },
        {
            "name": "balmain",
            "business_id": "1717010852512540252"
        }
    ]
}

class ParallelAvailabilityTester:
    def __init__(self, base_url: str = "http://localhost:8000"):
        self.base_url = base_url
        self.client = httpx.AsyncClient(timeout=60.0)
        
    async def test_endpoint(self, payload: Dict[str, Any], test_name: str) -> Dict[str, Any]:
        """Test a single endpoint with given payload"""
        print(f"\n=== {test_name} ===")
        print(f"Payload: {json.dumps(payload, indent=2)}")
        
        start_time = time.time()
        try:
            response = await self.client.post(
                f"{self.base_url}/find-next-available-parallel",
                json=payload
            )
            response_time = time.time() - start_time
            
            print(f"Response Status: {response.status_code}")
            print(f"Response Time: {response_time:.2f} seconds")
            
            if response.status_code == 200:
                response_data = response.json()
                print(f"Success: {response_data.get('success', False)}")
                print(f"Found: {response_data.get('found', False)}")
                print(f"Message: {response_data.get('message', 'No message')}")
                
                if response_data.get('found'):
                    slot = response_data.get('slot', {})
                    practitioner = response_data.get('practitioner', {})
                    location = response_data.get('location', {})
                    
                    print(f"Slot: {slot.get('date')} at {slot.get('time')}")
                    print(f"Practitioner: {practitioner.get('name')} (ID: {practitioner.get('id')})")
                    print(f"Location: {location.get('name')} (ID: {location.get('id')})")
                    print(f"firstName field: {practitioner.get('firstName')}")
                
                return {
                    "success": True,
                    "response_time": response_time,
                    "data": response_data
                }
            else:
                print(f"❌ ERROR: HTTP {response.status_code}")
                print(f"Response: {response.text}")
                return {
                    "success": False,
                    "response_time": response_time,
                    "error": f"HTTP {response.status_code}"
                }
                
        except Exception as e:
            response_time = time.time() - start_time
            print(f"❌ ERROR: {str(e)}")
            return {
                "success": False,
                "response_time": response_time,
                "error": str(e)
            }

    async def run_comprehensive_tests(self):
        """Run all test scenarios"""
        print("Starting comprehensive parallel availability tests...")
        print(f"Testing against: {self.base_url}")
        print("Using real Cliniko data from test environment")
        
        test_results = []
        
        # Test 1: Specific practitioner with specific service
        test_results.append(await self.test_endpoint({
            "practitioner": "Cameron",
            "service": "Acupuncture (Initial)",
            "sessionId": "test-1",
            "dialedNumber": TEST_DATA["clinic"]["dialedNumber"]
        }, "Test 1: Cameron + Acupuncture (Initial) - All Locations"))
        
        # Test 2: Specific practitioner with specific service at specific location
        test_results.append(await self.test_endpoint({
            "practitioner": "Cameron",
            "service": "Acupuncture (Initial)",
            "sessionId": "test-2",
            "dialedNumber": TEST_DATA["clinic"]["dialedNumber"],
            "business_id": TEST_DATA["locations"][2]["business_id"]  # balmain
        }, "Test 2: Cameron + Acupuncture (Initial) - balmain only"))
        
        # Test 3: Specific practitioner only (no service specified)
        test_results.append(await self.test_endpoint({
            "practitioner": "Cameron",
            "sessionId": "test-3",
            "dialedNumber": TEST_DATA["clinic"]["dialedNumber"]
        }, "Test 3: Cameron only - All services"))
        
        # Test 4: Service only (any practitioner)
        test_results.append(await self.test_endpoint({
            "service": "Acupuncture (Initial)",
            "sessionId": "test-4",
            "dialedNumber": TEST_DATA["clinic"]["dialedNumber"]
        }, "Test 4: Acupuncture (Initial) - Any practitioner"))
        
        # Test 5: Service only at specific location
        test_results.append(await self.test_endpoint({
            "service": "Acupuncture (Initial)",
            "sessionId": "test-5",
            "dialedNumber": TEST_DATA["clinic"]["dialedNumber"],
            "business_id": TEST_DATA["locations"][0]["business_id"]  # City Clinic
        }, "Test 5: Acupuncture (Initial) - City Clinic only"))
        
        # Test 6: Edge case - No practitioner or service
        test_results.append(await self.test_endpoint({
            "sessionId": "test-6",
            "dialedNumber": TEST_DATA["clinic"]["dialedNumber"]
        }, "Test 6: No practitioner or service specified"))
        
        # Test 7: Short search window
        test_results.append(await self.test_endpoint({
            "practitioner": "Cameron",
            "service": "Acupuncture (Initial)",
            "sessionId": "test-7",
            "dialedNumber": TEST_DATA["clinic"]["dialedNumber"],
            "maxDays": 3
        }, "Test 7: Short search window (3 days)"))
        
        # Test 8: Long search window
        test_results.append(await self.test_endpoint({
            "practitioner": "Cameron",
            "service": "Acupuncture (Initial)",
            "sessionId": "test-8",
            "dialedNumber": TEST_DATA["clinic"]["dialedNumber"],
            "maxDays": 30
        }, "Test 8: Long search window (30 days)"))
        
        # Test 9: Different location combinations
        for i, location in enumerate(TEST_DATA["locations"]):
            test_results.append(await self.test_endpoint({
                "practitioner": "Cameron",
                "service": "Acupuncture (Initial)",
                "sessionId": f"test-9-{i}",
                "dialedNumber": TEST_DATA["clinic"]["dialedNumber"],
                "business_id": location["business_id"]
            }, f"Test 9.{i+1}: Cameron + Acupuncture at {location['name']}"))
        
        # Performance comparison with sequential endpoint
        print("\n=== Performance Comparison ===")
        
        # Test sequential endpoint
        print("Testing sequential endpoint...")
        sequential_start = time.time()
        sequential_response = await self.client.post(
            f"{self.base_url}/find-next-available",
            json={
                "practitioner": "Cameron",
                "service": "Acupuncture (Initial)",
                "sessionId": "perf-test",
                "dialedNumber": TEST_DATA["clinic"]["dialedNumber"]
            }
        )
        sequential_time = time.time() - sequential_start
        
        # Test parallel endpoint
        print("Testing parallel endpoint...")
        parallel_start = time.time()
        parallel_response = await self.client.post(
            f"{self.base_url}/find-next-available-parallel",
            json={
                "practitioner": "Cameron",
                "service": "Acupuncture (Initial)",
                "sessionId": "perf-test",
                "dialedNumber": TEST_DATA["clinic"]["dialedNumber"]
            }
        )
        parallel_time = time.time() - parallel_start
        
        print(f"Sequential: {sequential_time:.2f}s")
        print(f"Parallel:   {parallel_time:.2f}s")
        if sequential_time > 0:
            improvement = ((sequential_time - parallel_time) / sequential_time) * 100
            print(f"Improvement: {improvement:.1f}% faster")
        
        # Summary
        print("\n=== Test Summary ===")
        successful_tests = sum(1 for r in test_results if r["success"])
        total_tests = len(test_results)
        print(f"Successful tests: {successful_tests}/{total_tests}")
        
        if successful_tests < total_tests:
            print("\nFailed tests:")
            for i, result in enumerate(test_results):
                if not result["success"]:
                    print(f"  Test {i+1}: {result.get('error', 'Unknown error')}")
        
        await self.client.aclose()

async def main():
    """Main test runner"""
    tester = ParallelAvailabilityTester()
    await tester.run_comprehensive_tests()

if __name__ == "__main__":
    print("Comprehensive Parallel Availability Tests")
    print("Make sure your backend is running on localhost:8000")
    print("Using real Cliniko data from test environment")
    print("=" * 60)
    
    asyncio.run(main()) 