#!/usr/bin/env python3
import requests

# === API Config ===
ELEVENLABS_API_KEY = "sk_8ac5a73e17b37d0275ee0a8cce89a4bb53a07ee7f1609692"
WEBHOOK_API_KEY = "MS0xNzAyMDE4MzQ3NzQ0MzcyMjM4LUs2YzJodjE2TEM1OVVGM0JTRU1GMHZ1K2Y5V0VmRHNH-au4"
ELEVENLABS_API_URL = "https://api.elevenlabs.io/v1/convai/tools"

# === Tool metadata and IDs ===
TOOLS = [
    {
        "name": "location_resolver",
        "id": "CnABJJ47hcLunEF3T8PC",
        "description": "Resolves ANY location reference to a specific clinic location ID. Call when location is mentioned (main, usual, Balmain, city, your clinic, etc). Returns one of two responses: 1) SUCCESS: Returns location_id (a number) - use this in subsequent tools 2) NEEDS CLARIFICATION: Returns needs_clarification=true with a message and options list. When this happens, you MUST read the message to the caller exactly as provided, wait for their response, then call confirm-location.",
    },
    {
        "name": "confirm_location",
        "id": "bVMUwyFJQBdJG2cNWSJA",
        "description": "Confirms location after location-resolver needs clarification. ONLY use after you've: 1) Received needs_clarification=true from location-resolver 2) Read the exact message to the caller 3) Received their response. Pass their EXACT words in userResponse along with the options array from location-resolver. Returns the confirmed location_id to use in booking.",
    },
    {
        "name": "find_next_available",
        "id": "QYcS2jqfGR6I5NlZrr3M",
        "description": "Finds the FIRST/NEXT available appointment across multiple days. Use when caller asks: 'when's the next available', 'earliest appointment', 'first available', 'soonest you have', or doesn't specify a date. Searches forward from today to find the first open slot. Can search by practitioner, service, or both. Returns ONE appointment option - the earliest available.",
    },
    {
        "name": "availability_checker",
        "id": "RuKpWtLnDEmPtikxPVQp",
        "description": "Shows ALL available times on a SPECIFIC date. Use when caller mentions a PARTICULAR day: 'tomorrow', 'this Monday', 'December 15th', 'next Friday'. This tool shows multiple time options on that one day only. If caller wants 'next available' without specifying a date, use find-next-available instead. Returns list of all open times on the requested date.",
    },
    {
        "name": "appointment_handler",
        "id": "xIBLqYYP2j20HnEWk96C",
        "description": "Creates the actual appointment booking. This is the ONLY tool that books appointments. ONLY call after: 1) Caller has verbally confirmed they want the specific time 2) You have asked for and received their full name. Required formats: appointmentDate as YYYY-MM-DD, appointmentTime as HH:MM (24-hour), business_id as the number from location-resolver. This completes the booking and returns confirmation.",
    },
    {
        "name": "cancel_appointment",
        "id": "mIIZCPwBnBx6myk2CkkT",
        "description": "Cancels existing appointments. Use when caller says: cancel, can't make it, need to change. Can find appointments by natural description like 'my appointment tomorrow with Dr Smith' or 'my massage next week'. Confirms the specific appointment details before cancelling. Only returns success after the appointment is actually cancelled in the system.",
    },
    {
        "name": "get_practitioner_services",
        "id": "gvAf3sfLSzJJREyiziug",
        "description": "Lists services for ONE practitioner. Use when caller says a practitioner name but NO service: 'I want to see Dr Smith' (but doesn't say for what). Returns the exact service names to offer the caller. This is the simplest practitioner tool - just shows what they do.",
    },
    {
        "name": "get_practitioner_info",
        "id": "lSrq787L3rxtCA5F1QBa",
        "description": "Gets EVERYTHING about a practitioner (all services + all locations). Use ONLY when caller asks specifically about a practitioner: 'What does Dr Smith do?' or 'Where does Dr Smith work?' or when practitioner works at multiple locations. More detailed than needed for basic booking.",
    },
    {
        "name": "get_location_practitioners",
        "id": "EBw6WlVD1rHoQCNcBmnT",
        "description": "Shows WHO works at a location (just names, not availability). Use when caller asks: 'Who works at [location]?' or 'What practitioners do you have at [location]?' Requires locationId from location-resolver first. This is like looking at a staff directory.",
    },
    {
        "name": "get_available_practitioners",
        "id": "gEGy0qwg5TXTeF6d2fYG",
        "description": "Shows WHO has appointments available at a location on a specific date. Use when caller is flexible: 'Who's available at [location] tomorrow?' or 'Any practitioner at [location] this week'. Requires BOTH locationId AND date. Returns only practitioners with actual openings.",
    }
]

def get_ngrok_url():
    try:
        r = requests.get("http://localhost:4040/api/tunnels", timeout=3)
        tunnels = r.json().get("tunnels", [])
        for t in tunnels:
            if t["public_url"].startswith("https://"):
                return t["public_url"]
        return None
    except Exception as e:
        print(f"❌ Could not detect ngrok URL: {str(e)[:100]}")
        return None

def patch_tool(tool, webhook_base_url):
    endpoint = f"/{tool['name'].replace('_', '-')}"
    full_url = f"{webhook_base_url}{endpoint}"
    url = f"{ELEVENLABS_API_URL}/{tool['id']}"

    payload = {
        "name": tool["name"],
        "description": tool["description"],
        "type": "webhook",
        "response_timeout_secs": 20,
        "api_schema": {
            "url": full_url,
            "method": "POST",
            "request_headers": {
                "X-API-Key": WEBHOOK_API_KEY,
                "Content-Type": "application/json"
            },
            "path_params_schema": {},
            "query_params_schema": None,
            "request_body_schema": {
                "type": "object",
                "required": [],
                "description": "No-op placeholder schema update",
                "properties": {}
            }
        },
        "dynamic_variables": {
            "dynamic_variable_placeholders": {}
        }
    }

    headers = {
        "xi-api-key": ELEVENLABS_API_KEY,
        "Content-Type": "application/json"
    }

    try:
        response = requests.patch(url, headers=headers, json=payload, timeout=10)
        if response.status_code == 200:
            print(f"✓ Updated {tool['name']:<30} → {full_url}")
        else:
            print(f"✗ Failed {tool['name']:<30} [{response.status_code}]: {response.text[:100]}")
    except Exception as e:
        print(f"✗ Error {tool['name']:<30}: {str(e)[:100]}")

def main():
    print("=== ElevenLabs Tool URL Updater (Full Metadata + ngrok) ===")

    base_url = get_ngrok_url()
    if not base_url:
        print("❌ ngrok URL not found. Is ngrok running?")
        return

    print(f"🔗 Detected ngrok base URL: {base_url}\n")

    for tool in TOOLS:
        patch_tool(tool, base_url)

    print("\n✅ All tools patched.")

if __name__ == "__main__":
    main()
