#!/usr/bin/env python3
"""
Debug script to check appointment handler issues
"""

import asyncio
import asyncpg
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

async def debug_appointment_handler():
    """Debug the appointment handler by checking database state"""
    db_url = os.getenv("DATABASE_URL")
    pool = await asyncpg.create_pool(db_url)
    
    async with pool.acquire() as conn:
        # Get clinic ID
        clinic = await conn.fetchrow("""
            SELECT clinic_id, clinic_name
            FROM clinics 
            WHERE phone_number = $1
        """, '0478621276')
        
        if not clinic:
            print("Clinic not found!")
            return
        
        clinic_id = clinic['clinic_id']
        print(f"Clinic: {clinic['clinic_name']} (ID: {clinic_id})")
        
        # Check what's in the v_comprehensive_services view
        print(f"\n=== v_comprehensive_services view ===")
        services = await conn.fetch("""
            SELECT DISTINCT
                practitioner_name,
                practitioner_id,
                service_name,
                appointment_type_id,
                business_name,
                business_id
            FROM v_comprehensive_services
            WHERE clinic_id = $1
            ORDER BY practitioner_name, service_name
        """, clinic_id)
        
        if services:
            for service in services:
                print(f"  {service['practitioner_name']} ({service['practitioner_id']}): {service['service_name']} at {service['business_name']}")
        else:
            print("  No services found in v_comprehensive_services view!")
        
        # Check raw tables
        print(f"\n=== Raw tables ===")
        
        # Check practitioners
        practitioners = await conn.fetch("""
            SELECT practitioner_id, first_name, last_name, active
            FROM practitioners
            WHERE clinic_id = $1
            ORDER BY first_name, last_name
        """, clinic_id)
        
        print(f"Practitioners ({len(practitioners)}):")
        for prac in practitioners:
            status = " (ACTIVE)" if prac['active'] else " (INACTIVE)"
            print(f"  {prac['first_name']} {prac['last_name']}{status} (ID: {prac['practitioner_id']})")
        
        # Check appointment types
        appointment_types = await conn.fetch("""
            SELECT appointment_type_id, name, active
            FROM appointment_types
            WHERE clinic_id = $1
            ORDER BY name
        """, clinic_id)
        
        print(f"\nAppointment types ({len(appointment_types)}):")
        for apt_type in appointment_types:
            status = " (ACTIVE)" if apt_type['active'] else " (INACTIVE)"
            print(f"  {apt_type['name']}{status} (ID: {apt_type['appointment_type_id']})")
        
        # Check practitioner_appointment_types
        pat_links = await conn.fetch("""
            SELECT 
                pat.practitioner_id,
                pat.appointment_type_id,
                p.first_name || ' ' || p.last_name as practitioner_name,
                at.name as service_name
            FROM practitioner_appointment_types pat
            JOIN practitioners p ON pat.practitioner_id = p.practitioner_id
            JOIN appointment_types at ON pat.appointment_type_id = at.appointment_type_id
            WHERE p.clinic_id = $1
            ORDER BY p.first_name, p.last_name, at.name
        """, clinic_id)
        
        print(f"\nPractitioner-Appointment Type links ({len(pat_links)}):")
        for link in pat_links:
            print(f"  {link['practitioner_name']} -> {link['service_name']}")
        
        # Check practitioner_businesses
        pb_links = await conn.fetch("""
            SELECT 
                pb.practitioner_id,
                pb.business_id,
                p.first_name || ' ' || p.last_name as practitioner_name,
                b.business_name
            FROM practitioner_businesses pb
            JOIN practitioners p ON pb.practitioner_id = p.practitioner_id
            JOIN businesses b ON pb.business_id = b.business_id
            WHERE p.clinic_id = $1
            ORDER BY p.first_name, p.last_name, b.business_name
        """, clinic_id)
        
        print(f"\nPractitioner-Business links ({len(pb_links)}):")
        for link in pb_links:
            print(f"  {link['practitioner_name']} -> {link['business_name']}")
        
        # Check businesses
        businesses = await conn.fetch("""
            SELECT business_id, business_name, is_primary
            FROM businesses
            WHERE clinic_id = $1
            ORDER BY is_primary DESC, business_name
        """, clinic_id)
        
        print(f"\nBusinesses ({len(businesses)}):")
        for biz in businesses:
            primary = " (PRIMARY)" if biz['is_primary'] else ""
            print(f"  {biz['business_name']}{primary} (ID: {biz['business_id']})")
        
        # Test the specific case: Brendan Smith + Acupuncture (Follow up)
        print(f"\n=== Testing Brendan Smith + Acupuncture (Follow up) ===")
        
        # Find Brendan Smith
        brendan = await conn.fetchrow("""
            SELECT practitioner_id, first_name, last_name
            FROM practitioners
            WHERE clinic_id = $1 AND first_name ILIKE '%brendan%'
        """, clinic_id)
        
        if brendan:
            print(f"Found Brendan Smith: {brendan['first_name']} {brendan['last_name']} (ID: {brendan['practitioner_id']})")
            
            # Check if he has Acupuncture (Follow up)
            acupuncture_followup = await conn.fetchrow("""
                SELECT appointment_type_id, name
                FROM appointment_types
                WHERE clinic_id = $1 AND name ILIKE '%acupuncture%follow%up%'
            """, clinic_id)
            
            if acupuncture_followup:
                print(f"Found Acupuncture (Follow up): {acupuncture_followup['name']} (ID: {acupuncture_followup['appointment_type_id']})")
                
                # Check if Brendan has this service
                has_service = await conn.fetchrow("""
                    SELECT 1
                    FROM practitioner_appointment_types
                    WHERE practitioner_id = $1 AND appointment_type_id = $2
                """, brendan['practitioner_id'], acupuncture_followup['appointment_type_id'])
                
                if has_service:
                    print("✓ Brendan Smith has Acupuncture (Follow up) service")
                else:
                    print("✗ Brendan Smith does NOT have Acupuncture (Follow up) service")
                    
                    # Check what services he actually has
                    his_services = await conn.fetch("""
                        SELECT at.name
                        FROM practitioner_appointment_types pat
                        JOIN appointment_types at ON pat.appointment_type_id = at.appointment_type_id
                        WHERE pat.practitioner_id = $1 AND at.clinic_id = $2
                        ORDER BY at.name
                    """, brendan['practitioner_id'], clinic_id)
                    
                    print(f"Brendan's actual services: {[s['name'] for s in his_services]}")
            else:
                print("✗ Acupuncture (Follow up) service not found")
        else:
            print("✗ Brendan Smith not found")
    
    await pool.close()

if __name__ == "__main__":
    asyncio.run(debug_appointment_handler()) 