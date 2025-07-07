#!/usr/bin/env python3
"""
Webhook-first booking test:
1. Checks availability via /availability-checker webhook
2. Books the appointment via /appointment-handler webhook
"""

import os
import sys
import requests
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
log_file = LOG_DIR / f"booking_test_{timestamp}.log"

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_file),
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger(__name__)
logger.info(f"Starting webhook booking test - Log file: {log_file}")

# Configuration
WEBHOOK_BASE_URL = os.getenv('WEBHOOK_BASE_URL', 'http://localhost:8000')
WEBHOOK_API_KEY = os.getenv('API_KEY', 'development-key')
TEST_DIALED_NUMBER = '0478621276'  # Matches clinics table

webhook_headers = {
    'X-API-Key': WEBHOOK_API_KEY,
    'Content-Type': 'application/json'
}


def check_availability():
    """Call the webhook's availability checker, searching up to 7 days ahead for an available slot."""
    for day_offset in range(1, 8):  # Next 7 days
        check_date = (datetime.now() + timedelta(days=day_offset)).strftime('%Y-%m-%d')
        payload = {
            "practitioner": "Brendan Smith",
            "appointmentType": "Massage",
            "date": check_date,
            "sessionId": "test_booking_123",
            "dialedNumber": TEST_DIALED_NUMBER
        }
        logger.info(f"\n--- Step 1: Check Availability via Webhook (date: {check_date}) ---")
        logger.info(f"Payload: {json.dumps(payload, indent=2)}")
        try:
            response = requests.post(
                f'{WEBHOOK_BASE_URL}/availability-checker',
                headers=webhook_headers,
                json=payload
            )
            logger.info(f"Status: {response.status_code}")
            logger.info(f"Response: {response.text}")
            if response.status_code != 200:
                logger.error("Availability check failed.")
                continue
            result = response.json()
            if not result.get('success'):
                logger.error(f"Availability check not successful: {result.get('message')}")
                continue
            if result.get('disambiguation_needed') or result.get('needsClarification'):
                logger.warning(f"Clarification needed: {result.get('message')}")
                continue
            slots = result.get('slots') or result.get('availability', {}).get('slots')
            if not slots:
                logger.error("No available slots returned.")
                continue
            first_slot = slots[0]
            if isinstance(first_slot, dict):
                time_str = first_slot.get('time') or first_slot.get('displayTime') or str(first_slot)
            else:
                time_str = str(first_slot)
            location_id = result.get('location_id') or result.get('location', {}).get('id')
            location_name = result.get('location_name') or result.get('location', {}).get('name')
            return {
                'date': check_date,
                'time': time_str,
                'location_id': location_id,
                'location_name': location_name
            }
        except Exception as e:
            logger.error(f"Exception in check_availability: {e}")
            continue
    logger.error("No available times found in the next 7 days.")
    return None


def book_appointment(availability):
    """Book appointment using the webhook"""
    logger.info("\n--- Step 2: Book Appointment via Webhook ---")
    # Use a realistic patient (simulate agent behavior)
    booking_payload = {
        "action": "book",
        "sessionId": "test_booking_123",
        "dialedNumber": TEST_DIALED_NUMBER,
        "callerPhone": "0412345678",
        "patientName": "Test Patient",
        "patientPhone": "0412345678",
        "practitioner": "Brendan Smith",
        "appointmentType": "Massage",
        "appointmentDate": availability['date'],
        "appointmentTime": availability['time'],
        # Only include location fields if present
    }
    if availability.get('location_id'):
        booking_payload['locationId'] = availability['location_id']
    if availability.get('location_name'):
        booking_payload['location'] = availability['location_name']
    logger.info(f"Booking payload: {json.dumps(booking_payload, indent=2)}")
    try:
        response = requests.post(
            f'{WEBHOOK_BASE_URL}/appointment-handler',
            headers=webhook_headers,
            json=booking_payload
        )
        logger.info(f"Status: {response.status_code}")
        logger.info(f"Response: {response.text}")
        if response.status_code != 200:
            logger.error("Booking failed.")
            return False
        result = response.json()
        if result.get('success'):
            logger.info("BOOKING SUCCESSFUL!")
            logger.info(f"Message: {result.get('message')}")
            if 'appointmentDetails' in result:
                logger.info(f"Appointment Details: {json.dumps(result['appointmentDetails'], indent=2)}")
            return True
        else:
            logger.error(f"Booking failed: {result.get('message')}")
            logger.error(f"Error details: {result.get('error')}")
            return False
    except Exception as e:
        logger.error(f"Exception in book_appointment: {e}")
        return False


def main():
    logger.info("=== Webhook-First Booking Test ===")
    logger.info(f"Webhook API: {WEBHOOK_BASE_URL}")
    logger.info(f"Test phone number: {TEST_DIALED_NUMBER}")
    # Step 1: Check availability
    availability = check_availability()
    if not availability:
        logger.error("Test failed: No available times found or clarification needed.")
        return
    # Step 2: Book appointment
    success = book_appointment(availability)
    if success:
        logger.info("\nTEST COMPLETED SUCCESSFULLY!")
        logger.info(f"\nTest results saved to: {log_file}")
    else:
        logger.error("\nTEST FAILED!")
        logger.error(f"\nCheck log file for details: {log_file}")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        logger.error(f"Unhandled exception: {e}", exc_info=True)
        logger.error(f"\nCheck log file for details: {log_file}")
