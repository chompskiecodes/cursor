#!/usr/bin/env python3
"""Debug script for find-next-available endpoint"""

import asyncio
import httpx
import json
from datetime import datetime, timedelta
import time

async def test_find_next_available():
    """Test the /find-next-available endpoint directly with production-like payload"""
    
    # Test data matching the failing production call
    payload = {
        "practitioner": "Cameron",
        "service": "Acupuncture (Initial)",
        "sessionId": "1",
        "dialedNumber": "0478621276",
        "business_id": "1717010852512540252"
    }
    
    print("Testing /find-next-available...")
    print(f"Payload: {json.dumps(payload, indent=2)}")
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "http://localhost:8000/find-next-available",
                json=payload,
                timeout=60.0
            )
            
            print(f"Status: {response.status_code}")
            print(f"Response: {response.text}")
            if response.status_code == 200:
                data = response.json()
                print(json.dumps(data, indent=2))
    
    except Exception as e:
        print(f"Error: {e}")

async def test_find_next_available_schedule_filter():
    """Test that /find-next-available only returns slots on scheduled working days."""
    # Example: Use a practitioner and business known to have a schedule (adjust as needed)
    payload = {
        "practitioner": "Cameron",
        "service": "Acupuncture (Initial)",
        "sessionId": "test-session-schedule-filter",
        "dialedNumber": "0478621276",
        "business_id": "1717010852512540252",
        "maxDays": 7  # Search a week
    }
    print("Testing /find-next-available with schedule filtering...")
    print(f"Payload: {json.dumps(payload, indent=2)}")
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "http://localhost:8000/find-next-available",
                json=payload,
                timeout=60.0
            )
            print(f"Status: {response.status_code}")
            print(f"Response: {response.text}")
            if response.status_code == 200:
                data = response.json()
                print(json.dumps(data, indent=2))
                # Manual check: The returned 'date' should match a scheduled working day for the practitioner
                # Optionally, assert here if you know the expected day
    except Exception as e:
        print(f"Error: {e}")

async def test_sequential_find_next_available_with_location():
    """Test /find-next-available with both practitioner and business_id (location) specified."""
    payload = {
        "practitioner": "Brendan",
        "service": "Acupuncture (Initial)",
        "sessionId": "test-session-sequential-location-specific",
        "dialedNumber": "0478621276",
        "business_id": "1701928805762869230",  # City Clinic
        "maxDays": 7
    }
    start = time.time()
    slots = []
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "http://localhost:8000/find-next-available",
                json=payload,
                timeout=60.0
            )
            elapsed = time.time() - start
            if response.status_code == 200:
                data = response.json()
                slots = data.get("slots", [])
            print(f"Sequential endpoint execution time: {elapsed:.3f} seconds")
            print("Slots returned (sequential):")
            for slot in slots:
                print(slot)
            print()
    except Exception as e:
        print(f"Error: {e}")
    return elapsed, slots

async def test_enhanced_find_next_available_with_location():
    """Test /enhanced/find-next-available with both practitioner and business_id (location) specified."""
    payload = {
        "practitioner": "Brendan",
        "service": "Acupuncture (Initial)",
        "sessionId": "test-session-enhanced-location-specific",
        "dialedNumber": "0478621276",
        "business_id": "1701928805762869230",  # City Clinic
        "maxDays": 7
    }
    start = time.time()
    slots = []
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "http://localhost:8000/enhanced/find-next-available",
                json=payload,
                timeout=60.0
            )
            elapsed = time.time() - start
            if response.status_code == 200:
                data = response.json()
                print("Full parallel endpoint response:")
                print(json.dumps(data, indent=2))
                slots = data.get("slots", [])
            print(f"Parallel endpoint execution time: {elapsed:.3f} seconds")
            print("Slots returned (parallel):")
            for slot in slots:
                print(slot)
            print()
    except Exception as e:
        print(f"Error: {e}")
    return elapsed, slots

async def test_compare_sequential_and_parallel():
    seq_time, seq_slots = await test_sequential_find_next_available_with_location()
    par_time, par_slots = await test_enhanced_find_next_available_with_location()
    print("=== SUMMARY ===")
    print(f"Sequential endpoint: {seq_time:.3f} seconds, slots: {seq_slots}")
    print(f"Parallel endpoint:   {par_time:.3f} seconds, slots: {par_slots}")

if __name__ == "__main__":
    asyncio.run(test_compare_sequential_and_parallel())
