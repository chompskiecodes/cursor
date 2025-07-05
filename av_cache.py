#!/usr/bin/env python3
"""
Smart cache refresh that respects rate limits and only refreshes what's needed
"""

import asyncio
import asyncpg
import os
from datetime import datetime, date, timedelta
from dotenv import load_dotenv
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

async def smart_cache_refresh():
    """Smart refresh that minimizes API calls"""
    
    database_url = os.getenv("DATABASE_URL")
    pool = await asyncpg.create_pool(database_url)
    
    try:
        clinic_id = '9da34639-5ea8-4c1b-b29b-82f1ece91518'
        
        async with pool.acquire() as conn:
            clinic = await conn.fetchrow("""
                SELECT clinic_name, cliniko_api_key, cliniko_shard
                FROM clinics WHERE clinic_id = $1
            """, clinic_id)
            
            print(f"Smart cache refresh for: {clinic['clinic_name']}")
            
            # Strategy: Only refresh the most important combinations
            # 1. Primary location only
            # 2. Today + next 3 days only (not 7)
            # 3. Skip if already cached and fresh
            
            important_combos = await conn.fetch("""
                WITH priority_combos AS (
                    SELECT DISTINCT
                        p.practitioner_id,
                        p.first_name || ' ' || p.last_name as practitioner_name,
                        pb.business_id,
                        b.business_name,
                        pat.appointment_type_id,
                        at.name as service_name,
                        b.is_primary
                    FROM practitioners p
                    JOIN practitioner_businesses pb ON p.practitioner_id = pb.practitioner_id
                    JOIN practitioner_appointment_types pat ON p.practitioner_id = pat.practitioner_id
                    JOIN businesses b ON pb.business_id = b.business_id
                    JOIN appointment_types at ON pat.appointment_type_id = at.appointment_type_id
                    WHERE p.clinic_id = $1 
                      AND p.active = true
                      AND at.active = true
                      AND b.is_primary = true  -- PRIMARY LOCATION ONLY
                )
                SELECT * FROM priority_combos
                ORDER BY practitioner_name, service_name
            """, clinic_id)
            
            print(f"\nFocusing on {len(important_combos)} primary location combinations")
            
            from cliniko import ClinikoAPI
            cliniko = ClinikoAPI(
                clinic['cliniko_api_key'],
                clinic['cliniko_shard'],
                user_agent="VoiceBookingSystem/1.0"
            )
            
            api_calls = 0
            max_calls_per_minute = 50  # Stay under 60 limit
            call_times = []
            
            for combo in important_combos:
                print(f"\n{combo['practitioner_name']} - {combo['service_name']}:")
                
                # Only check next 3 days
                for days_ahead in range(3):
                    check_date = date.today() + timedelta(days=days_ahead)
                    
                    # Check if already cached and fresh
                    existing = await conn.fetchrow("""
                        SELECT cache_id, expires_at > NOW() as is_fresh
                        FROM availability_cache
                        WHERE practitioner_id = $1 
                          AND business_id = $2 
                          AND date = $3
                          AND NOT is_stale
                    """, combo['practitioner_id'], combo['business_id'], check_date)
                    
                    if existing and existing['is_fresh']:
                        print(f"  ⏭️  {check_date}: Already cached")
                        continue
                    
                    # Rate limiting check
                    current_time = datetime.now()
                    call_times = [t for t in call_times if (current_time - t).seconds < 60]
                    
                    if len(call_times) >= max_calls_per_minute:
                        wait_time = 60 - (current_time - call_times[0]).seconds
                        print(f"  ⏸️  Rate limit: waiting {wait_time}s...")
                        await asyncio.sleep(wait_time + 1)
                        call_times = []
                    
                    try:
                        # Make API call
                        call_times.append(datetime.now())
                        api_calls += 1
                        
                        slots = await cliniko.get_available_times(
                            combo['business_id'],
                            combo['practitioner_id'],
                            combo['appointment_type_id'],
                            check_date.isoformat(),
                            check_date.isoformat()
                        )
                        
                        # Store result
                        import json
                        await conn.execute("""
                            INSERT INTO availability_cache 
                                (clinic_id, practitioner_id, business_id, date, available_slots)
                            VALUES ($1, $2, $3, $4, $5::jsonb)
                            ON CONFLICT (practitioner_id, business_id, date) 
                            DO UPDATE SET 
                                available_slots = $5::jsonb,
                                cached_at = NOW(),
                                expires_at = NOW() + INTERVAL '4 hours',
                                is_stale = false
                        """, clinic_id, combo['practitioner_id'], combo['business_id'], 
                            check_date, json.dumps(slots if isinstance(slots, list) else []))
                        
                        print(f"  ✓ {check_date}: {len(slots) if slots else 0} slots")
                        
                    except Exception as e:
                        print(f"  ✗ {check_date}: {str(e)[:50]}...")
                    
                    # Always wait at least 1.2 seconds between calls
                    await asyncio.sleep(1.2)
            
            print(f"\n{'='*60}")
            print(f"Smart refresh complete!")
            print(f"  API calls made: {api_calls}")
            print(f"  Rate: ~{api_calls / max(1, len(call_times))*60:.1f} calls/minute")
            
    finally:
        await pool.close()


if __name__ == "__main__":
    print("Starting smart cache refresh...")
    asyncio.run(smart_cache_refresh())