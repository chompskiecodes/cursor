#!/usr/bin/env python3
"""Test the Cliniko API rate limiter over 120 seconds"""

import asyncio
import time
from cliniko import ClinikoAPI
from datetime import datetime, timedelta
from tools.dependencies import get_db
from database import get_clinic_by_dialed_number

async def get_test_data():
    """Get real test data from database using existing infrastructure"""
    # Get database pool using existing infrastructure
    pool = await get_db()
    
    # Get a clinic with API credentials - use a known dialed number
    clinic = await get_clinic_by_dialed_number("0478621276", pool)
    
    if not clinic:
        raise Exception("No clinic with API credentials found")
    
    # Get a business, practitioner, and appointment type
    async with pool.acquire() as conn:
        data = await conn.fetchrow("""
            SELECT 
                b.business_id,
                p.practitioner_id,
                at.appointment_type_id,
                b.business_name,
                p.first_name || ' ' || p.last_name as practitioner_name,
                at.name as service_name
            FROM businesses b
            JOIN practitioner_businesses pb ON b.business_id = pb.business_id
            JOIN practitioners p ON pb.practitioner_id = p.practitioner_id
            JOIN practitioner_appointment_types pat ON p.practitioner_id = pat.practitioner_id
            JOIN appointment_types at ON pat.appointment_type_id = at.appointment_type_id
            WHERE b.clinic_id = $1
            LIMIT 1
        """, clinic.clinic_id)
        
        if not data:
            raise Exception("No practitioner/service/business combination found")
        
        return {
            'clinic': clinic,
            'business_id': data['business_id'],
            'practitioner_id': data['practitioner_id'],
            'appointment_type_id': data['appointment_type_id'],
            'business_name': data['business_name'],
            'practitioner_name': data['practitioner_name'],
            'service_name': data['service_name']
        }

async def test_rate_limiter_120s():
    """Test the rate limiter over 120 seconds"""
    print("=== Cliniko API Rate Limiter Test (120 seconds) ===")
    
    # Get real test data
    test_data = await get_test_data()
    print(f"Using clinic: {test_data['clinic'].clinic_name}")
    print(f"Business: {test_data['business_name']}")
    print(f"Practitioner: {test_data['practitioner_name']}")
    print(f"Service: {test_data['service_name']}")
    print()
    
    # Create API instance
    api = ClinikoAPI(
        test_data['clinic'].cliniko_api_key,
        test_data['clinic'].cliniko_shard,
        "RateLimiterTest/1.0"
    )
    
    # Test parameters
    test_duration = 120  # seconds
    start_time = time.time()
    results = []
    
    # Date range for testing
    from_date = datetime.now().date().isoformat()
    to_date = (datetime.now().date() + timedelta(days=3)).isoformat()
    
    print(f"Running test for {test_duration} seconds...")
    print(f"Expected: ~118 calls (59 per minute)")
    print(f"Date range: {from_date} to {to_date}")
    print()
    print("Time(s) | Call# | Success | Slots | Rate(calls/min)")
    print("--------|-------|---------|-------|---------------")
    
    call_count = 0
    last_minute_calls = []
    
    async def make_call():
        nonlocal call_count
        call_start = time.time()
        call_count += 1
        
        try:
            result = await api.get_available_times(
                test_data['business_id'],
                test_data['practitioner_id'], 
                test_data['appointment_type_id'],
                from_date,
                to_date
            )
            success = True
            slots = len(result) if result else 0
        except Exception as e:
            success = False
            slots = 0
        
        call_end = time.time()
        elapsed = call_end - start_time
        
        # Track calls in the last minute
        last_minute_calls.append(call_end)
        last_minute_calls[:] = [t for t in last_minute_calls if call_end - t < 60.0]
        
        # Calculate current rate
        current_rate = len(last_minute_calls)
        
        print(f"{elapsed:6.1f} | {call_count:5d} | {'✓' if success else '✗'}      | {slots:4d} | {current_rate:13d}")
        
        results.append({
            'call_num': call_count,
            'time': elapsed,
            'success': success,
            'slots': slots,
            'rate_at_time': current_rate
        })
    
    # Start making calls continuously
    while time.time() - start_time < test_duration:
        await make_call()
        # Small delay to prevent overwhelming the system
        await asyncio.sleep(0.1)
    
    total_time = time.time() - start_time
    successful_calls = sum(1 for r in results if r['success'])
    
    print()
    print("=== Final Results ===")
    print(f"Total time: {total_time:.1f} seconds")
    print(f"Total calls: {call_count}")
    print(f"Successful calls: {successful_calls}/{call_count}")
    print(f"Average rate: {call_count / (total_time / 60):.1f} calls/minute")
    
    # Analyze rate over time
    print()
    print("Rate Analysis:")
    for i in range(0, len(results), 20):
        batch = results[i:i+20]
        if batch:
            avg_rate = sum(r['rate_at_time'] for r in batch) / len(batch)
            time_range = f"{batch[0]['time']:.1f}-{batch[-1]['time']:.1f}s"
            print(f"  {time_range}: avg rate = {avg_rate:.1f} calls/min")

if __name__ == "__main__":
    asyncio.run(test_rate_limiter_120s()) 