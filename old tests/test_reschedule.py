#!/usr/bin/env python3
"""
Webhook-first reschedule test:
Reschedules a booking via /appointment-handler webhook (action: reschedule)
"""

import os
import sys
import requests
from datetime import datetime
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
log_file = LOG_DIR / f"test_reschedule_{timestamp}.log"

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_file),
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger(__name__)
logger.info(f"Starting webhook reschedule test - Log file: {log_file}")

# Configuration
WEBHOOK_BASE_URL = os.getenv('WEBHOOK_BASE_URL', 'http://localhost:8000')
WEBHOOK_API_KEY = os.getenv('API_KEY', 'development-key')
TEST_DIALED_NUMBER = '0478621276'  # Matches clinics table

webhook_headers = {
    'X-API-Key': WEBHOOK_API_KEY,
    'Content-Type': 'application/json'
}

APPOINTMENT_ID = '1723218736460080245'
RESCHEDULE_DATE = '2025-07-07'
PREFERRED_TIME = '14:00'  # 2:00 PM

PATIENT_PHONE = '0412345678'
CALLER_PHONE = '0412345678'
SESSION_ID = 'test_booking_123'

PRACTITIONER = 'Brendan Smith'
APPOINTMENT_TYPE = 'Massage'


def check_availability():
    """Check for available slots and return the next available time (as HH:MM) or None."""
    payload = {
        "practitioner": PRACTITIONER,
        "appointmentType": APPOINTMENT_TYPE,
        "date": RESCHEDULE_DATE,
        "sessionId": SESSION_ID,
        "dialedNumber": TEST_DIALED_NUMBER
    }
    logger.info(f"\n--- Check Availability for {RESCHEDULE_DATE} ---")
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
            return None
        result = response.json()
        if not result.get('success'):
            logger.error(f"Availability check not successful: {result.get('message')}")
            return None
        # Updated slot extraction logic: check for 'available_times' as well as 'slots'
        slots = (
            result.get('slots')
            or result.get('available_times')
            or result.get('availability', {}).get('slots')
        )
        if not slots:
            logger.error("No available slots returned.")
            return None
        # Try to find preferred time first
        for slot in slots:
            slot_time = slot.get('time') if isinstance(slot, dict) else slot
            slot_time = slot_time or (slot.get('displayTime') if isinstance(slot, dict) else None)
            slot_time = slot_time or (slot.get('start') if isinstance(slot, dict) else None)
            if slot_time and PREFERRED_TIME in slot_time:
                logger.info(f"Preferred time {PREFERRED_TIME} is available.")
                return PREFERRED_TIME
        # Otherwise, return the next available slot
        next_slot = slots[0]
        next_time = next_slot.get('time') if isinstance(next_slot, dict) else next_slot
        next_time = next_time or (next_slot.get('displayTime') if isinstance(next_slot, dict) else None)
        next_time = next_time or (next_slot.get('start') if isinstance(next_slot, dict) else None)
        logger.info(f"Preferred time not available. Next available time: {next_time}")
        return next_time
    except Exception as e:
        logger.error(f"Exception in check_availability: {e}")
        return None


def reschedule_appointment(new_time):
    logger.info(f"\n--- Step: Reschedule Appointment to {new_time} via Webhook ---")
    reschedule_payload = {
        "action": "reschedule",
        "sessionId": SESSION_ID,
        "dialedNumber": TEST_DIALED_NUMBER,
        "callerPhone": CALLER_PHONE,
        "appointmentId": APPOINTMENT_ID,
        "newDate": RESCHEDULE_DATE,
        "newTime": new_time,
        "practitioner": PRACTITIONER,
        "appointmentType": APPOINTMENT_TYPE
    }
    logger.info(f"Reschedule payload: {json.dumps(reschedule_payload, indent=2)}")
    try:
        response = requests.post(
            f'{WEBHOOK_BASE_URL}/appointment-handler',
            headers=webhook_headers,
            json=reschedule_payload
        )
        logger.info(f"Status: {response.status_code}")
        logger.info(f"Response: {response.text}")
        if response.status_code != 200:
            logger.error("Reschedule failed.")
            return False
        result = response.json()
        if result.get('success'):
            logger.info("RESCHEDULE SUCCESSFUL!")
            logger.info(f"Message: {result.get('message')}")
            if 'appointmentDetails' in result:
                logger.info(f"Appointment Details: {json.dumps(result['appointmentDetails'], indent=2)}")
            return True
        else:
            logger.error(f"Reschedule failed: {result.get('message')}")
            logger.error(f"Error details: {result.get('error')}")
            return False
    except Exception as e:
        logger.error(f"Exception in reschedule_appointment: {e}")
        return False


def main():
    logger.info("=== Webhook-First Reschedule Test ===")
    logger.info(f"Webhook API: {WEBHOOK_BASE_URL}")
    logger.info(f"Test phone number: {TEST_DIALED_NUMBER}")
    # Step 1: Find the next available time (prefer 2:00 PM)
    next_time = check_availability()
    if next_time:
        success = reschedule_appointment(next_time)
        if success:
            logger.info("\nRESCHEDULE TEST COMPLETED SUCCESSFULLY!")
            logger.info(f"\nTest results saved to: {log_file}")
            return
    logger.error("\nRESCHEDULE TEST FAILED! No available times found.")
    logger.error(f"\nCheck log file for details: {log_file}")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        logger.error(f"Unhandled exception: {e}", exc_info=True)
        logger.error(f"\nCheck log file for details: {log_file}")
