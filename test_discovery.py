import requests
import json
from datetime import datetime, timedelta
import os
from typing import Dict, Any
import uuid

# Configuration
BASE_URL = "http://localhost:8000"
API_KEY = "MS0xNzAyMDE4MzQ3NzQ0MzcyMjM4LUs2YzJodjE2TEM1OVVGM0JTRU1GMHZ1K2Y5V0VmRHNH-au4"

def test_availability_discovery():
    """Test discovering where Brendan works using availability checker"""
    print("\n=== Testing Availability Discovery ===")
    
    session_id = f"session_{uuid.uuid4()}"
    availability_url = f"{BASE_URL}/availability-checker"
    headers = {
        "x-api-key": API_KEY,
        "Content-Type": "application/json"
    }
    
    tomorrow = datetime.now() + timedelta(days=1)
    date_str = tomorrow.strftime("%Y-%m-%d")
    
    payload = {
        "practitioner": "Brendan Smith",
        "appointmentType": "Acupuncture (Follow up)",
        "date": date_str,
        "time_preference": "morning",
        "dialedNumber": "0478621276",
        "sessionId": session_id
    }
    
    print(f"Checking availability for Brendan Smith on {date_str}...")
    print(f"Payload: {json.dumps(payload, indent=2)}")
    
    try:
        response = requests.post(availability_url, headers=headers, json=payload)
        print(f"[availability_discovery] Status: {response.status_code}")
        print(f"[availability_discovery] Response: {response.text}")
        if response.status_code == 200:
            result = response.json()
            print(f"✅ Availability response: {json.dumps(result, indent=2)}")
            if result.get("needsClarification") and result.get("options"):
                print("📍 Found location options, using first available location...")
                first_location = result["options"][0]
                location_name = first_location.get("name", "Unknown Location")
                business_id = first_location.get("business_id")
                print(f"Using location: {location_name} (ID: {business_id})")
                return business_id, location_name, session_id
            else:
                print("❌ No location options found")
                return None, None, session_id
        else:
            print(f"❌ Availability check failed: {response.status_code}")
            print(response.text)
            return None, None, session_id
    except Exception as e:
        print(f"❌ Error checking availability: {e}")
        return None, None, session_id

def test_booking_with_discovered_location(business_id: str, location_name: str, session_id: str):
    """Test booking using the discovered location"""
    print(f"\n=== Testing Booking at {location_name} ===")
    
    tomorrow = datetime.now() + timedelta(days=1)
    date_str = tomorrow.strftime("%Y-%m-%d")
    
    booking_url = f"{BASE_URL}/appointment-handler"
    headers = {
        "x-api-key": API_KEY,
        "Content-Type": "application/json"
    }
    
    payload = {
        "action": "book",
        "appointmentType": "Acupuncture (Follow up)",
        "callerPhone": "0412345678",
        "bookingFor": "self",
        "patientPhone": "0412345678",
        "patientName": "John Doe",
        "practitioner": "Brendan Smith",
        "appointmentDate": date_str,
        "appointmentTime": "09:00",
        "sessionId": session_id,
        "dialedNumber": "0478621276",
        "location": location_name,
        "locationId": business_id,
        "notes": "Test booking via script"
    }
    
    print(f"Booking appointment at {location_name}...")
    print(f"Payload: {json.dumps(payload, indent=2)}")
    
    try:
        response = requests.post(booking_url, headers=headers, json=payload)
        print(f"[booking] Status: {response.status_code}")
        print(f"[booking] Response: {response.text}")
        if response.status_code == 200:
            result = response.json()
            print(f"✅ Booking successful: {json.dumps(result, indent=2)}")
            return result
        else:
            print(f"❌ Booking failed: {response.status_code}")
            print(response.text)
            return None
    except Exception as e:
        print(f"❌ Error booking appointment: {e}")
        return None

def main():
    print("🚀 Starting comprehensive test with availability discovery...")
    try:
        # Removed sync_clinic_data step
        business_id, location_name, session_id = test_availability_discovery()
        if not business_id:
            print("❌ Failed to discover location, aborting test")
            return
        booking_result = test_booking_with_discovered_location(business_id, location_name, session_id)
        if booking_result:
            print("🎉 Test completed successfully!")
        else:
            print("❌ Test failed")
    except Exception as e:
        print(f"❌ Unhandled exception in main: {e}")

if __name__ == "__main__":
    main() 