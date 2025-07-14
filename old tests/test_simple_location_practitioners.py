import requests
import json
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Test configuration
WEBHOOK_BASE_URL = "http://localhost:8000"
API_KEY = "development-key"

def test_simple_location_practitioners():
    """Simple test for get-location-practitioners endpoint"""
    
    # Test payload with correct business name
    payload = {
        "business_id": "1701928805762869230",  # City Clinic
        "businessName": "Noam Field",  # Actual business name from the database
        "dialedNumber": "+61478621276",  # Correct dialed number
        "sessionId": "test-simple-123"
    }
    
    headers = {
        "Content-Type": "application/json",
        "X-API-Key": API_KEY
    }
    
    logger.info(f"Testing with payload: {payload}")
    
    try:
        response = requests.post(
            f"{WEBHOOK_BASE_URL}/get-location-practitioners",
            json=payload,
            headers=headers,
            timeout=10
        )
        
        logger.info(f"Response status: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            logger.info(f"Success! Response: {json.dumps(data, indent=2)}")
        else:
            logger.error(f"HTTP {response.status_code}: {response.text}")
            
    except Exception as e:
        logger.error(f"Request failed with exception: {e}")

if __name__ == "__main__":
    test_simple_location_practitioners() 