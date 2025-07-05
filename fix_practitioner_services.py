# fix_practitioner_services.py
import asyncio
import asyncpg
from dotenv import load_dotenv
import os

load_dotenv()

async def link_practitioners_to_services():
    conn = await asyncpg.connect(os.getenv('DATABASE_URL'))
    
    # Get clinic ID
    clinic = await conn.fetchrow(
        "SELECT clinic_id FROM clinics WHERE phone_number = $1",
        "0478621276"
    )
    clinic_id = clinic['clinic_id']
    
    # Get all practitioners
    practitioners = await conn.fetch(
        "SELECT practitioner_id FROM practitioners WHERE clinic_id = $1",
        clinic_id
    )
    
    # Get all appointment types
    appt_types = await conn.fetch(
        "SELECT appointment_type_id FROM appointment_types WHERE clinic_id = $1",
        clinic_id
    )
    
    # Link each practitioner to each appointment type (for testing)
    print("Linking practitioners to services...")
    for p in practitioners:
        for a in appt_types:
            try:
                await conn.execute(
                    """INSERT INTO practitioner_appointment_types 
                       (practitioner_id, appointment_type_id) 
                       VALUES ($1, $2) 
                       ON CONFLICT DO NOTHING""",
                    p['practitioner_id'], a['appointment_type_id']
                )
            except Exception as e:
                print(f"Error: {e}")
    
    # Verify
    count = await conn.fetchval(
        "SELECT COUNT(*) FROM practitioner_appointment_types"
    )
    print(f"✅ Created {count} practitioner-service links")
    
    # Check the view now
    services = await conn.fetch(
        "SELECT COUNT(*) as count FROM v_comprehensive_services WHERE clinic_id = $1",
        clinic_id
    )
    print(f"✅ View now shows {services[0]['count']} services")
    
    await conn.close()

asyncio.run(link_practitioners_to_services())