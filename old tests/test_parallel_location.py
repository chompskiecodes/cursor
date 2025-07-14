import asyncio
import aiohttp
import json
import time

# Test configuration
BASE_URL = "http://localhost:8000"
API_KEY = "your-api-key-here"  # Replace with actual API key

# Example test data (update as needed)
BUSINESS_ID = "1701928805762869230"
BUSINESS_NAME = "City Clinic"
DIALED_NUMBER = "0478621276"
SESSION_ID = "test-parallel-location-001"

async def test_parallel_location():
    payload = {
        "business_id": BUSINESS_ID,
        "businessName": BUSINESS_NAME,
        "dialedNumber": DIALED_NUMBER,
        "sessionId": SESSION_ID
    }
    headers = {
        "Content-Type": "application/json",
        "X-API-Key": API_KEY
    }
    url = f"{BASE_URL}/get-location-practitioners-parallel"
    print(f"\n=== Testing: /get-location-practitioners-parallel ===")
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
            assert "practitioners" in resp_json and isinstance(resp_json["practitioners"], list), "No practitioners list in response"
            print(f"Test passed in {elapsed:.2f} seconds.")

if __name__ == "__main__":
    asyncio.run(test_parallel_location()) 