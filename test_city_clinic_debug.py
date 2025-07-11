import requests
import json
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Test configuration
WEBHOOK_BASE_URL = "http://localhost:8000"
API_KEY = "development-key"

def test_city_clinic_practitioners():
    """Test for City Clinic specifically to see debug logs"""
    
    # Test payload for City Clinic
    payload = {
        "locationId": "1701928805762869230",  # City Clinic business_id
        "locationName": "City Clinic",  # The actual location name
        "dialedNumber": "0478621276",
        "sessionId": "test-city-clinic-123"
    }
    
    headers = {
        "Content-Type": "application/json",
        "X-API-Key": API_KEY
    }
    
    logger.info(f"Testing City Clinic with payload: {payload}")
    
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
    test_city_clinic_practitioners() 