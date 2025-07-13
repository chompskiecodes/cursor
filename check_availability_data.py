#!/usr/bin/env python3
"""
Check what availability data exists in the system
"""

import asyncio
import asyncpg
import os
from datetime import datetime, timedelta

async def check_availability_data():
    """Check what practitioners and availability data exists"""
    
    # Database connection
    db_url = os.getenv('DATABASE_URL', 'postgresql://postgres:password@localhost:5432/cliniko_agent')
    conn = await asyncpg.connect(db_url)
    
    print("=== AVAILABILITY DATA CHECK ===\n")
    
    # Check practitioners
    print("1. PRACTITIONERS:")
    print("-" * 40)
    practitioners = await conn.fetch("""
        SELECT p.practitioner_id, p.first_name, p.last_name, p.active, p.clinic_id
        FROM practitioners p
        ORDER BY p.first_name, p.last_name
    """)
    
    print(f"Total practitioners: {len(practitioners)}")
    active_practitioners = [p for p in practitioners if p['active']]
    print(f"Active practitioners: {len(active_practitioners)}")
    
    for p in active_practitioners[:5]:  # Show first 5
        print(f"  - {p['first_name']} {p['last_name']} (ID: {p['practitioner_id']})")
    
    if len(active_practitioners) > 5:
        print(f"  ... and {len(active_practitioners) - 5} more")
    
    # Check businesses
    print("\n2. BUSINESSES:")
    print("-" * 40)
    businesses = await conn.fetch("""
        SELECT business_id, name, active
        FROM businesses
        ORDER BY name
    """)
    
    print(f"Total businesses: {len(businesses)}")
    active_businesses = [b for b in businesses if b['active']]
    print(f"Active businesses: {len(active_businesses)}")
    
    for b in active_businesses:
        print(f"  - {b['name']} (ID: {b['business_id']})")
    
    # Check practitioner-business relationships
    print("\n3. PRACTITIONER-BUSINESS RELATIONSHIPS:")
    print("-" * 40)
    prac_business = await conn.fetch("""
        SELECT pb.practitioner_id, pb.business_id, 
               p.first_name, p.last_name, b.name as business_name
        FROM practitioner_businesses pb
        JOIN practitioners p ON pb.practitioner_id = p.practitioner_id
        JOIN businesses b ON pb.business_id = b.business_id
        WHERE p.active = true AND b.active = true
        ORDER BY b.name, p.first_name, p.last_name
    """)
    
    print(f"Active practitioner-business relationships: {len(prac_business)}")
    
    # Group by business
    by_business = {}
    for pb in prac_business:
        business_name = pb['business_name']
        if business_name not in by_business:
            by_business[business_name] = []
        by_business[business_name].append(f"{pb['first_name']} {pb['last_name']}")
    
    for business, practitioners in by_business.items():
        print(f"  {business}: {', '.join(practitioners)}")
    
    # Check appointment types
    print("\n4. APPOINTMENT TYPES:")
    print("-" * 40)
    appointment_types = await conn.fetch("""
        SELECT at.appointment_type_id, at.name, at.active
        FROM appointment_types at
        ORDER BY at.name
    """)
    
    print(f"Total appointment types: {len(appointment_types)}")
    active_types = [at for at in appointment_types if at['active']]
    print(f"Active appointment types: {len(active_types)}")
    
    for at in active_types[:10]:  # Show first 10
        print(f"  - {at['name']} (ID: {at['appointment_type_id']})")
    
    if len(active_types) > 10:
        print(f"  ... and {len(active_types) - 10} more")
    
    # Check practitioner-appointment type relationships
    print("\n5. PRACTITIONER-SERVICE RELATIONSHIPS:")
    print("-" * 40)
    prac_services = await conn.fetch("""
        SELECT pat.practitioner_id, pat.appointment_type_id,
               p.first_name, p.last_name, at.name as service_name
        FROM practitioner_appointment_types pat
        JOIN practitioners p ON pat.practitioner_id = p.practitioner_id
        JOIN appointment_types at ON pat.appointment_type_id = at.appointment_type_id
        WHERE p.active = true AND at.active = true
        ORDER BY p.first_name, p.last_name, at.name
    """)
    
    print(f"Active practitioner-service relationships: {len(prac_services)}")
    
    # Group by practitioner
    by_practitioner = {}
    for ps in prac_services:
        practitioner_name = f"{ps['first_name']} {ps['last_name']}"
        if practitioner_name not in by_practitioner:
            by_practitioner[practitioner_name] = []
        by_practitioner[practitioner_name].append(ps['service_name'])
    
    for practitioner, services in list(by_practitioner.items())[:5]:  # Show first 5
        print(f"  {practitioner}: {', '.join(services)}")
    
    if len(by_practitioner) > 5:
        print(f"  ... and {len(by_practitioner) - 5} more practitioners")
    
    # Check cached availability
    print("\n6. CACHED AVAILABILITY:")
    print("-" * 40)
    cached_availability = await conn.fetch("""
        SELECT COUNT(*) as count, 
               MIN(created_at) as earliest,
               MAX(created_at) as latest
        FROM cached_availability
    """)
    
    if cached_availability:
        count = cached_availability[0]['count']
        earliest = cached_availability[0]['earliest']
        latest = cached_availability[0]['latest']
        
        print(f"Total cached availability records: {count}")
        if earliest and latest:
            print(f"Date range: {earliest.strftime('%Y-%m-%d')} to {latest.strftime('%Y-%m-%d')}")
        
        # Check recent availability
        recent_availability = await conn.fetch("""
            SELECT ca.practitioner_id, ca.appointment_type_id, ca.date,
                   p.first_name, p.last_name, at.name as service_name,
                   ca.available_times
            FROM cached_availability ca
            JOIN practitioners p ON ca.practitioner_id = p.practitioner_id
            JOIN appointment_types at ON ca.appointment_type_id = at.appointment_type_id
            WHERE ca.date >= CURRENT_DATE
            ORDER BY ca.date, p.first_name, p.last_name
            LIMIT 10
        """)
        
        if recent_availability:
            print(f"Recent availability records (next 10):")
            for ra in recent_availability:
                times_count = len(ra['available_times']) if ra['available_times'] else 0
                print(f"  {ra['first_name']} {ra['last_name']} - {ra['service_name']} on {ra['date']}: {times_count} slots")
        else:
            print("No recent availability data found")
    else:
        print("No cached availability data found")
    
    await conn.close()

if __name__ == "__main__":
    asyncio.run(check_availability_data()) 