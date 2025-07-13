#!/usr/bin/env python3
"""Test the Cliniko API rate limiter with real API calls (no DB)"""

import asyncio
import time
import os
from cliniko import ClinikoAPI
from datetime import datetime, timedelta

# Get test data from environment variables
CLINIKO_API_KEY = os.environ.get('CLINIKO_API_KEY', 'YOUR_CLINIKO_API_KEY')
CLINIKO_SHARD = os.environ.get('CLINIKO_SHARD', 'au4')
BUSINESS_ID = os.environ.get('BUSINESS_ID', 'YOUR_BUSINESS_ID')
PRACTITIONER_ID = os.environ.get('PRACTITIONER_ID', 'YOUR_PRACTITIONER_ID')
APPOINTMENT_TYPE_ID = os.environ.get('APPOINTMENT_TYPE_ID', 'YOUR_APPTYPE_ID')
BUSINESS_NAME = os.environ.get('BUSINESS_NAME', 'City Clinic')
PRACTITIONER_NAME = os.environ.get('PRACTITIONER_NAME', 'Cameron Lockey')
SERVICE_NAME = os.environ.get('SERVICE_NAME', 'Acupuncture')

async def test_rate_limiter():
    """Test the rate limiter with real API calls"""
    print("=== Cliniko API Rate Limiter Test ===")
    print(f"Using business: {BUSINESS_NAME}")
    print(f"Practitioner: {PRACTITIONER_NAME}")
    print(f"Service: {SERVICE_NAME}")
    print()
    
    # Create API instance
    api = ClinikoAPI(
        CLINIKO_API_KEY,
        CLINIKO_SHARD,
        "RateLimiterTest/1.0"
    )
    
    # Test parameters
    n_calls = 70
    start_time = time.time()
    results = []
    
    # Date range for testing (next few days)
    from_date = datetime.now().date().isoformat()
    to_date = (datetime.now().date() + timedelta(days=3)).isoformat()
    
    print(f"Making {n_calls} parallel API calls...")
    print(f"Date range: {from_date} to {to_date}")
    print()
    
    async def single_call(i):
        call_start = time.time()
        try:
            result = await api.get_available_times(
                BUSINESS_ID,
                PRACTITIONER_ID, 
                APPOINTMENT_TYPE_ID,
                from_date,
                to_date
            )
            success = True
            slots = len(result) if result else 0
        except Exception as e:
            success = False
            slots = 0
            error = str(e)[:50] + "..." if len(str(e)) > 50 else str(e)
        
        call_end = time.time()
        elapsed = call_end - start_time
        call_duration = call_end - call_start
        
        print(f"Call {i+1:02d}: {elapsed:6.2f}s (took {call_duration:.3f}s) - {'✓' if success else '✗'} {slots} slots")
        
        results.append({
            'call_num': i + 1,
            'start_time': call_start - start_time,
            'duration': call_duration,
            'success': success,
            'slots': slots
        })
    
    # Execute all calls in parallel
    await asyncio.gather(*(single_call(i) for i in range(n_calls)))
    
    total_time = time.time() - start_time
    successful_calls = sum(1 for r in results if r['success'])
    
    print()
    print("=== Results ===")
    print(f"Total time: {total_time:.2f} seconds")
    print(f"Successful calls: {successful_calls}/{n_calls}")
    print(f"Average call duration: {sum(r['duration'] for r in results)/len(results):.3f}s")
    
    # Check if rate limiting worked
    if total_time > 60:  # Should take more than 60s for 70 calls with 59/min limit
        print("✓ Rate limiter working: Total time > 60s indicates calls were delayed")
    else:
        print("⚠ Rate limiter may not be working: Total time < 60s")
    
    # Show timing distribution
    print()
    print("Timing analysis:")
    for i in range(0, n_calls, 10):
        batch = results[i:i+10]
        avg_start = sum(r['start_time'] for r in batch) / len(batch)
        print(f"Calls {i+1:02d}-{min(i+10, n_calls):02d}: avg start at {avg_start:.2f}s")

if __name__ == "__main__":
    asyncio.run(test_rate_limiter()) 