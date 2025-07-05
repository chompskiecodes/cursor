# fix_practitioner_businesses.py
import asyncio
import asyncpg
import os
from dotenv import load_dotenv

load_dotenv()

async def fix_practitioner_businesses():
    # Use the pooler connection
    db_url = os.environ.get("SUPABASE_DB_URL")
    
    conn = await asyncpg.connect(db_url)
    
    try:
        clinic_id = '9c9d041c-585a-44bb-b685-4a3432d66d82'
        
        # Get all practitioners for this clinic
        practitioners = await conn.fetch("""
            SELECT practitioner_id, first_name, last_name 
            FROM practitioners 
            WHERE clinic_id = $1 AND active = true
        """, clinic_id)
        
        # Get all businesses for this clinic
        businesses = await conn.fetch("""
            SELECT business_id, business_name, is_primary 
            FROM businesses 
            WHERE clinic_id = $1
            ORDER BY is_primary DESC
        """, clinic_id)
        
        print(f"Found {len(practitioners)} practitioners and {len(businesses)} businesses")
        print("\nCreating practitioner-business links...")
        
        links_created = 0
        
        # Link all practitioners to all businesses
        for practitioner in practitioners:
            for business in businesses:
                try:
                    await conn.execute("""
                        INSERT INTO practitioner_businesses (practitioner_id, business_id)
                        VALUES ($1, $2)
                        ON CONFLICT (practitioner_id, business_id) DO NOTHING
                    """, practitioner['practitioner_id'], business['business_id'])
                    
                    print(f"✅ Linked {practitioner['first_name']} {practitioner['last_name']} -> {business['business_name']} (business ID: {business['business_id']})")
                    links_created += 1
                    
                except Exception as e:
                    print(f"❌ Error linking {practitioner['practitioner_id']} to business ID {business['business_id']}: {e}")
        
        print(f"\n✅ Created {links_created} practitioner-business links")
        
        # Verify the fix worked
        print("\n=== VERIFYING FIX ===")
        
        # Check practitioner_businesses
        pb_count = await conn.fetchval("""
            SELECT COUNT(*) FROM practitioner_businesses pb
            JOIN practitioners p ON pb.practitioner_id = p.practitioner_id
            WHERE p.clinic_id = $1
        """, clinic_id)
        print(f"Practitioner-business links: {pb_count}")
        
        # Check v_comprehensive_services
        services = await conn.fetch("""
            SELECT DISTINCT practitioner_name, service_name, business_name
            FROM v_comprehensive_services
            WHERE clinic_id = $1
            LIMIT 5
        """, clinic_id)
        
        print(f"\nServices in v_comprehensive_services: {len(services)} (showing first 5)")
        for s in services:
            print(f"  📋 {s['practitioner_name']} - {s['service_name']} @ {s['business_name']}")
        
        # Get total count
        total_services = await conn.fetchval("""
            SELECT COUNT(*) FROM v_comprehensive_services
            WHERE clinic_id = $1
        """, clinic_id)
        print(f"\nTotal services available: {total_services}")
        
    finally:
        await conn.close()

if __name__ == "__main__":
    asyncio.run(fix_practitioner_businesses())