import asyncio
import aiohttp
import json
import time

# Test configuration
BASE_URL = "http://localhost:8000"
API_KEY = "your-api-key-here"  # Replace with actual API key

# Example test data (update as needed)
PRACTITIONER = "Brendan Smith"
APPOINTMENT_TYPE = "Acupuncture (Initial)"
BUSINESS_ID = "1701928805762869230"
DATE = "2025-07-14"
DIALED_NUMBER = "0478621276"
SESSION_ID = "test-parallel-availability-001"

async def test_parallel_availability_checker():
    payload = {
        "practitioner": PRACTITIONER,
        "appointmentType": APPOINTMENT_TYPE,
        "business_id": BUSINESS_ID,
        "date": DATE,
        "dialedNumber": DIALED_NUMBER,
        "sessionId": SESSION_ID
    }
    headers = {
        "Content-Type": "application/json",
        "X-API-Key": API_KEY
    }
    url = f"{BASE_URL}/availability-checker-parallel"
    print(f"\n=== Testing: /availability-checker-parallel ===")
    print(f"Request: {json.dumps(payload, indent=2)}")
    async with aiohttp.ClientSession() as session:
        start_time = time.time()
        async with session.post(url, json=payload, headers=headers) as response:
            elapsed = time.time() - start_time
            resp_json = await response.json()
            print(f"Status: {response.status}")
            print(f"Response: {json.dumps(resp_json, indent=2)}")
            assert response.status == 200, "Non-200 response"
            assert resp_json.get("success"), "Response did not indicate success"
            assert "available_times" in resp_json or "slots" in resp_json, "No available_times or slots in response"
            print(f"Test passed in {elapsed:.2f} seconds.")

if __name__ == "__main__":
    asyncio.run(test_parallel_availability_checker()) 