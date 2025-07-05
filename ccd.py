# check_business_practitioners.py
import httpx
import asyncio
import base64
import json

API_KEY = "MS0xNzAyMDE4MzQ3NzQ0MzcyMjM4LUs2YzJodjE2TEM1OVVGM0JTRU1GMHZ1K2Y5V0VmRHNH-au4"
SHARD = "au4"
BASE_URL = f"https://api.{SHARD}.cliniko.com/v1"

auth_string = f"{API_KEY}:"
auth_b64 = base64.b64encode(auth_string.encode('ascii')).decode('ascii')

HEADERS = {
    "Authorization": f"Basic {auth_b64}",
    "Accept": "application/json",
    "User-Agent": "Python/Test"
}

async def check_business_practitioners():
    async with httpx.AsyncClient() as client:
        # Get both businesses
        print("Checking practitioner assignments...\n")
        
        businesses = [
            ("1701928805762869230", "Noam Field"),
            ("1709781060880966929", "Location 2")
        ]
        
        for biz_id, biz_name in businesses:
            print(f"\n{biz_name}:")
            url = f"{BASE_URL}/businesses/{biz_id}"
            
            response = await client.get(url, headers=HEADERS)
            if response.status_code == 200:
                biz = response.json()
                
                # Check practitioners field
                practitioners = biz.get('practitioners', {})
                print(f"  Practitioners field: {practitioners}")
                
                # If practitioners has links, follow them
                if isinstance(practitioners, dict) and 'links' in practitioners:
                    prac_url = practitioners['links'].get('self')
                    if prac_url:
                        print(f"  Following practitioner link: {prac_url}")
                        # Adjust URL if needed
                        if prac_url.startswith('/'):
                            prac_url = f"{BASE_URL}{prac_url}"
                        
                        prac_response = await client.get(prac_url, headers=HEADERS)
                        if prac_response.status_code == 200:
                            prac_data = prac_response.json()
                            print(f"  Practitioners at {biz_name}:")
                            for p in prac_data.get('practitioners', []):
                                print(f"    - {p['first_name']} {p['last_name']} (ID: {p['id']})")
                
                # Also check appointment_type_ids
                appt_types = biz.get('appointment_type_ids', [])
                print(f"  Appointment type IDs: {len(appt_types)} types")
                if appt_types:
                    print(f"    First few: {appt_types[:5]}")
        
        # Now test the CORRECT endpoint format
        print("\n\nTesting CORRECT availability endpoint:")
        
        # Based on Cliniko docs, try this format
        business_id = "1709781060880966929"  # Location 2
        practitioner_id = "1702107281644070164"  # Cameron
        
        # Get available times for the business
        url = f"{BASE_URL}/businesses/{business_id}/available_times"
        params = {
            "from": "2025-06-25",
            "to": "2025-06-26"
        }
        
        print(f"\nTrying: GET {url}")
        print(f"Params: {params}")
        
        response = await client.get(url, headers=HEADERS, params=params)
        print(f"Status: {response.status_code}")
        
        if response.status_code == 200:
            times = response.json().get('available_times', [])
            print(f"✅ Found {len(times)} available times!")
            
            # Filter for Cameron's times
            cameron_times = [t for t in times if str(t.get('practitioner', {}).get('id')) == practitioner_id]
            print(f"   Cameron has {len(cameron_times)} slots")

asyncio.run(check_business_practitioners())