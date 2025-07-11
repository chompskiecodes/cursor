import requests
import json
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Test configuration
WEBHOOK_BASE_URL = "http://localhost:8000"
API_KEY = "development-key"

def test_business_name_debug():
    """Test to see what business name is actually returned"""
    
    # Test payload with the business_id that should be City Clinic
    payload = {
        "business_id": "1701928805762869230",  # This should be City Clinic
        "businessName": "City Clinic",  # The business name
        "dialedNumber": "0478621276",
        "sessionId": "test-business-name-debug"
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
            logger.info(f"Response: {json.dumps(data, indent=2)}")
            
            # Check if we got a location name in the response
            if data.get('location'):
                logger.info(f"Location returned: {data['location']}")
        else:
            logger.error(f"HTTP {response.status_code}: {response.text}")
            
    except Exception as e:
        logger.error(f"Request failed with exception: {e}")

if __name__ == "__main__":
    test_business_name_debug() 