#!/usr/bin/env python3
"""
Standalone script to onboard a single clinic
Usage: python onboard_single_clinic.py
"""

import asyncio
import sys
from getpass import getpass
from initialize_clinic import ClinicInitializer
import os
from dotenv import load_dotenv

load_dotenv()

async def main():
    print("=== Voice Booking System - Clinic Onboarding ===\n")

    # Collect information
    clinic_data = {
        'clinic_name': input("Clinic name: "),
        'phone_number': input("Phone number (e.g., 0412345678): "),
        'contact_email': input("Contact email: "),
        'cliniko_shard': input("Cliniko shard (au1/au2/au3/au4/uk1/us1): "),
        'cliniko_api_key': getpass("Cliniko API key (hidden): ")
    }

    # Confirm
    print("\nReady to onboard:")
    print(f"  Clinic: {clinic_data['clinic_name']}")
    print(f"  Phone: {clinic_data['phone_number']}")
    print(f"  Email: {clinic_data['contact_email']}")
    print(f"  Shard: {clinic_data['cliniko_shard']}")

    if input("\nProceed? (y/n): ").lower() != 'y':
        print("Cancelled.")
        return

    print("\n⏳ Onboarding... This may take 30-60 seconds.")

    try:
        db_url = os.getenv("DATABASE_URL") or os.getenv('DATABASE_URL')

        async with ClinicInitializer(db_url) as initializer:
            results = await initializer.initialize_clinic(clinic_data)

        if results['errors']:
            print(f"\n❌ Failed: {', '.join(results['errors'])}")
            sys.exit(1)
        else:
            print("\n✅ Successfully onboarded!")
            print(f"   Clinic ID: {results['clinic_id']}")
            print(f"   Practitioners: {results['practitioners']}")
            print(f"   Services: {results['appointment_types']}")
            print(f"   Time: {results.get('elapsed_seconds', 0):.2f} seconds")

    except Exception as e:
        print(f"\n❌ Error: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
