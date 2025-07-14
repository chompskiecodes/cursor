"""
Comprehensive webhook test that covers all 10 webhook endpoints:
1. location-resolver
2. confirm-location  
3. get-location-practitioners
4. get-practitioner-services
5. get-practitioner-info
6. get-available-practitioners
7. availability-checker
8. find-next-available
9. appointment-handler
10. cancel-appointment

This test simulates a complete booking flow and tests all webhooks.
"""

import os
import sys
import requests
import random
from datetime import datetime, timedelta
import json
from dotenv import load_dotenv
import logging
from pathlib import Path

# Load environment variables
load_dotenv()

# Set up logging directory
LOG_DIR = Path("booking_test_logs")
LOG_DIR.mkdir(exist_ok=True)

timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
log_file = LOG_DIR / f"test_all_webhooks_{timestamp}.log"

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_file),
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger(__name__)
logger.info(f"Starting comprehensive webhook test - Log file: {log_file}")

# Configuration
WEBHOOK_BASE_URL = os.getenv('WEBHOOK_BASE_URL', 'http://localhost:8000')
WEBHOOK_API_KEY = os.getenv('API_KEY', 'development-key')
TEST_DIALED_NUMBER = '0478621276'  # Matches clinics table

webhook_headers = {
    'X-API-Key': WEBHOOK_API_KEY,
    'Content-Type': 'application/json'
}

# Test data - these should match your database
TEST_LOCATIONS = ["City Clinic", "Balmain", "Location 2"]
TEST_PATIENT_NAME = "Test Patient Comprehensive"
TEST_PATIENT_PHONE = "0412345678"
TEST_CALLER_PHONE = "0412345678"
SESSION_ID = "test_comprehensive_123"


class WebhookTestResult:
    """Track test results for each webhook"""
    def __init__(self, webhook_name):
        self.webhook_name = webhook_name
        self.success = False
        self.response = None
        self.error = None
        self.data = None

    def set_success(self, response, data=None):
        self.success = True
        self.response = response
        self.data = data

    def set_error(self, response, error):
        self.success = False
        self.response = response
        self.error = error


def make_webhook_request(endpoint, payload, webhook_name):
    """Make a webhook request and return result"""
    logger.info(f"\n--- Testing {webhook_name} ---")
    logger.info(f"Endpoint: {endpoint}")
    logger.info(f"Payload: {json.dumps(payload, indent=2)}")
    
    result = WebhookTestResult(webhook_name)
    
    try:
        response = requests.post(
            f'{WEBHOOK_BASE_URL}{endpoint}',
            headers=webhook_headers,
            json=payload,
            timeout=30
        )
        
        logger.info(f"Status: {response.status_code}")
        logger.info(f"Response: {response.text}")
        
        if response.status_code == 200:
            result_data = response.json()
            # Special logic for booking: pass if time_not_available and alternatives are offered
            if webhook_name == "appointment_handler_book":
                if result_data.get('success') or (
                    result_data.get('error') == 'time_not_available' and result_data.get('availableTimes')
                ):
                    result.set_success(response, result_data)
                    logger.info(f"SUCCESS: {webhook_name}")
                else:
                    result.set_error(response, result_data.get('message', 'Unknown error'))
                    logger.error(f"FAILED: {webhook_name} - {result.error}")
            else:
                if result_data.get('success'):
                    result.set_success(response, result_data)
                    logger.info(f"SUCCESS: {webhook_name}")
                else:
                    result.set_error(response, result_data.get('message', 'Unknown error'))
                    logger.error(f"FAILED: {webhook_name} - {result.error}")
        else:
            result.set_error(response, f"HTTP {response.status_code}")
            logger.error(f"HTTP ERROR: {webhook_name} - {response.status_code}")
            
    except Exception as e:
        result.set_error(None, str(e))
        logger.error(f"EXCEPTION: {webhook_name} - {e}")
    
    return result


def test_location_resolver():
    """Test 1: location-resolver"""
    payload = {
        "locationQuery": random.choice(TEST_LOCATIONS),
        "sessionId": SESSION_ID,
        "dialedNumber": TEST_DIALED_NUMBER,
        "callerPhone": TEST_CALLER_PHONE
    }
    return make_webhook_request("/location-resolver", payload, "location-resolver")


def test_confirm_location(location_options):
    """Test 2: confirm-location"""
    if not location_options:
        logger.warning("No location options available for confirm-location test")
        return WebhookTestResult("confirm-location")
    
    # Simulate user choosing the first option
    user_response = location_options[0] if isinstance(location_options[0], str) else location_options[0].get('name', '')
    
    payload = {
        "userResponse": user_response,
        "options": location_options,
        "sessionId": SESSION_ID,
        "dialedNumber": TEST_DIALED_NUMBER,
        "callerPhone": TEST_CALLER_PHONE
    }
    return make_webhook_request("/confirm-location", payload, "confirm-location")


def test_get_location_practitioners(location_id, location_name):
    """Test 3: get-location-practitioners"""
    payload = {
        "business_id": location_id,
        "businessName": location_name,
        "dialedNumber": TEST_DIALED_NUMBER,
        "sessionId": SESSION_ID
    }
    return make_webhook_request("/get-location-practitioners", payload, "get-location-practitioners")


def test_get_practitioner_services(practitioner_name, business_id=None):
    """Test 4: get-practitioner-services"""
    payload = {
        "practitioner": practitioner_name,
        "dialedNumber": TEST_DIALED_NUMBER,
        "sessionId": SESSION_ID
    }
    if business_id:
        payload["business_id"] = business_id
    
    return make_webhook_request("/get-practitioner-services", payload, "get-practitioner-services")


def test_get_practitioner_info(practitioner_name, business_name=None):
    """Test 5: get-practitioner-info"""
    payload = {
        "practitioner": practitioner_name,
        "dialedNumber": TEST_DIALED_NUMBER,
        "sessionId": SESSION_ID
    }
    if business_name:
        payload["businessName"] = business_name
    return make_webhook_request("/get-practitioner-info", payload, "get-practitioner-info")


def test_get_available_practitioners(business_id, business_name, date_str):
    """Test 6: get-available-practitioners"""
    payload = {
        "business_id": business_id,
        "businessName": business_name,
        "date": date_str,
        "dialedNumber": TEST_DIALED_NUMBER,
        "sessionId": SESSION_ID
    }
    return make_webhook_request("/get-available-practitioners", payload, "get-available-practitioners")


def test_availability_checker(practitioner_name, appointment_type, date_str, business_id=None):
    """Test 7: availability-checker"""
    payload = {
        "practitioner": practitioner_name,
        "appointmentType": appointment_type,
        "date": date_str,
        "sessionId": SESSION_ID,
        "dialedNumber": TEST_DIALED_NUMBER
    }
    if business_id:
        payload["business_id"] = business_id
    
    return make_webhook_request("/availability-checker", payload, "availability-checker")


def test_find_next_available(practitioner_name=None, service_name=None, location_id=None, location_name=None):
    payload = {
        "sessionId": SESSION_ID,
        "dialedNumber": TEST_DIALED_NUMBER,
        "maxDays": 14
    }
    if practitioner_name:
        payload["practitioner"] = practitioner_name
    if service_name:
        payload["service"] = service_name
    if location_id:
        payload["locationId"] = location_id
    if location_name:
        payload["locationName"] = location_name
    return make_webhook_request("/find-next-available", payload, "find_next_available_any_practitioner")


def test_appointment_handler(action, appointment_data):
    payload = appointment_data.copy()
    payload["action"] = action
    payload["sessionId"] = SESSION_ID
    payload["dialedNumber"] = TEST_DIALED_NUMBER
    return make_webhook_request("/appointment-handler", payload, "appointment_handler_book")


def main():
    logger.info("=== FULL WEBHOOK TEST: ALL 10 ENDPOINTS ===")
    logger.info(f"Webhook API: {WEBHOOK_BASE_URL}")
    logger.info(f"Test phone number: {TEST_DIALED_NUMBER}")
    
    results = {}

    # Fallbacks
    fallback_location_id = "1717010852512540252"
    fallback_location_name = TEST_LOCATIONS[0]
    fallback_practitioner = "Brendan Smith"
    fallback_service = "Massage"
    fallback_date = (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d')

    # 1. location-resolver
    loc_res_result = test_location_resolver()
    results['location_resolver'] = loc_res_result
    location_options = None
    location_id = None
    location_name = None
    practitioner_name = None
    appointment_type = None
    if loc_res_result.success and loc_res_result.data:
        data = loc_res_result.data
        if data.get('needs_clarification') and data.get('options'):
            location_options = data['options']
        elif data.get('business_id') or data.get('location_id'):
            location_id = data.get('business_id') or data.get('location_id')
            location_name = data.get('businessName') or data.get('locationName') or fallback_location_name
    if not location_id:
        logger.info(f"[Fallback] Using default location_id: {fallback_location_id}")
        location_id = fallback_location_id
    if not location_name:
        logger.info(f"[Fallback] Using default location_name: {fallback_location_name}")
        location_name = fallback_location_name
    
    # 2. confirm-location
    if location_options:
        conf_loc_result = test_confirm_location(location_options)
        results['confirm_location'] = conf_loc_result
        if conf_loc_result.success and conf_loc_result.data:
            location_id = conf_loc_result.data.get('business_id') or conf_loc_result.data.get('location_id') or location_id
            location_name = conf_loc_result.data.get('businessName') or conf_loc_result.data.get('locationName') or location_name
    else:
        logger.info(f"[Fallback] Skipping confirm-location, no options. Using location_id: {location_id}, location_name: {location_name}")
        results['confirm_location'] = WebhookTestResult('confirm-location')

    # 3. get-location-practitioners
    get_loc_prac_result = test_get_location_practitioners(location_id, location_name)
    results['get_location_practitioners'] = get_loc_prac_result
    if get_loc_prac_result.success and get_loc_prac_result.data:
        practitioners = get_loc_prac_result.data.get('practitioners')
        if practitioners and isinstance(practitioners, list):
            practitioner_name = practitioners[0].get('name') if isinstance(practitioners[0], dict) else practitioners[0]
    if not practitioner_name:
        logger.info(f"[Fallback] Using default practitioner: {fallback_practitioner}")
        practitioner_name = fallback_practitioner

    # 4. get-practitioner-services
    get_prac_serv_result = test_get_practitioner_services(practitioner_name, location_id)
    results['get_practitioner_services'] = get_prac_serv_result
    if get_prac_serv_result.success and get_prac_serv_result.data:
        services = get_prac_serv_result.data.get('services')
        if services and isinstance(services, list) and services:
            # If service is a dict, extract the name for endpoints that expect a string
            if isinstance(services[0], dict):
                appointment_type = services[0].get('service_name') or services[0].get('name') or fallback_service
            else:
                appointment_type = services[0]
    if not appointment_type:
        logger.info(f"[Fallback] Using default service: {fallback_service}")
        appointment_type = fallback_service

    # 5. get-practitioner-info
    get_prac_info_result = test_get_practitioner_info(practitioner_name, location_name)
    results['get_practitioner_info'] = get_prac_info_result

    # 6. get-available-practitioners
    get_avail_prac_result = test_get_available_practitioners(location_id, location_name, fallback_date)
    results['get_available_practitioners'] = get_avail_prac_result

    # 7. availability-checker
    avail_checker_result = test_availability_checker(practitioner_name, appointment_type, fallback_date, location_id)
    results['availability_checker'] = avail_checker_result

    # 8. find-next-available
    find_next_result = test_find_next_available(practitioner_name, appointment_type, location_id, location_name)
    results['find_next_available'] = find_next_result

    # 9. appointment-handler (book)
    booking_data = {
        "patientName": TEST_PATIENT_NAME,
        "patientPhone": TEST_PATIENT_PHONE,
        "practitioner": practitioner_name,
        # Always send appointmentType as a string, not a dict
        "appointmentType": appointment_type if isinstance(appointment_type, str) else (appointment_type.get('service_name') if isinstance(appointment_type, dict) else fallback_service),
        "appointmentDate": fallback_date,
        "appointmentTime": "14:00",
        "business_id": location_id,
        "location": location_name
    }
    booking_result = test_appointment_handler("book", booking_data)
    results['appointment_handler_book'] = booking_result

    # 10. cancel-appointment
    cancel_payload = {
        "sessionId": SESSION_ID,
        "dialedNumber": TEST_DIALED_NUMBER,
        "callerPhone": TEST_CALLER_PHONE,
        # Use the string service name in appointmentDetails
        "appointmentDetails": f"{booking_data['appointmentType']} with {booking_data['practitioner']} on {booking_data['appointmentDate']} at {booking_data['appointmentTime']}"
    }
    cancel_result = make_webhook_request("/cancel-appointment", cancel_payload, "cancel_appointment")
    results['cancel_appointment'] = cancel_result

    # Summary
    logger.info("\n" + "="*50)
    logger.info("TEST SUMMARY")
    logger.info("="*50)

    successful_tests = 0
    total_tests = len(results)

    for test_name, result in results.items():
        status = "PASS" if result.success else "FAIL"
        logger.info(f"{test_name}: {status}")
        if result.success:
            successful_tests += 1
        else:
            logger.info(f"  Error: {result.error}")

    logger.info(f"\nOverall: {successful_tests}/{total_tests} tests passed")

    if successful_tests == total_tests:
        logger.info("\nALL WEBHOOK TESTS PASSED!")
    else:
        logger.info(f"\n{total_tests - successful_tests} tests failed")

    logger.info(f"\nDetailed results saved to: {log_file}")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        logger.error(f"Unhandled exception: {e}", exc_info=True)
        logger.error(f"\nCheck log file for details: {log_file}") 