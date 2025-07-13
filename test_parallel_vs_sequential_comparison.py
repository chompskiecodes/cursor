
"""
Parallel vs Sequential Endpoint Comparison Test

This test compares the old sequential endpoints with the new parallel endpoints
to verify blackbox equivalence and measure performance improvements.
"""

import os
import sys
import requests
import random
import time
from datetime import datetime, timedelta
import json
from dotenv import load_dotenv
import logging
from pathlib import Path
import pytest

# Load environment variables
load_dotenv()

# Set up logging directory
LOG_DIR = Path("booking_test_logs")
LOG_DIR.mkdir(exist_ok=True)

timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
log_file = LOG_DIR / f"parallel_vs_sequential_comparison_{timestamp}.log"

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_file),
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger(__name__)
logger.info(f"Starting parallel vs sequential comparison test - Log file: {log_file}")

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
TEST_PATIENT_NAME = "Test Patient Comparison"
TEST_PATIENT_PHONE = "0412345678"
TEST_CALLER_PHONE = "0412345678"
SESSION_ID = "test_comparison_123"

# Example hardcoded values for City Clinic
BUSINESS_ID = "1701928805762869230"
BUSINESS_NAME = "City Clinic"
PRACTITIONER_NAME = "Brendan Smith"
APPOINTMENT_TYPE = "Acupuncture (Initial)"
# 4 weeks in the future from 2025-07-14
DATES = ["2025-08-11", "2025-08-12", "2025-08-13"]


class ComparisonResult:
    """Track comparison results for each endpoint pair"""
    def __init__(self, endpoint_name):
        self.endpoint_name = endpoint_name
        self.sequential_success = False
        self.parallel_success = False
        self.sequential_response = None
        self.parallel_response = None
        self.sequential_time = 0
        self.parallel_time = 0
        self.responses_match = False
        self.performance_improvement = 0
        self.error = None

    def set_results(self, seq_response, par_response, seq_time, par_time):
        self.sequential_response = seq_response
        self.parallel_response = par_response
        self.sequential_time = seq_time
        self.parallel_time = par_time
        
        # Check if both succeeded
        if seq_response and par_response:
            self.sequential_success = seq_response.get('success', False)
            self.parallel_success = par_response.get('success', False)
            
            # Compare response structure (excluding performance metrics)
            seq_clean = self._clean_response_for_comparison(seq_response)
            par_clean = self._clean_response_for_comparison(par_response)
            self.responses_match = seq_clean == par_clean
            
            # Calculate performance improvement
            if seq_time > 0:
                self.performance_improvement = ((seq_time - par_time) / seq_time) * 100

    def _clean_response_for_comparison(self, response):
        """Remove performance metrics and other non-business-logic fields for comparison"""
        if not response:
            return response
        
        # Create a copy and remove performance-related fields
        cleaned = response.copy()
        cleaned.pop('performance_metrics', None)
        cleaned.pop('execution_time', None)
        cleaned.pop('total_calls', None)
        cleaned.pop('successful_calls', None)
        cleaned.pop('failed_calls', None)
        cleaned.pop('cache_hits', None)
        cleaned.pop('average_duration', None)
        cleaned.pop('rate_limit_delays', None)
        cleaned.pop('success_rate', None)
        
        return cleaned

    def set_error(self, error):
        self.error = error


def make_timed_request(endpoint, payload, webhook_name):
    """Make a webhook request and return response with timing"""
    logger.info(f"Making request to {webhook_name}")
    logger.info(f"Endpoint: {endpoint}")
    logger.info(f"Payload: {json.dumps(payload, indent=2)}")
    
    start_time = time.time()
    
    try:
        response = requests.post(
            f'{WEBHOOK_BASE_URL}{endpoint}',
            headers=webhook_headers,
            json=payload,
            timeout=120  # Increased timeout for parallel endpoints
        )
        
        end_time = time.time()
        duration = end_time - start_time
        
        logger.info(f"Status: {response.status_code}")
        logger.info(f"Duration: {duration:.2f}s")
        logger.info(f"Response: {response.text[:500]}...")  # Truncate long responses
        
        if response.status_code == 200:
            return response.json(), duration, None
        else:
            return None, duration, f"HTTP {response.status_code}"
            
    except Exception as e:
        end_time = time.time()
        duration = end_time - start_time
        return None, duration, str(e)


def test_find_next_available_comparison(practitioner_name=None, service_name=None, location_id=None, location_name=None):
    """Compare find-next-available endpoints"""
    logger.info("\n" + "="*60)
    logger.info("TESTING: find-next-available vs enhanced/find-next-available")
    logger.info("="*60)
    
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
    
    # Test sequential endpoint
    seq_response, seq_time, seq_error = make_timed_request(
        "/find-next-available", payload, "find-next-available (sequential)"
    )
    
    # Test parallel endpoint
    par_response, par_time, par_error = make_timed_request(
        "/enhanced/find-next-available", payload, "enhanced/find-next-available (parallel)"
    )
    
    result = ComparisonResult("find-next-available")
    
    if seq_error or par_error:
        result.set_error(f"Sequential error: {seq_error}, Parallel error: {par_error}")
    else:
        result.set_results(seq_response, par_response, seq_time, par_time)
    
    return result


def write_summary_to_file(summary: str):
    with open("timing_summary.txt", "a", encoding="utf-8") as f:
        f.write("\n" + "*" * 60 + "\n")
        f.write(summary)
        f.write("\n" + "*" * 60 + "\n")

@pytest.mark.parametrize("business_id, business_name, date_str", [
    (BUSINESS_ID, BUSINESS_NAME, d) for d in DATES
])
def test_get_available_practitioners_comparison(business_id, business_name, date_str, _timings=[]):
    """Compare get-available-practitioners endpoints"""
    logger.info("\n" + "="*60)
    logger.info("TESTING: get-available-practitioners vs enhanced/get-available-practitioners")
    logger.info("="*60)
    
    payload = {
        "business_id": business_id,
        "businessName": business_name,
        "date": date_str,
        "dialedNumber": TEST_DIALED_NUMBER,
        "sessionId": SESSION_ID
    }
        
        # Test sequential endpoint
    seq_response, seq_time, seq_error = make_timed_request(
        "/get-available-practitioners", payload, "get-available-practitioners (sequential)"
    )
        
        # Test parallel endpoint  
    par_response, par_time, par_error = make_timed_request(
        "/enhanced/get-available-practitioners", payload, "enhanced/get-available-practitioners (parallel)"
    )
    
    result = ComparisonResult("get-available-practitioners")
    
    if seq_error or par_error:
        result.set_error(f"Sequential error: {seq_error}, Parallel error: {par_error}")
    else:
        result.set_results(seq_response, par_response, seq_time, par_time)
    
    return result


@pytest.mark.parametrize("practitioner_name, appointment_type, date_str, business_id", [
    (PRACTITIONER_NAME, APPOINTMENT_TYPE, d, BUSINESS_ID) for d in DATES
])
def test_availability_checker_comparison(practitioner_name, appointment_type, date_str, business_id, _timings=[]):
    """Compare availability-checker endpoints (if parallel version exists)"""
    logger.info("\n" + "="*60)
    logger.info("TESTING: availability-checker (sequential only - no parallel version)")
    logger.info("="*60)
    
    payload = {
        "practitioner": practitioner_name,
        "appointmentType": appointment_type,
        "date": date_str,
        "sessionId": SESSION_ID,
        "dialedNumber": TEST_DIALED_NUMBER
    }
    if business_id:
        payload["business_id"] = business_id
    
    # Test sequential endpoint only
    seq_response, seq_time, seq_error = make_timed_request(
        "/availability-checker", payload, "availability-checker (sequential)"
    )
    
    result = ComparisonResult("availability-checker")
    if seq_error:
        result.set_error(f"Sequential error: {seq_error}")
    else:
        result.sequential_success = seq_response.get('success', False) if seq_response else False
        result.sequential_response = seq_response
        result.sequential_time = seq_time
    
    return result


def main():
    logger.info("=== PARALLEL VS SEQUENTIAL ENDPOINT COMPARISON ===")
    logger.info(f"Webhook API: {WEBHOOK_BASE_URL}")
    logger.info(f"Test phone number: {TEST_DIALED_NUMBER}")
    
    results = {}

    # Fallbacks
    fallback_location_id = "1717010852512540252"
    fallback_location_name = TEST_LOCATIONS[0]
    fallback_practitioner = "Brendan Smith"
    fallback_service = "Massage"
    fallback_date = (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d')

    # Get location and practitioner info first
    logger.info("\n" + "="*60)
    logger.info("SETTING UP TEST DATA")
    logger.info("="*60)
    
    # Get location info
    location_payload = {
        "locationQuery": random.choice(TEST_LOCATIONS),
        "sessionId": SESSION_ID,
        "dialedNumber": TEST_DIALED_NUMBER,
        "callerPhone": TEST_CALLER_PHONE
    }
    
    location_response, _, _ = make_timed_request("/location-resolver", location_payload, "location-resolver")
    
    location_id = fallback_location_id
    location_name = fallback_location_name
    practitioner_name = fallback_practitioner
    appointment_type = fallback_service
    
    if location_response and location_response.get('success'):
        data = location_response.get('data', {})
        if data.get('business_id'):
            location_id = data['business_id']
        if data.get('businessName'):
            location_name = data['businessName']
    
    # Get practitioner info
    practitioner_payload = {
        "business_id": location_id,
        "businessName": location_name,
        "dialedNumber": TEST_DIALED_NUMBER,
        "sessionId": SESSION_ID
    }
    
    practitioner_response, _, _ = make_timed_request("/get-location-practitioners", practitioner_payload, "get-location-practitioners")
    
    if practitioner_response and practitioner_response.get('success'):
        practitioners = practitioner_response.get('practitioners', [])
        if practitioners:
            practitioner_name = practitioners[0].get('name') if isinstance(practitioners[0], dict) else practitioners[0]
    
    # Get service info
    service_payload = {
        "practitioner": practitioner_name,
        "dialedNumber": TEST_DIALED_NUMBER,
        "sessionId": SESSION_ID
    }
    
    service_response, _, _ = make_timed_request("/get-practitioner-services", service_payload, "get-practitioner-services")
    
    if service_response and service_response.get('success'):
        services = service_response.get('services', [])
        if services:
            appointment_type = services[0].get('service_name') if isinstance(services[0], dict) else services[0]
    
    logger.info(f"Using test data:")
    logger.info(f"  Location: {location_name} ({location_id})")
    logger.info(f"  Practitioner: {practitioner_name}")
    logger.info(f"  Service: {appointment_type}")
    logger.info(f"  Date: {fallback_date}")
    
    # Run comparison tests
    logger.info("\n" + "="*60)
    logger.info("RUNNING COMPARISON TESTS")
    logger.info("="*60)
    
    # Test 1: find-next-available
    results['find_next_available'] = test_find_next_available_comparison(
        practitioner_name, appointment_type, location_id, location_name
    )
    
    # Test 2: get-available-practitioners
    results['get_available_practitioners'] = test_get_available_practitioners_comparison(
        location_id, location_name, fallback_date
    )
    
    # Test 3: availability-checker (sequential only)
    results['availability_checker'] = test_availability_checker_comparison(
        practitioner_name, appointment_type, fallback_date, location_id
    )
    
    # Summary
    logger.info("\n" + "="*60)
    logger.info("COMPARISON SUMMARY")
    logger.info("="*60)
    
    total_tests = len(results)
    successful_comparisons = 0
    performance_improvements = []
    
    for test_name, result in results.items():
        logger.info(f"\n{test_name}:")
        
        if result.error:
            logger.info(f"  ❌ ERROR: {result.error}")
            continue
        
        if test_name == 'availability_checker':
            # Sequential only test
            if result.sequential_success:
                logger.info(f"  ✅ Sequential: SUCCESS ({result.sequential_time:.2f}s)")
                logger.info(f"  ⚠️  Parallel: Not available")
            else:
                logger.info(f"  ❌ Sequential: FAILED ({result.sequential_time:.2f}s)")
        else:
            # Comparison test
            if result.sequential_success and result.parallel_success:
                if result.responses_match:
                    logger.info(f"  ✅ Sequential: SUCCESS ({result.sequential_time:.2f}s)")
                    logger.info(f"  ✅ Parallel: SUCCESS ({result.parallel_time:.2f}s)")
                    logger.info(f"  ✅ Responses: MATCH")
                    
                    if result.performance_improvement > 0:
                        logger.info(f"  🚀 Performance: {result.performance_improvement:.1f}% faster")
                        performance_improvements.append(result.performance_improvement)
                    else:
                        logger.info(f"  ⚠️  Performance: {abs(result.performance_improvement):.1f}% slower")
                    
                    successful_comparisons += 1
                else:
                    logger.info(f"  ✅ Sequential: SUCCESS ({result.sequential_time:.2f}s)")
                    logger.info(f"  ✅ Parallel: SUCCESS ({result.parallel_time:.2f}s)")
                    logger.info(f"  ❌ Responses: DO NOT MATCH")
                    logger.info(f"  Sequential response: {json.dumps(result.sequential_response, indent=2)}")
                    logger.info(f"  Parallel response: {json.dumps(result.parallel_response, indent=2)}")
            else:
                logger.info(f"  ❌ Sequential: {'SUCCESS' if result.sequential_success else 'FAILED'} ({result.sequential_time:.2f}s)")
                logger.info(f"  ❌ Parallel: {'SUCCESS' if result.parallel_success else 'FAILED'} ({result.parallel_time:.2f}s)")
    
    # Overall summary
    logger.info("\n" + "="*60)
    logger.info("OVERALL RESULTS")
    logger.info("="*60)
    
    logger.info(f"Successful comparisons: {successful_comparisons}/{total_tests}")
    
    if performance_improvements:
        avg_improvement = sum(performance_improvements) / len(performance_improvements)
        logger.info(f"Average performance improvement: {avg_improvement:.1f}%")
        logger.info(f"Best improvement: {max(performance_improvements):.1f}%")
    
    if successful_comparisons == total_tests:
        logger.info("\n🎉 ALL COMPARISONS PASSED - PARALLEL ENDPOINTS ARE FUNCTIONALLY EQUIVALENT!")
    else:
        logger.info(f"\n⚠️  {total_tests - successful_comparisons} comparisons failed")
    
    logger.info(f"\nDetailed results saved to: {log_file}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        logger.error(f"Unhandled exception: {e}", exc_info=True)
        logger.error(f"\nCheck log file for details: {log_file}") 