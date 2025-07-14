import os
import requests
import json
from dotenv import load_dotenv

load_dotenv()

WEBHOOK_BASE_URL = os.getenv('WEBHOOK_BASE_URL', 'http://localhost:8000')
WEBHOOK_API_KEY = os.getenv('API_KEY', 'development-key')

# Use the known correct business/location ID for City Clinic
CITY_CLINIC_ID = '1701928805762869230'
CITY_CLINIC_NAME = 'City Clinic'

headers = {
    'X-API-Key': WEBHOOK_API_KEY,
    'Content-Type': 'application/json'
}

payload = {
    "dialedNumber": "0478621276",
    "sessionId": "test_mock_1",
    "locationName": CITY_CLINIC_NAME,
    "locationId": CITY_CLINIC_ID
}

url = f"{WEBHOOK_BASE_URL}/get-location-practitioners"

print(f"POST {url}\nPayload: {json.dumps(payload, indent=2)}\n")

try:
    response = requests.post(url, headers=headers, json=payload, timeout=15)
    print(f"Status: {response.status_code}")
    print(f"Response: {response.text}")
except Exception as e:
    print(f"Request failed: {e}") 