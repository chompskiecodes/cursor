import requests
import json

URL = "http://localhost:8000/enhanced/get-available-practitioners"

payload = {
    "business_id": "1701928805762869230",
    "businessName": "City Clinic",
    "date": "2025-07-20",  # One week later
    "dialedNumber": "0478621276",
    "sessionId": "test-session-enhanced-get-available"
}

print("Requesting /enhanced/get-available-practitioners with payload:")
print(json.dumps(payload, indent=2))

response = requests.post(URL, json=payload)

print("\nResponse:")
try:
    print(json.dumps(response.json(), indent=2))
except Exception as e:
    print("Failed to parse JSON response:", e)
    print(response.text)

def test_week_availability():
    import requests
    from datetime import date, timedelta
    base_url = "http://localhost:8000/enhanced/get-available-practitioners"
    business_id = "1701928805762869230"
    business_name = "City Clinic"
    dialed_number = "0478621276"
    session_id = "test-session-enhanced-get-available"
    week_start = date(2025, 7, 14)  # Monday
    for i in range(7):
        d = week_start + timedelta(days=i)
        payload = {
            "business_id": business_id,
            "businessName": business_name,
            "date": d.isoformat(),
            "dialedNumber": dialed_number,
            "sessionId": session_id
        }
        resp = requests.post(base_url, json=payload)
        print(f"Results for {d}:")
        print(resp.json())
        print("-" * 40)

def test_30_day_future_availability():
    import requests
    from datetime import date, timedelta
    import time
    base_url = "http://localhost:8000/enhanced/get-available-practitioners"
    business_id = "1701928805762869230"
    business_name = "City Clinic"
    dialed_number = "0478621276"
    session_id = "test-session-enhanced-get-available"
    start_date = date(2025, 7, 14)
    total_time = 0
    for i in range(30):
        d = start_date + timedelta(days=i)
        payload = {
            "business_id": business_id,
            "businessName": business_name,
            "date": d.isoformat(),
            "dialedNumber": dialed_number,
            "sessionId": session_id
        }
        t0 = time.time()
        resp = requests.post(base_url, json=payload)
        t1 = time.time()
        print(f"Results for {d} (took {t1-t0:.2f}s):")
        print(resp.json())
        print("-" * 40)
        total_time += (t1-t0)
    print(f"Total time for 30 days: {total_time:.2f}s")

def test_future_week_availability():
    import requests
    from datetime import date, timedelta
    import time
    base_url = "http://localhost:8000/enhanced/get-available-practitioners"
    business_id = "1701928805762869230"
    business_name = "City Clinic"
    dialed_number = "0478621276"
    session_id = "test-session-enhanced-get-available"
    # Start 30 days after 2025-07-14
    week_start = date(2025, 7, 14) + timedelta(days=30)
    total_time = 0
    for i in range(7):
        d = week_start + timedelta(days=i)
        payload = {
            "business_id": business_id,
            "businessName": business_name,
            "date": d.isoformat(),
            "dialedNumber": dialed_number,
            "sessionId": session_id
        }
        t0 = time.time()
        resp = requests.post(base_url, json=payload)
        t1 = time.time()
        print(f"Results for {d} (took {t1-t0:.2f}s):")
        print(resp.json())
        print("-" * 40)
        total_time += (t1-t0)
    print(f"Total time for future week: {total_time:.2f}s") 