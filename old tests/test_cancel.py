#!/usr/bin/env python3
"""
Webhook-first cancel test:
Cancels a booking via /cancel-appointment webhook
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
log_file = LOG_DIR / f"test_cancel_{timestamp}.log"

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_file),
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger(__name__)
logger.info(f"Starting webhook cancel test - Log file: {log_file}")

# Configuration
WEBHOOK_BASE_URL = os.getenv('WEBHOOK_BASE_URL', 'http://localhost:8000')
WEBHOOK_API_KEY = os.getenv('API_KEY', 'development-key')
TEST_DIALED_NUMBER = '0478621276'  # Matches clinics table

webhook_headers = {
    'X-API-Key': WEBHOOK_API_KEY,
    'Content-Type': 'application/json'
}

# Use the appointmentId from the last successful booking (update as needed)
APPOINTMENT_ID = '1723216902232220787'

CANCEL_PAYLOAD = {
    "action": "cancel",
    "sessionId": "test_booking_123",
    "dialedNumber": TEST_DIALED_NUMBER,
    "callerPhone": "0412345678",
    "appointmentId": APPOINTMENT_ID
}


def cancel_appointment():
    logger.info("\n--- Step: Cancel Appointment via Webhook ---")
    logger.info(f"Cancel payload: {json.dumps(CANCEL_PAYLOAD, indent=2)}")
    try:
        response = requests.post(
            f'{WEBHOOK_BASE_URL}/cancel-appointment',
            headers=webhook_headers,
            json=CANCEL_PAYLOAD
        )
        logger.info(f"Status: {response.status_code}")
        logger.info(f"Response: {response.text}")
        if response.status_code != 200:
            logger.error("Cancellation failed.")
            return False
        result = response.json()
        if result.get('success'):
            logger.info("CANCELLATION SUCCESSFUL!")
            logger.info(f"Message: {result.get('message')}")
            return True
        else:
            logger.error(f"Cancellation failed: {result.get('message')}")
            logger.error(f"Error details: {result.get('error')}")
            return False
    except Exception as e:
        logger.error(f"Exception in cancel_appointment: {e}")
        return False


def main():
    logger.info("=== Webhook-First Cancel Test ===")
    logger.info(f"Webhook API: {WEBHOOK_BASE_URL}")
    logger.info(f"Test phone number: {TEST_DIALED_NUMBER}")
    # Step: Cancel appointment
    success = cancel_appointment()
    if success:
        logger.info("\nCANCEL TEST COMPLETED SUCCESSFULLY!")
        logger.info(f"\nTest results saved to: {log_file}")
    else:
        logger.error("\nCANCEL TEST FAILED!")
        logger.error(f"\nCheck log file for details: {log_file}")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        logger.error(f"Unhandled exception: {e}", exc_info=True)
        logger.error(f"\nCheck log file for details: {log_file}")
