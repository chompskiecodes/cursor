import os
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise Exception("Please set DATABASE_URL in your environment.")

practitioner_name = "Cameron"
business_name = "City Clinic"

def main():
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor(cursor_factory=RealDictCursor)

    # Find business_id
    cur.execute("""
        SELECT business_id, business_name FROM businesses WHERE business_name ILIKE %s
    """, (f"%{business_name}%",))
    business = cur.fetchone()
    if not business:
        print(f"No business found matching '{business_name}'")
        return
    print(f"Business found: {business['business_name']} (ID: {business['business_id']})")

    # Find practitioner_id
    cur.execute("""
        SELECT practitioner_id, first_name, last_name FROM practitioners
        WHERE first_name ILIKE %s OR last_name ILIKE %s
    """, (f"%{practitioner_name}%", f"%{practitioner_name}%"))
    practitioner = cur.fetchone()
    if not practitioner:
        print(f"No practitioner found matching '{practitioner_name}'")
        return
    print(f"Practitioner found: {practitioner['first_name']} {practitioner['last_name']} (ID: {practitioner['practitioner_id']})")

    # Check mapping
    cur.execute("""
        SELECT 1 FROM practitioner_businesses WHERE practitioner_id = %s AND business_id = %s
    """, (practitioner['practitioner_id'], business['business_id']))
    mapped = cur.fetchone()
    if mapped:
        print(f"\n✅ Practitioner '{practitioner['first_name']} {practitioner['last_name']}' IS assigned to '{business['business_name']}'.")
    else:
        print(f"\n❌ Practitioner '{practitioner['first_name']} {practitioner['last_name']}' is NOT assigned to '{business['business_name']}'.")

    cur.close()
    conn.close()

if __name__ == "__main__":
    main() 