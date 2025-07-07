import requests
import json
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Test configuration
WEBHOOK_BASE_URL = "http://localhost:8000"
API_KEY = "development-key"

def test_get_location_practitioners():
    """Test get-location-practitioners endpoint with City Clinic"""
    
    # City Clinic business ID from the database
    city_clinic_id = "1701928805762869230"
    
    # Use the actual dialed number from the database
    actual_dialed_number = "+61478621276"  # This normalizes to 61478621276
    
    # Test payload
    payload = {
        "business_id": city_clinic_id,  # Use business_id instead of locationId
        "businessName": "City Clinic",
        "dialedNumber": actual_dialed_number,  # Use the correct dialed number
        "sessionId": "test-session-123"
    }
    
    headers = {
        "Content-Type": "application/json",
        "X-API-Key": API_KEY
    }
    
    logger.info(f"Testing get-location-practitioners with payload: {payload}")
    
    try:
        response = requests.post(
            f"{WEBHOOK_BASE_URL}/get-location-practitioners",
            json=payload,
            headers=headers,
            timeout=10
        )
        
        logger.info(f"Response status: {response.status_code}")
        logger.info(f"Response headers: {dict(response.headers)}")
        
        if response.status_code == 200:
            data = response.json()
            logger.info(f"Response data: {json.dumps(data, indent=2)}")
            
            if data.get('success'):
                practitioners = data.get('practitioners', [])
                logger.info(f"Found {len(practitioners)} practitioners:")
                for p in practitioners:
                    logger.info(f"  - {p.get('name')} (ID: {p.get('id')})")
            else:
                logger.error(f"Request failed: {data.get('message')}")
        else:
            logger.error(f"HTTP {response.status_code}: {response.text}")
            
    except Exception as e:
        logger.error(f"Request failed with exception: {e}")

if __name__ == "__main__":
    test_get_location_practitioners() 