import asyncio
import asyncpg

async def check_database():
    conn = await asyncpg.connect('postgresql://postgres.feywathteocancjzdgtf:seS!llyw3rd@aws-0-ap-southeast-2.pooler.supabase.com:5432/postgres')
    
    print("=== Checking Database Content ===")
    
    # Check businesses
    businesses = await conn.fetch('SELECT business_id, business_name, clinic_id FROM businesses LIMIT 5')
    print(f"Businesses ({len(businesses)}):")
    for b in businesses:
        print(f"  {b['business_id']}: {b['business_name']} (clinic: {b['clinic_id']})")
    
    # Check clinics
    clinics = await conn.fetch('SELECT clinic_id, clinic_name, phone_number FROM clinics LIMIT 5')
    print(f"\nClinics ({len(clinics)}):")
    for c in clinics:
        print(f"  {c['clinic_id']}: {c['clinic_name']} (phone: {c['phone_number']})")
    
    # Check practitioners
    practitioners = await conn.fetch('SELECT practitioner_id, first_name, last_name, clinic_id FROM practitioners LIMIT 5')
    print(f"\nPractitioners ({len(practitioners)}):")
    for p in practitioners:
        print(f"  {p['practitioner_id']}: {p['first_name']} {p['last_name']} (clinic: {p['clinic_id']})")
    
    await conn.close()

if __name__ == "__main__":
    asyncio.run(check_database()) 