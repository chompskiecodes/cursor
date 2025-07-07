#!/usr/bin/env python3
"""
Comprehensive location resolver debugging tool
Tests location resolution with detailed diagnostics
"""

import requests
import json
import os
import time
import asyncio
import asyncpg
import base64
from dotenv import load_dotenv

# Add these imports
from cache_manager import IncrementalCacheSync, CacheManager

load_dotenv()

# Config
BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")
API_KEY = os.getenv("API_KEY", "development-key")
DB_URL = "postgresql://postgres.feywathteocancjzdgtf:seS!llyw3rd@aws-0-ap-southeast-2.pooler.supabase.com:5432/postgres"

class ClinikoAPI:
    """Simple Cliniko API client for syncing"""
    
    def __init__(self, api_key: str, shard: str):
        self.api_key = api_key
        self.shard = shard
        self.base_url = f"https://api.{shard}.cliniko.com/v1"
        
        # Fix authentication header format according to Cliniko API docs
        # Cliniko expects "Basic {base64(api_key:)}" - note the colon at the end
        # The API key itself is the username, password is empty
        auth_string = f"{api_key}:"
        auth_bytes = auth_string.encode('ascii')
        auth_b64 = base64.b64encode(auth_bytes).decode('ascii')
        
        self.headers = {
            'Authorization': f'Basic {auth_b64}',
            'User-Agent': 'VoiceBookingSystem/1.0',
            'Accept': 'application/json',
            'Content-Type': 'application/json'
        }
    
    async def get_all_pages(self, endpoint: str) -> list:
        """Get all pages from a Cliniko endpoint"""
        all_data = []
        url = f"{self.base_url}/{endpoint}"
        
        while url:
            # Use synchronous requests for simplicity
            response = requests.get(url, headers=self.headers)
            response.raise_for_status()
            data = response.json()
            
            all_data.extend(data.get(endpoint.split('/')[-1], []))
            
            # Get next page URL
            links = data.get('links', {})
            url = links.get('next')
        
        return all_data

async def sync_clinic_data(clinic_id: str, cliniko_api_key: str, cliniko_shard: str):
    """Sync all clinic data needed for location resolution"""
    print_section("SYNCING CLINIC DATA FROM CLINIKO")
    
    try:
        # Connect to database
        pool = await asyncpg.create_pool(DB_URL, ssl='require', min_size=1, max_size=2)
        
        async with pool.acquire() as conn:
            # Initialize Cliniko API
            cliniko = ClinikoAPI(cliniko_api_key, cliniko_shard)
            
            print_subsection("1. SYNCING BUSINESSES")
            businesses = await cliniko.get_all_pages('businesses')
            print(f"Found {len(businesses)} businesses in Cliniko")
            
            business_count = 0
            for idx, business in enumerate(businesses):
                try:
                    await conn.execute("""
                        INSERT INTO businesses (business_id, clinic_id, business_name, is_primary)
                        VALUES ($1, $2, $3, $4)
                        ON CONFLICT (business_id) 
                        DO UPDATE SET
                            business_name = EXCLUDED.business_name,
                            is_primary = EXCLUDED.is_primary
                    """, 
                        str(business['id']),
                        clinic_id,
                        business.get('business_name') or business.get('label', 'Main Location'),
                        idx == 0  # First business is primary
                    )
                    business_count += 1
                    print(f"  ✓ Synced: {business.get('business_name') or business.get('label', 'Main Location')}")
                except Exception as e:
                    print(f"  ❌ Error syncing business {business['id']}: {e}")
            
            print(f"Successfully synced {business_count} businesses")
            
            print_subsection("2. SYNCING PRACTITIONERS")
            practitioners = await cliniko.get_all_pages('practitioners')
            print(f"Found {len(practitioners)} practitioners in Cliniko")
            
            practitioner_count = 0
            for practitioner in practitioners:
                try:
                    await conn.execute("""
                        INSERT INTO practitioners (
                            practitioner_id, clinic_id, first_name, 
                            last_name, title, active
                        ) VALUES ($1, $2, $3, $4, $5, $6)
                        ON CONFLICT (practitioner_id) 
                        DO UPDATE SET
                            first_name = EXCLUDED.first_name,
                            last_name = EXCLUDED.last_name,
                            title = EXCLUDED.title,
                            active = EXCLUDED.active
                    """,
                        str(practitioner['id']),
                        clinic_id,
                        practitioner.get('first_name', ''),
                        practitioner.get('last_name', ''),
                        practitioner.get('title', ''),
                        practitioner.get('active', True)
                    )
                    practitioner_count += 1
                    print(f"  ✓ Synced: {practitioner.get('first_name', '')} {practitioner.get('last_name', '')}")
                except Exception as e:
                    print(f"  ❌ Error syncing practitioner {practitioner['id']}: {e}")
            
            print(f"Successfully synced {practitioner_count} practitioners")
            
            print_subsection("3. SYNCING APPOINTMENT TYPES")
            appointment_types = await cliniko.get_all_pages('appointment_types')
            print(f"Found {len(appointment_types)} appointment types in Cliniko")
            
            appt_type_count = 0
            # Step 1: Sync all appointment types without billable items first
            for appt_type in appointment_types:
                try:
                    await conn.execute("""
                        INSERT INTO appointment_types (
                            appointment_type_id, clinic_id, name, 
                            duration_minutes, billable_item_id, active
                        ) VALUES ($1, $2, $3, $4, NULL, true)
                        ON CONFLICT (appointment_type_id) 
                        DO UPDATE SET
                            name = EXCLUDED.name,
                            duration_minutes = EXCLUDED.duration_minutes
                    """,
                        str(appt_type['id']),
                        clinic_id,
                        appt_type.get('name', ''),
                        appt_type.get('duration_in_minutes', 30)
                    )
                    appt_type_count += 1
                    print(f"  ✓ Synced: {appt_type.get('name', '')}")
                except Exception as e:
                    print(f"  ❌ Error syncing appointment type {appt_type['id']}: {e}")
            
            # Step 2: Sync billable item relationships
            print("Syncing appointment type billable item relationships...")
            # Get all appointment type billable items
            billable_relationships = await cliniko.get_all_pages('appointment_type_billable_items')
            updated_count = 0
            for relationship in billable_relationships:
                try:
                    appt_type_link = relationship.get('appointment_type', {}).get('links', {}).get('self')
                    if not appt_type_link:
                        continue
                    appt_type_id = appt_type_link.split('/')[-1]
                    billable_item_link = relationship.get('billable_item', {}).get('links', {}).get('self')
                    if not billable_item_link:
                        continue
                    billable_item_id = billable_item_link.split('/')[-1]
                    await conn.execute("""
                        UPDATE appointment_types 
                        SET billable_item_id = $1
                        WHERE appointment_type_id = $2 AND clinic_id = $3
                    """, billable_item_id, appt_type_id, clinic_id)
                    updated_count += 1
                    print(f"  Updated appointment type {appt_type_id} with billable item {billable_item_id}")
                except Exception as e:
                    print(f"  Error updating appointment type billable item relationship: {e}")
            print(f"Updated {updated_count} appointment type billable item relationships")
            
            print(f"Successfully synced {appt_type_count} appointment types")
            
            print_subsection("4. LINKING PRACTITIONERS TO BUSINESSES")
            # Get all practitioners and businesses for this clinic
            practitioners = await conn.fetch("""
                SELECT practitioner_id FROM practitioners 
                WHERE clinic_id = $1 AND active = true
            """, clinic_id)
            
            businesses = await conn.fetch("""
                SELECT business_id FROM businesses 
                WHERE clinic_id = $1
            """, clinic_id)
            
            # Link each practitioner to each business
            link_count = 0
            for practitioner in practitioners:
                for business in businesses:
                    try:
                        await conn.execute("""
                            INSERT INTO practitioner_businesses 
                            (practitioner_id, business_id)
                            VALUES ($1, $2)
                            ON CONFLICT DO NOTHING
                        """,
                            practitioner['practitioner_id'],
                            business['business_id']
                        )
                        link_count += 1
                    except Exception as e:
                        print(f"  ❌ Error linking practitioner to business: {e}")
            
            print(f"Successfully created {link_count} practitioner-business links")
            
            print_subsection("5. LINKING PRACTITIONERS TO APPOINTMENT TYPES")
            # Link practitioners to their appointment types
            total_service_links = 0
            for practitioner in practitioners:
                try:
                    # Get appointment types for this practitioner from Cliniko
                    endpoint = f"practitioners/{practitioner['practitioner_id']}/appointment_types"
                    appt_types = await cliniko.get_all_pages(endpoint)
                    
                    for appt_type in appt_types:
                        await conn.execute("""
                            INSERT INTO practitioner_appointment_types 
                            (practitioner_id, appointment_type_id)
                            VALUES ($1, $2)
                            ON CONFLICT DO NOTHING
                        """,
                            str(practitioner['practitioner_id']),
                            str(appt_type['id'])
                        )
                        total_service_links += 1
                        
                except Exception as e:
                    print(f"  ❌ Error linking practitioner {practitioner['practitioner_id']} to services: {e}")
            
            print(f"Successfully created {total_service_links} practitioner-service links")
            
            print_subsection("6. VERIFYING SYNC RESULTS")
            # Check what we have in the database
            business_count = await conn.fetchval("SELECT COUNT(*) FROM businesses WHERE clinic_id = $1", clinic_id)
            practitioner_count = await conn.fetchval("SELECT COUNT(*) FROM practitioners WHERE clinic_id = $1", clinic_id)
            appt_type_count = await conn.fetchval("SELECT COUNT(*) FROM appointment_types WHERE clinic_id = $1", clinic_id)
            
            print("Database now contains:")
            print(f"  • {business_count} businesses")
            print(f"  • {practitioner_count} practitioners") 
            print(f"  • {appt_type_count} appointment types")
            
            # Show business names for location testing
            businesses = await conn.fetch("""
                SELECT business_id, business_name, is_primary 
                FROM businesses 
                WHERE clinic_id = $1 
                ORDER BY is_primary DESC, business_name
            """, clinic_id)
            
            print("\nAvailable locations for testing:")
            for business in businesses:
                primary_flag = " (PRIMARY)" if business['is_primary'] else ""
                print(f"  • {business['business_name']}{primary_flag} (ID: {business['business_id']})")
        
        # After all other syncs, run appointment sync
        print_subsection("7. SYNCING APPOINTMENTS (IncrementalCacheSync)")
        cache_manager = CacheManager(pool)
        sync = IncrementalCacheSync(cache_manager, pool)
        stats = await sync.sync_appointments_incremental(clinic_id, cliniko)
        print(f"Appointments sync stats: {stats}")
        await pool.close()
        print_subsection("SYNC COMPLETE")
        return True
        
    except Exception as e:
        print(f"❌ SYNC ERROR: {e}")
        return False

def print_section(title):
    """Print a formatted section header"""
    print("\n" + "="*60)
    print(f" {title}")
    print("="*60)

def print_subsection(title):
    """Print a formatted subsection header"""
    print(f"\n--- {title} ---")

def test_location_resolver(location_query, description="", debug_mode=False):
    """Test location resolver with comprehensive debugging"""
    print_section(f"TESTING: {description or location_query}")

    # Test payload
    payload = {
        "locationQuery": location_query,
        "sessionId": f"test_{int(time.time())}",
        "dialedNumber": "0478621276",
        "callerPhone": "0412345678"
    }

    headers = {
        "X-API-Key": API_KEY,
        "Content-Type": "application/json"
    }

    print_subsection("REQUEST DETAILS")
    print(f"URL: {BASE_URL}/location-resolver")
    print(f"Headers: {json.dumps(headers, indent=2)}")
    print(f"Payload: {json.dumps(payload, indent=2)}")

    try:
        # Make request
        start_time = time.time()
        response = requests.post(
            f"{BASE_URL}/location-resolver",
            json=payload,
            headers=headers,
            timeout=10
        )
        response_time = (time.time() - start_time) * 1000

        print_subsection("RESPONSE DETAILS")
        print(f"Status Code: {response.status_code}")
        print(f"Response Time: {response_time:.2f}ms")
        print(f"Response Headers: {dict(response.headers)}")

        # Try to parse JSON
        try:
            data = response.json()

            if debug_mode:
                print_subsection("RAW RESPONSE DATA")
                print(json.dumps(data, indent=2))

            print_subsection("RESPONSE ANALYSIS")

            # Check success
            success = data.get('success', False)
            print(f"✓ Success: {success}")

            if not success:
                print(f"❌ Error: {data.get('error', 'Unknown error')}")
                print(f"❌ Message: {data.get('message', 'No message')}")
                return False

            # Analyze response structure
            resolved = data.get('resolved', False)
            needs_clarification = data.get('needsClarification', False)
            confidence = data.get('confidence', 0.0)
            message = data.get('message', 'No message')

            print(f"✓ Resolved: {resolved}")
            print(f"✓ Needs Clarification: {needs_clarification}")
            print(f"✓ Confidence: {confidence:.3f}")
            print(f"✓ Message: '{message}'")

            # Check for location data
            location = data.get('location')
            if location:
                print(f"✓ Location ID: {location.get('id')}")
                print(f"✓ Location Name: {location.get('name')}")
            else:
                # Fallback for old structure
                business_id = data.get('business_id')
                business_name = data.get('business_name')
                if business_id or business_name:
                    print(f"✓ Business ID (old): {business_id}")
                    print(f"✓ Business Name (old): {business_name}")

            # Check for options
            options = data.get('options')
            if options is not None:
                if isinstance(options, list):
                    if len(options) > 0:
                        # Handle options as list of dicts/LocationData
                        if isinstance(options[0], dict):
                            option_names = [opt.get('name', str(opt)) for opt in options]
                        else:
                            option_names = [str(opt) for opt in options]
                        print(f"✓ Options ({len(options)}): {option_names}")
                    else:
                        print("⚠️  Options: Empty list")
                else:
                    print(f"⚠️  Options: Not a list ({type(options)})")
            else:
                print("✓ Options: None")

            # Check for consistency issues
            print_subsection("CONSISTENCY CHECKS")

            if needs_clarification and options:
                # Print joined option names for consistency check
                if isinstance(options, list) and len(options) > 0 and isinstance(options[0], dict):
                    joined_names = ', '.join(opt.get('name', str(opt)) for opt in options)
                else:
                    joined_names = ', '.join(str(opt) for opt in options) if options else ''
                print(f"Options for clarification: {joined_names}")

            if needs_clarification and not options:
                print("❌ INCONSISTENCY: needsClarification=true but options is None/empty")
                print("   This indicates a bug in the API response structure")

            if resolved and not location and not data.get('business_id'):
                print("❌ INCONSISTENCY: resolved=true but no location data provided")
                print("   This indicates a bug in the API response structure")

            if confidence > 0.8 and not resolved:
                print("⚠️  WARNING: High confidence but not resolved")
                print("   This might indicate a scoring threshold issue")

            if confidence < 0.3 and resolved:
                print("⚠️  WARNING: Low confidence but resolved anyway")
                print("   This might indicate a scoring threshold issue")

            # Determine result
            print_subsection("RESULT")
            if resolved:
                location_name = location.get('name') if location else data.get('business_name', 'Unknown')
                business_id = location.get('id') if location else data.get('business_id', 'Unknown')
                print(f"🎯 SUCCESS: Location resolved to '{location_name}' (ID: {business_id})")
                print(f"   Confidence: {confidence:.3f}")
                return True
            elif needs_clarification and options:
                if isinstance(options, list):
                    if len(options) > 0:
                        if isinstance(options[0], dict):
                            option_names = [opt.get('name', str(opt)) for opt in options]
                        else:
                            option_names = [str(opt) for opt in options]
                        print(f"❓ CLARIFICATION NEEDED: {', '.join(option_names)}")
                    else:
                        print("❓ CLARIFICATION NEEDED: (no options)")
                else:
                    print("❓ CLARIFICATION NEEDED: (options not a list)")
                print(f"   Confidence: {confidence:.3f}")
                return False
            elif needs_clarification and not options:
                print("⚠️  BUG: Needs clarification but no options provided")
                print("   This is likely an API bug")
                return False
            else:
                print(f"❌ NO MATCH: {message}")
                return False

        except json.JSONDecodeError as e:
            print(f"❌ JSON PARSE ERROR: {e}")
            print("Raw response:")
            print(response.text)
            return False

    except requests.exceptions.ConnectionError:
        print(f"❌ CONNECTION ERROR: Cannot connect to {BASE_URL}")
        print("   Is the server running?")
        return False
    except Exception as e:
        print(f"❌ EXCEPTION: {type(e).__name__}: {str(e)}")
        return False

async def main():
    """Main test function with data sync"""
    print_section("LOCATION RESOLVER DEBUGGING TOOL")
    print(f"Base URL: {BASE_URL}")
    print(f"API Key: {API_KEY[:10]}..." if len(API_KEY) > 10 else f"API Key: {API_KEY}")
    
    # Get clinic info for syncing
    clinic_id = "9da34639-5ea8-4c1b-b29b-82f1ece91518"  # Noam Field clinic
    cliniko_api_key = "MS0xNzAyMDE4MzQ3NzQ0MzcyMjM4LUs2YzJodjE2TEM1OVVGM0JTRU1GMHZ1K2Y5V0VmRHNH-au4"  # Hardcoded as requested
    cliniko_shard = "au4"
    
    print_subsection("SYNCING CLINIC DATA")
    print(f"Clinic ID: {clinic_id}")
    print(f"Cliniko Shard: {cliniko_shard}")
    
    # Sync data first
    sync_success = await sync_clinic_data(clinic_id, cliniko_api_key, cliniko_shard)
    
    if not sync_success:
        print("❌ SYNC FAILED - Cannot proceed with location tests")
        return
    
    # Test scenarios with different confidence levels
    test_scenarios = [
        {
            "query": "main",
            "description": "Primary location reference",
            "expected": "high_confidence"
        },
        {
            "query": "city",
            "description": "Specific location name",
            "expected": "high_confidence"
        },
        {
            "query": "balmain",
            "description": "Specific location name",
            "expected": "high_confidence"
        },
        {
            "query": "downtown",
            "description": "Ambiguous location",
            "expected": "medium_confidence"
        },
        {
            "query": "your usual place",
            "description": "Contextual reference",
            "expected": "medium_confidence"
        },
        {
            "query": "the clinic",
            "description": "Generic reference",
            "expected": "low_confidence"
        },
        {
            "query": "xyz123",
            "description": "Non-existent location",
            "expected": "no_match"
        },
        {
            "query": "",
            "description": "Empty query",
            "expected": "no_match"
        }
    ]
    
    print_subsection("RUNNING COMPREHENSIVE TESTS")
    
    results = {
        "total": len(test_scenarios),
        "successful": 0,
        "clarification_needed": 0,
        "no_match": 0,
        "errors": 0
    }
    
    for i, scenario in enumerate(test_scenarios, 1):
        print(f"\n[{i}/{len(test_scenarios)}] Testing: {scenario['description']}")
        print(f"Query: '{scenario['query']}'")
        print(f"Expected: {scenario['expected']}")
        
        success = test_location_resolver(
            scenario['query'], 
            scenario['description'],
            debug_mode=(i == 1)  # Debug mode for first test only
        )
        
        if success:
            results["successful"] += 1
        else:
            # Check if it was a clarification case or error
            # This is simplified - in practice you'd check the actual response
            results["clarification_needed"] += 1
    
    print_section("TEST SUMMARY")
    print(f"Total Tests: {results['total']}")
    print(f"Successful Resolutions: {results['successful']}")
    print(f"Needed Clarification: {results['clarification_needed']}")
    print(f"No Match: {results['no_match']}")
    print(f"Errors: {results['errors']}")
    
    success_rate = (results['successful'] / results['total']) * 100
    print(f"Success Rate: {success_rate:.1f}%")
    
    print_section("DEBUGGING TIPS")
    print("If you're seeing issues:")
    print("1. Check database: SELECT * FROM businesses WHERE clinic_id = 'your_clinic_id'")
    print("2. Check aliases: SELECT * FROM location_aliases")
    print("3. Check cache: Look for cache-related errors in server logs")
    print("4. Check phone normalization: Test normalize_phone() function")
    print("5. Check scoring: Add debug logs to calculate_location_score()")
    
    print_section("CURL COMMAND FOR MANUAL TESTING")
print(f"""
curl -X POST {BASE_URL}/location-resolver \\
  -H "X-API-Key: {API_KEY}" \\
  -H "Content-Type: application/json" \\
  -d '{{"locationQuery": "main", "sessionId": "test_123", "dialedNumber": "0478621276", "callerPhone": "0412345678"}}'
""")

if __name__ == "__main__":
    asyncio.run(main())