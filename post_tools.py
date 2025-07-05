#!/usr/bin/env python3
"""
ElevenLabs Tools Creator
Creates all 10 webhook tools for the Voice Booking System
"""

import requests
import json
import time
from datetime import datetime
from typing import Dict, List, Tuple

# ElevenLabs API configuration
ELEVENLABS_API_KEY = "sk_8ac5a73e17b37d0275ee0a8cce89a4bb53a07ee7f1609692"
ELEVENLABS_API_URL = "https://api.elevenlabs.io/v1/convai/tools"
WEBHOOK_API_KEY = "MS0xNzAyMDE4MzQ3NzQ0MzcyMjM4LUs2YzJodjE2TEM1OVVGM0JTRU1GMHZ1K2Y5V0VmRHNH-au4"

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

def create_tool_config(name: str, description: str, webhook_url: str, parameters: Dict) -> Dict:
    """Create a tool configuration for ElevenLabs"""
    return {
        "tool_config": {
            "name": name,
            "description": description,
            "response_timeout_secs": 20,
            "type": "webhook",
            "api_schema": {
                "url": webhook_url,
                "method": "POST",
                "path_params_schema": {},
                "query_params_schema": None,
                "request_body_schema": {
                    "type": "object",
                    "required": parameters["required"],
                    "description": parameters["description"],
                    "properties": parameters["properties"]
                },
                "request_headers": {
                    "X-API-Key": WEBHOOK_API_KEY,
                    "Content-Type": "application/json"
                },
                "auth_connection": None
            },
            "dynamic_variables": {
                "dynamic_variable_placeholders": {}
            }
        }
    }

def create_all_tools(webhook_base_url: str) -> List[Tuple[str, str, bool, str]]:
    """Create all tools and return results"""
    results = []
    
    # Headers for API calls
    headers = {
        "xi-api-key": ELEVENLABS_API_KEY,
        "Content-Type": "application/json"
    }
    
    # Define all 10 tools
    tools = [
        {
            "name": "location_resolver",
            "description": "Resolves ANY location reference to a specific clinic location ID. Call when location is mentioned (main, usual, Balmain, city, your clinic, etc). Returns one of two responses: 1) SUCCESS: Returns location_id (a number) - use this in subsequent tools 2) NEEDS CLARIFICATION: Returns needs_clarification=true with a message and options list. When this happens, you MUST read the message to the caller exactly as provided, wait for their response, then call confirm-location.",
            "endpoint": "/location-resolver",
            "required": ["locationQuery", "sessionId", "dialedNumber"],
            "properties": {
                "locationQuery": {
                    "type": "string",
                    "description": "The location reference to resolve (exactly what caller said)",
                    "dynamic_variable": "",
                    "constant_value": ""
                },
                "sessionId": {
                    "type": "string",
                    "description": "Current conversation session ID",
                    "dynamic_variable": "",
                    "constant_value": ""
                },
                "dialedNumber": {
                    "type": "string",
                    "description": "The clinic phone number that was dialed",
                    "dynamic_variable": "",
                    "constant_value": ""
                },
                "callerPhone": {
                    "type": "string",
                    "description": "The caller's phone number",
                    "dynamic_variable": "",
                    "constant_value": ""
                },
                "systemCallerID": {
                    "type": "string",
                    "description": "System-provided caller ID if available",
                    "dynamic_variable": "",
                    "constant_value": ""
                }
            }
        },
        {
            "name": "confirm_location",
            "description": "Confirms location after location-resolver needs clarification. ONLY use after you've: 1) Received needs_clarification=true from location-resolver 2) Read the exact message to the caller 3) Received their response. Pass their EXACT words in userResponse along with the options array from location-resolver. Returns the confirmed location_id to use in booking.",
            "endpoint": "/confirm-location",
            "required": ["userResponse", "options", "sessionId", "dialedNumber"],
            "properties": {
                "userResponse": {
                    "type": "string",
                    "description": "User's exact response to location options",
                    "dynamic_variable": "",
                    "constant_value": ""
                },
                "options": {
                    "type": "array",
                    "description": "The location options array from location-resolver",
                    "items": {
                        "type": "string",
                        "description": "Location name option"
                    }
                },
                "sessionId": {
                    "type": "string",
                    "description": "Current conversation session ID",
                    "dynamic_variable": "",
                    "constant_value": ""
                },
                "dialedNumber": {
                    "type": "string",
                    "description": "The clinic phone number that was dialed",
                    "dynamic_variable": "",
                    "constant_value": ""
                },
                "callerPhone": {
                    "type": "string",
                    "description": "The caller's phone number",
                    "dynamic_variable": "",
                    "constant_value": ""
                }
            }
        },
        {
            "name": "find_next_available",
            "description": "Finds the FIRST/NEXT available appointment across multiple days. Use when caller asks: 'when's the next available', 'earliest appointment', 'first available', 'soonest you have', or doesn't specify a date. Searches forward from today to find the first open slot. Can search by practitioner, service, or both. Returns ONE appointment option - the earliest available.",
            "endpoint": "/find-next-available",
            "required": ["sessionId", "dialedNumber"],
            "properties": {
                "service": {
                    "type": "string",
                    "description": "Service name (e.g., 'Massage', 'Acupuncture (Initial)')",
                    "dynamic_variable": "",
                    "constant_value": ""
                },
                "practitioner": {
                    "type": "string",
                    "description": "Practitioner name if specified",
                    "dynamic_variable": "",
                    "constant_value": ""
                },
                "locationId": {
                    "type": "string",
                    "description": "Location ID from location-resolver if location was mentioned",
                    "dynamic_variable": "",
                    "constant_value": ""
                },
                "locationName": {
                    "type": "string",
                    "description": "Location name for response formatting",
                    "dynamic_variable": "",
                    "constant_value": ""
                },
                "maxDays": {
                    "type": "number",
                    "description": "Maximum days to search ahead (default 14)",
                    "dynamic_variable": "",
                    "constant_value": ""
                },
                "sessionId": {
                    "type": "string",
                    "description": "Current conversation session ID",
                    "dynamic_variable": "",
                    "constant_value": ""
                },
                "dialedNumber": {
                    "type": "string",
                    "description": "The clinic phone number that was dialed",
                    "dynamic_variable": "",
                    "constant_value": ""
                }
            }
        },
        {
            "name": "availability_checker",
            "description": "Shows ALL available times on a SPECIFIC date. Use when caller mentions a PARTICULAR day: 'tomorrow', 'this Monday', 'December 15th', 'next Friday'. This tool shows multiple time options on that one day only. If caller wants 'next available' without specifying a date, use find-next-available instead. Returns list of all open times on the requested date.",
            "endpoint": "/availability-checker",
            "required": ["practitioner", "sessionId", "dialedNumber"],
            "properties": {
                "practitioner": {
                    "type": "string",
                    "description": "The practitioner's name",
                    "dynamic_variable": "",
                    "constant_value": ""
                },
                "date": {
                    "type": "string",
                    "description": "The date to check (e.g., 'tomorrow', 'Monday', '2024-12-25')",
                    "dynamic_variable": "",
                    "constant_value": ""
                },
                "appointmentType": {
                    "type": "string",
                    "description": "The type of appointment/service if specified",
                    "dynamic_variable": "",
                    "constant_value": ""
                },
                "location": {
                    "type": "string",
                    "description": "The location name if not yet resolved",
                    "dynamic_variable": "",
                    "constant_value": ""
                },
                "business_id": {
                    "type": "string",
                    "description": "The resolved business ID from location-resolver",
                    "dynamic_variable": "",
                    "constant_value": ""
                },
                "sessionId": {
                    "type": "string",
                    "description": "Current conversation session ID",
                    "dynamic_variable": "",
                    "constant_value": ""
                },
                "dialedNumber": {
                    "type": "string",
                    "description": "The clinic phone number that was dialed",
                    "dynamic_variable": "",
                    "constant_value": ""
                },
                "callerPhone": {
                    "type": "string",
                    "description": "The caller's phone number",
                    "dynamic_variable": "",
                    "constant_value": ""
                }
            }
        },
        {
            "name": "appointment_handler",
            "description": "Creates the actual appointment booking. This is the ONLY tool that books appointments. ONLY call after: 1) Caller has verbally confirmed they want the specific time 2) You have asked for and received their full name. Required formats: appointmentDate as YYYY-MM-DD, appointmentTime as HH:MM (24-hour), business_id as the number from location-resolver. This completes the booking and returns confirmation.",
            "endpoint": "/appointment-handler",
            "required": ["sessionId", "dialedNumber", "patientName", "practitioner", "appointmentType", "appointmentDate", "appointmentTime", "business_id"],
            "properties": {
                "sessionId": {
                    "type": "string",
                    "description": "Current conversation session ID",
                    "dynamic_variable": "",
                    "constant_value": ""
                },
                "dialedNumber": {
                    "type": "string",
                    "description": "The clinic phone number that was dialed",
                    "dynamic_variable": "",
                    "constant_value": ""
                },
                "callerPhone": {
                    "type": "string",
                    "description": "The caller's phone number",
                    "dynamic_variable": "",
                    "constant_value": ""
                },
                "systemCallerID": {
                    "type": "string",
                    "description": "System-provided caller ID if available",
                    "dynamic_variable": "",
                    "constant_value": ""
                },
                "patientName": {
                    "type": "string",
                    "description": "Full name of the patient (required before booking)",
                    "dynamic_variable": "",
                    "constant_value": ""
                },
                "patientPhone": {
                    "type": "string",
                    "description": "Patient's phone number (if different from caller)",
                    "dynamic_variable": "",
                    "constant_value": ""
                },
                "practitioner": {
                    "type": "string",
                    "description": "The practitioner's name",
                    "dynamic_variable": "",
                    "constant_value": ""
                },
                "appointmentType": {
                    "type": "string",
                    "description": "Exact service name (e.g., 'Massage', 'Acupuncture (Initial)', 'Acupuncture (Follow up)')",
                    "dynamic_variable": "",
                    "constant_value": ""
                },
                "appointmentDate": {
                    "type": "string",
                    "description": "Appointment date in YYYY-MM-DD format",
                    "dynamic_variable": "",
                    "constant_value": ""
                },
                "appointmentTime": {
                    "type": "string",
                    "description": "Appointment time in HH:MM format (24-hour)",
                    "dynamic_variable": "",
                    "constant_value": ""
                },
                "business_id": {
                    "type": "string",
                    "description": "The resolved business ID (get from location-resolver first)",
                    "dynamic_variable": "",
                    "constant_value": ""
                },
                "notes": {
                    "type": "string",
                    "description": "Optional notes about the appointment",
                    "dynamic_variable": "",
                    "constant_value": ""
                }
            }
        },
        {
            "name": "cancel_appointment",
            "description": "Cancels existing appointments. Use when caller says: cancel, can't make it, need to change. Can find appointments by natural description like 'my appointment tomorrow with Dr Smith' or 'my massage next week'. Confirms the specific appointment details before cancelling. Only returns success after the appointment is actually cancelled in the system.",
            "endpoint": "/cancel-appointment",
            "required": ["sessionId", "dialedNumber", "callerPhone"],
            "properties": {
                "sessionId": {
                    "type": "string",
                    "description": "Current conversation session ID",
                    "dynamic_variable": "",
                    "constant_value": ""
                },
                "dialedNumber": {
                    "type": "string",
                    "description": "The clinic phone number that was dialed",
                    "dynamic_variable": "",
                    "constant_value": ""
                },
                "callerPhone": {
                    "type": "string",
                    "description": "The caller's phone number",
                    "dynamic_variable": "",
                    "constant_value": ""
                },
                "systemCallerID": {
                    "type": "string",
                    "description": "System-provided caller ID if available",
                    "dynamic_variable": "",
                    "constant_value": ""
                },
                "appointmentId": {
                    "type": "string",
                    "description": "Specific appointment ID if mentioned",
                    "dynamic_variable": "",
                    "constant_value": ""
                },
                "appointmentDetails": {
                    "type": "string",
                    "description": "Natural language description of the appointment to cancel",
                    "dynamic_variable": "",
                    "constant_value": ""
                },
                "reason": {
                    "type": "string",
                    "description": "Reason for cancellation if provided",
                    "dynamic_variable": "",
                    "constant_value": ""
                }
            }
        },
        {
            "name": "get_practitioner_services",
            "description": "Lists services for ONE practitioner. Use when caller says a practitioner name but NO service: 'I want to see Dr Smith' (but doesn't say for what). Returns the exact service names to offer the caller. This is the simplest practitioner tool - just shows what they do.",
            "endpoint": "/get-practitioner-services",
            "required": ["practitioner", "dialedNumber", "sessionId"],
            "properties": {
                "practitioner": {
                    "type": "string",
                    "description": "The practitioner's name",
                    "dynamic_variable": "",
                    "constant_value": ""
                },
                "dialedNumber": {
                    "type": "string",
                    "description": "The clinic phone number that was dialed",
                    "dynamic_variable": "",
                    "constant_value": ""
                },
                "sessionId": {
                    "type": "string",
                    "description": "Current conversation session ID",
                    "dynamic_variable": "",
                    "constant_value": ""
                }
            }
        },
        {
            "name": "get_practitioner_info",
            "description": "Gets EVERYTHING about a practitioner (all services + all locations). Use ONLY when caller asks specifically about a practitioner: 'What does Dr Smith do?' or 'Where does Dr Smith work?' or when practitioner works at multiple locations. More detailed than needed for basic booking.",
            "endpoint": "/get-practitioner-info",
            "required": ["practitioner", "dialedNumber", "sessionId"],
            "properties": {
                "practitioner": {
                    "type": "string",
                    "description": "The practitioner's name",
                    "dynamic_variable": "",
                    "constant_value": ""
                },
                "dialedNumber": {
                    "type": "string",
                    "description": "The clinic phone number that was dialed",
                    "dynamic_variable": "",
                    "constant_value": ""
                },
                "sessionId": {
                    "type": "string",
                    "description": "Current conversation session ID",
                    "dynamic_variable": "",
                    "constant_value": ""
                }
            }
        },
        {
            "name": "get_location_practitioners",
            "description": "Shows WHO works at a location (just names, not availability). Use when caller asks: 'Who works at [location]?' or 'What practitioners do you have at [location]?' Requires locationId from location-resolver first. This is like looking at a staff directory.",
            "endpoint": "/get-location-practitioners",
            "required": ["locationId", "locationName", "dialedNumber", "sessionId"],
            "properties": {
                "locationId": {
                    "type": "string",
                    "description": "Location ID from location-resolver",
                    "dynamic_variable": "",
                    "constant_value": ""
                },
                "locationName": {
                    "type": "string",
                    "description": "Location name for response formatting",
                    "dynamic_variable": "",
                    "constant_value": ""
                },
                "dialedNumber": {
                    "type": "string",
                    "description": "The clinic phone number that was dialed",
                    "dynamic_variable": "",
                    "constant_value": ""
                },
                "sessionId": {
                    "type": "string",
                    "description": "Current conversation session ID",
                    "dynamic_variable": "",
                    "constant_value": ""
                }
            }
        },
        {
            "name": "get_available_practitioners",
            "description": "Shows WHO has appointments available at a location on a specific date. Use when caller is flexible: 'Who's available at [location] tomorrow?' or 'Any practitioner at [location] this week'. Requires BOTH locationId AND date. Returns only practitioners with actual openings.",
            "endpoint": "/get-available-practitioners",
            "required": ["locationId", "locationName", "date", "dialedNumber", "sessionId"],
            "properties": {
                "locationId": {
                    "type": "string",
                    "description": "Location ID from location-resolver",
                    "dynamic_variable": "",
                    "constant_value": ""
                },
                "locationName": {
                    "type": "string",
                    "description": "Location name for response formatting",
                    "dynamic_variable": "",
                    "constant_value": ""
                },
                "date": {
                    "type": "string",
                    "description": "Date to check availability (e.g., 'today', 'tomorrow')",
                    "dynamic_variable": "",
                    "constant_value": ""
                },
                "dialedNumber": {
                    "type": "string",
                    "description": "The clinic phone number that was dialed",
                    "dynamic_variable": "",
                    "constant_value": ""
                },
                "sessionId": {
                    "type": "string",
                    "description": "Current conversation session ID",
                    "dynamic_variable": "",
                    "constant_value": ""
                }
            }
        }
    ]
    
    # Create each tool
    for tool in tools:
        webhook_url = f"{webhook_base_url}{tool['endpoint']}"
        
        parameters = {
            "required": tool["required"],
            "description": f"Parameters for {tool['name']}",
            "properties": tool["properties"]
        }
        
        config = create_tool_config(
            name=tool["name"],
            description=tool["description"],
            webhook_url=webhook_url,
            parameters=parameters
        )
        
        print(f"Creating tool: {tool['name']}...", end="", flush=True)
        
        try:
            response = requests.post(
                ELEVENLABS_API_URL,
                headers=headers,
                json=config,
                timeout=30
            )
            
            if response.status_code == 200 or response.status_code == 201:
                result = response.json()
                tool_id = result.get("id", "NO_ID")
                print(f" ✓")
                results.append((tool["name"], tool_id, True, "Success"))
            else:
                print(f" ✗")
                error_msg = f"Status {response.status_code}: {response.text[:100]}"
                results.append((tool["name"], "FAILED", False, error_msg))
                
        except Exception as e:
            print(f" ✗")
            results.append((tool["name"], "ERROR", False, str(e)[:100]))
        
        # Small delay between API calls
        time.sleep(0.5)
    
    return results

def print_results_table(results: List[Tuple[str, str, bool, str]]):
    """Print results in a formatted table"""
    print("\n" + "="*80)
    print(f"{'Tool Name':<30} | {'Tool ID':<40} | {'Status':<10}")
    print("="*80)
    
    for name, tool_id, success, message in results:
        status = "✓ Success" if success else "✗ Failed"
        if success:
            print(f"{name:<30} | {tool_id:<40} | {status:<10}")
        else:
            print(f"{name:<30} | {tool_id:<40} | {status:<10}")
            print(f"{'':>30} | Error: {message}")
    
    print("="*80)
    
    # Summary
    successful = sum(1 for _, _, success, _ in results if success)
    failed = len(results) - successful
    
    print(f"\nSummary: {successful} tools created successfully, {failed} failed")
    
    # Save successful tool IDs
    if successful > 0:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"elevenlabs_tool_ids_{timestamp}.json"
        
        tool_data = {
            "created_at": datetime.now().isoformat(),
            "tools": {
                name: tool_id 
                for name, tool_id, success, _ in results 
                if success
            }
        }
        
        with open(filename, 'w') as f:
            json.dump(tool_data, f, indent=2)
        
        print(f"\nTool IDs saved to: {filename}")

def main():
    print("ElevenLabs Voice Booking Tools Creator")
    print("="*50)

    # Auto-detect ngrok URL
    webhook_base = get_ngrok_url()
    if not webhook_base:
        print("❌ ngrok URL not found. Is ngrok running?")
        return

    if webhook_base.endswith("/"):
        webhook_base = webhook_base[:-1]

    print(f"\nUsing webhook base URL: {webhook_base}")
    print("\nCreating tools...")
    print("-"*50)

    # Create all tools
    results = create_all_tools(webhook_base)

    # Print results
    print_results_table(results)

if __name__ == "__main__":
    main()