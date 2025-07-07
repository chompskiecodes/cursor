# tools/availability_tools.py
"""Availability-related endpoints for the Voice Booking System"""

from fastapi import APIRouter, Request, Depends, BackgroundTasks
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta, date
import logging
import asyncpg

# Local imports
from .dependencies import verify_api_key, get_db, get_cache
from models import AvailabilityRequest, create_error_response
from database import (
    get_clinic_by_dialed_number, match_practitioner, match_service,
    get_practitioner_services, match_business,
    normalize_for_matching
)
from cliniko import ClinikoAPI
from utils import parse_date_request
from payload_logger import payload_logger
from tools.timezone_utils import (
    get_clinic_timezone,
    convert_utc_to_local,
    format_time_for_voice
)
from .cache_utils import check_and_trigger_sync
from shared_types import CacheManagerProtocol
from models import (
    AvailabilityResponse,
    PractitionerData,
    LocationData,
    TimeSlotData,
    GetAvailablePractitionersResponse,
    NextAvailableResponse
)

logger = logging.getLogger(__name__)

# Create router
router = APIRouter(tags=["availability"])

async def check_practitioner_availability(
    clinic: Dict[str, Any],
    practitioner: Dict[str, Any],
    service: Dict[str, Any],
    appointment_date: date,
    location: Optional[Dict[str, Any]],
    db: asyncpg.Pool,
    cache: CacheManagerProtocol
) -> List[Dict[str, Any]]:
    """Check availability for a specific practitioner and service"""
    try:
        # Initialize Cliniko API
        cliniko = ClinikoAPI(
            clinic.cliniko_api_key,
            clinic.cliniko_shard,
            "VoiceBookingSystem/1.0"
        )
        
        # Determine business_id to use
        business_id = None
        if location:
            business_id = location.get('business_id')
        else:
            # Get the first business where this practitioner works
            query = """
                SELECT pb.business_id 
                FROM practitioner_businesses pb 
                WHERE pb.practitioner_id = $1 
                LIMIT 1
            """
            async with db.acquire() as conn:
                row = await conn.fetchrow(query, practitioner['practitioner_id'])
                if row:
                    business_id = row['business_id']
        
        if not business_id:
            logger.error(f"No business found for practitioner {practitioner['practitioner_id']}")
            return []
        
        # Check availability using Cliniko API
        from_date = appointment_date.isoformat()
        to_date = appointment_date.isoformat()
        
        logger.info(f"Checking availability for practitioner {practitioner['practitioner_id']} at business {business_id} on {from_date}")
        
        available_times = await cliniko.get_available_times(
            business_id=business_id,
            practitioner_id=practitioner['practitioner_id'],
            appointment_type_id=service['appointment_type_id'],
            from_date=from_date,
            to_date=to_date
        )
        
        logger.info(f"Cliniko API returned {len(available_times) if available_times else 0} slots")
        
        if available_times and len(available_times) > 0:
            return available_times
        else:
            return []
            
    except Exception as e:
        logger.error(f"Error checking practitioner availability: {e}")
        logger.error(f"Exception type: {type(e).__name__}")
        logger.error(f"Exception details: {str(e)}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        return []

@router.post("/availability-checker")
async def check_availability(
    request: Request,
    background_tasks: BackgroundTasks,
    db: asyncpg.Pool = Depends(get_db),
    cache: CacheManagerProtocol = Depends(get_cache)
) -> Dict[str, Any]:
    """Check availability for a specific practitioner and service"""
    try:
        body = await request.json()
        availability_request = AvailabilityRequest(**body)
        
        # Get clinic information
        clinic = await get_clinic_by_dialed_number(
            availability_request.dialedNumber, db
        )
        if not clinic:
            return create_error_response(
                error_code="clinic_not_found",
                message="I couldn't find your clinic. Please check your phone number.",
                session_id=availability_request.sessionId
            )
        
        # Parse date
        appointment_date = parse_date_request(availability_request.date)
        if not appointment_date:
            return create_error_response(
                error_code="invalid_date",
                message="I couldn't understand that date. Please try again.",
                session_id=availability_request.sessionId
            )
        
        # Match practitioner
        practitioner_match = await match_practitioner(
            clinic.clinic_id,
            availability_request.practitioner,
            db
        )
        
        if not practitioner_match.get("matches"):
            return create_error_response(
                error_code="practitioner_not_found",
                message=f"I couldn't find a practitioner named {availability_request.practitioner}.",
                session_id=availability_request.sessionId
            )
        
        practitioner = practitioner_match["matches"][0]
        
        # Ensure full_name is available
        if 'full_name' not in practitioner and 'first_name' in practitioner and 'last_name' in practitioner:
            practitioner['full_name'] = f"{practitioner['first_name']} {practitioner['last_name']}"
        
        # Match service
        service_match = await match_service(
                            clinic.clinic_id,
            practitioner["practitioner_id"],
            availability_request.appointmentType,
            db
        )
        
        if not service_match:
            return create_error_response(
                error_code="service_not_found",
                message=f"I couldn't find the service '{availability_request.appointmentType}'.",
                session_id=availability_request.sessionId
            )
        
        # Get location if specified
        location = None
        if availability_request.location:
            location_match = await match_business(
                                    clinic.clinic_id,
                availability_request.location,
                db
            )
            if location_match:
                location = location_match
        elif availability_request.business_id:
            # If business_id is provided directly, create a location object
            query = """
                SELECT business_id, business_name
                FROM businesses
                WHERE business_id = $1 AND clinic_id = $2
            """
            async with db.acquire() as conn:
                row = await conn.fetchrow(query, availability_request.business_id, clinic.clinic_id)
                if row:
                    location = {
                        'business_id': row['business_id'],
                        'business_name': row['business_name']
                    }
        
        # Check availability
        available_times = await check_practitioner_availability(
            clinic,
            practitioner,
            service_match,
            appointment_date,
            location,
            db,
            cache
        )
        
        logger.info(f"Availability check result: {len(available_times) if available_times else 0} slots found")
        
        if not available_times:
            # --- SUPABASE-ONLY FALLBACK ---
            # Try to get slots from Supabase cache directly
            cached_slots = await cache.get_availability(
                practitioner['practitioner_id'],
                location['business_id'] if location else None,
                appointment_date
            )
            if cached_slots:
                logger.warning(f"[SUPABASE-ONLY FALLBACK] Returning {len(cached_slots)} slots from cache for practitioner {practitioner['practitioner_id']} at business {location['business_id'] if location else None} on {appointment_date}")
                available_times_local = []
                clinic_tz = get_clinic_timezone(clinic)
                for slot in cached_slots:
                    slot_utc = datetime.fromisoformat(slot['appointment_start'].replace('Z', '+00:00'))
                    slot_local = slot_utc.astimezone(clinic_tz)
                    available_times_local.append(format_time_for_voice(slot_local))
                return {
                    "success": True,
                    "sessionId": availability_request.sessionId,
                    "available_times": available_times_local,
                    "practitioner": practitioner["full_name"],
                    "service": service_match.get("name", "the requested service"),
                    "date": appointment_date.strftime("%A, %B %d, %Y"),
                    "message": f"[From local system] {practitioner['full_name']} has these times available on {appointment_date.strftime('%A, %B %d, %Y')}: {', '.join(available_times_local)}. (Note: These may be slightly out of date.)"
                }
            # If no availability on requested date, search for next available slot across all locations
            logger.info(f"No availability found for {practitioner['full_name']} on {appointment_date}, searching for next available slot...")
            
            # Initialize Cliniko API for the search
            cliniko = ClinikoAPI(
                clinic.cliniko_api_key,
                clinic.cliniko_shard,
                "VoiceBookingSystem/1.0"
            )
            
            # Get all businesses where this practitioner works
            query = """
                SELECT DISTINCT 
                    pb.business_id,
                    b.business_name
                FROM practitioner_businesses pb
                JOIN businesses b ON pb.business_id = b.business_id
                WHERE pb.practitioner_id = $1
            """
            async with db.acquire() as conn:
                businesses = await conn.fetch(query, practitioner['practitioner_id'])
            
            logger.info(f"Found {len(businesses)} businesses for practitioner {practitioner['full_name']}")
            
            # Search for next available slot across all locations
            earliest_slot = None
            earliest_date = None
            earliest_location = None
            
            clinic_tz = get_clinic_timezone(clinic)
            search_start = datetime.now(clinic_tz).date()
            search_end = search_start + timedelta(days=14)  # Search next 2 weeks
            
            for days_ahead in range(14):
                check_date = search_start + timedelta(days=days_ahead)
                
                for biz in businesses:
                    try:
                        # Check availability for this practitioner/service/location combination
                        available_times = await cliniko.get_available_times(
                            business_id=biz['business_id'],
                            practitioner_id=practitioner['practitioner_id'],
                            appointment_type_id=service_match['appointment_type_id'],
                            from_date=check_date.isoformat(),
                            to_date=check_date.isoformat()
                        )
                        
                        if available_times and len(available_times) > 0:
                            earliest_slot = available_times[0]
                            earliest_date = check_date
                            earliest_location = biz
                            logger.info(f"Found available slot on {check_date} at {biz['business_name']}")
                            break
                    except Exception as e:
                        logger.warning(f"Error checking availability for {practitioner['full_name']} at {biz['business_name']} on {check_date}: {e}")
                        continue
                
                if earliest_slot:
                    break
            
            if earliest_slot:
                # Convert to local time
                slot_utc = datetime.fromisoformat(earliest_slot['appointment_start'].replace('Z', '+00:00'))
                slot_local = slot_utc.astimezone(clinic_tz)
                
                # Format the response message
                date_str = slot_local.strftime('%A, %B %d')
                time_str = format_time_for_voice(slot_local)
                
                # --- NEW: Also find next slot at originally requested location (if different) ---
                next_at_requested = None
                if location and earliest_location['business_id'] != location.get('business_id'):
                    # Search next 14 days at the requested location
                    for days_ahead in range(14):
                        check_date = search_start + timedelta(days=days_ahead)
                        try:
                            available_times = await cliniko.get_available_times(
                                business_id=location['business_id'],
                                practitioner_id=practitioner['practitioner_id'],
                                appointment_type_id=service_match['appointment_type_id'],
                                from_date=check_date.isoformat(),
                                to_date=check_date.isoformat()
                            )
                            if available_times and len(available_times) > 0:
                                slot_utc2 = datetime.fromisoformat(available_times[0]['appointment_start'].replace('Z', '+00:00'))
                                slot_local2 = slot_utc2.astimezone(clinic_tz)
                                next_at_requested = {
                                    'date': slot_local2.strftime('%A, %B %d'),
                                    'time': format_time_for_voice(slot_local2),
                                    'location': location['business_name'],
                                    'business_id': location['business_id']
                                }
                                break
                        except Exception as e:
                            logger.warning(f"Error checking availability for {practitioner['full_name']} at requested location {location['business_name']} on {check_date}: {e}")
                            continue
                
                # --- Compose message ---
                logger.info(f"service_match: {service_match}")
                if next_at_requested:
                    message = (
                        f"{practitioner['full_name']} doesn't have availability on {appointment_date.strftime('%A, %B %d, %Y')}, "
                        f"but they have a slot on {date_str} at {time_str} at our {earliest_location['business_name']}. "
                        f"Their next slot in {next_at_requested['location']} is {next_at_requested['date']} at {next_at_requested['time']}. "
                        f"Would you like to book either of them instead?"
                    )
                else:
                    if location and earliest_location['business_id'] == location.get('business_id'):
                        message = f"{practitioner['full_name']} doesn't have availability on {appointment_date.strftime('%A, %B %d, %Y')}, but they have a slot on {date_str} at {time_str}."
                    else:
                        message = f"{practitioner['full_name']} doesn't have availability on {appointment_date.strftime('%A, %B %d, %Y')}, but they have a slot on {date_str} at {time_str} at our {earliest_location['business_name']}."
                
                return {
                    "success": True,
                    "sessionId": availability_request.sessionId,
                    "message": message,
                    "practitioner": practitioner["full_name"],
                    "service": service_match.get("name", "the requested service"),
                    "next_available": {
                        "date": date_str,
                        "time": time_str,
                        "location": earliest_location['business_name'],
                        "business_id": earliest_location['business_id']
                    },
                    **({"next_at_requested": next_at_requested} if next_at_requested else {})
                }
            else:
                return create_error_response(
                    error_code="no_availability",
                    message=f"I'm sorry, {practitioner['full_name']} doesn't have any available times "
                            f"on {appointment_date.strftime('%A, %B %d, %Y')} or in the next 2 weeks.",
                    session_id=availability_request.sessionId
                )
        
        # Format times for voice response
        clinic_tz = get_clinic_timezone(clinic.timezone)
        available_times_local = []
        
        for time_slot in available_times:
            local_time = convert_utc_to_local(time_slot["appointment_start"], clinic_tz)
            formatted_time = format_time_for_voice(local_time)
            available_times_local.append(formatted_time)
        
        return {
            "success": True,
            "sessionId": availability_request.sessionId,
            "available_times": available_times_local,
            "practitioner": practitioner["full_name"],
            "service": service_match.get("name", "the requested service"),
            "date": appointment_date.strftime("%A, %B %d, %Y"),
            "message": f"{practitioner['full_name']} has available times on "
                      f"{appointment_date.strftime('%A, %B %d, %Y')}: "
                      f"{', '.join(available_times_local)}."
        }
        
    except Exception as e:
        logger.error(f"Error checking availability: {e}")
        logger.error(f"Exception type: {type(e).__name__}")
        logger.error(f"Exception details: {str(e)}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        return create_error_response(
            error_code="internal_error",
            message="I'm sorry, I encountered an error while checking availability. Please try again.",
            session_id=body.get("sessionId", "unknown") if 'body' in locals() else "unknown"
        )

@router.post("/get-available-practitioners")
async def get_available_practitioners(
    request: Request,
    authenticated: bool = Depends(verify_api_key)
) -> Dict[str, Any]:
    """Get practitioners with availability on a specific date"""
    
    body = await request.json()
    business_id = body.get('business_id', '')
    business_name = body.get('businessName', '')
    date_str = body.get('date', 'today')
    dialed_number = body.get('dialedNumber', '')
    session_id = body.get('sessionId', '')
    
    # Get database pool
    pool = await get_db()
    
    # Get clinic
    clinic = await get_clinic_by_dialed_number(dialed_number, pool)
    if not clinic:
        return {
            "success": False,
            "message": "I couldn't find the clinic information.",
            "sessionId": session_id
        }
    
    # Parse date
    clinic_tz = get_clinic_timezone(clinic)
    check_date = parse_date_request(date_str, clinic_tz)
    
    # Initialize Cliniko API
    cliniko = ClinikoAPI(
        clinic.cliniko_api_key,
        clinic.cliniko_shard,
        "VoiceBookingSystem/1.0"
    )
    
    # Get all practitioners at this business
    query = """
        SELECT DISTINCT
            p.practitioner_id,
            CASE 
                WHEN p.title IS NOT NULL AND p.title != '' 
                THEN CONCAT(p.title, ' ', p.first_name, ' ', p.last_name)
                ELSE CONCAT(p.first_name, ' ', p.last_name)
            END as practitioner_name
        FROM practitioners p
        JOIN practitioner_businesses pb ON p.practitioner_id = pb.practitioner_id
        JOIN practitioner_appointment_types pat ON p.practitioner_id = pat.practitioner_id
        WHERE pb.business_id = $1
          AND p.active = true
          AND p.clinic_id = $2
        GROUP BY p.practitioner_id, p.first_name, p.last_name, p.title
    """
    
    async with pool.acquire() as conn:
        practitioners = await conn.fetch(query, business_id, clinic.clinic_id)
    
    # Check availability for each practitioner
    available_practitioners = []
    from_date = check_date.isoformat()
    to_date = check_date.isoformat()  # SAME DATE
    
    for prac in practitioners:
        # Get services for this practitioner
        services_query = """
            SELECT DISTINCT at.name, at.appointment_type_id
            FROM practitioner_appointment_types pat
            JOIN appointment_types at ON pat.appointment_type_id = at.appointment_type_id
            WHERE pat.practitioner_id = $1
            ORDER BY at.name
        """
        async with pool.acquire() as conn:
            services = await conn.fetch(services_query, prac['practitioner_id'])
        
        # Check availability for each service
        for service in services:
            try:
                # Get availability for this practitioner/service combination
                available_times = await cliniko.get_available_times(
                    business_id=business_id,
                    practitioner_id=prac['practitioner_id'],
                    appointment_type_id=service['appointment_type_id'],
                    from_date=from_date,
                    to_date=to_date
                )
                
                if available_times and len(available_times) > 0:
                    # Add to available practitioners if not already added
                    if not any(p['practitioner_id'] == prac['practitioner_id'] for p in available_practitioners):
                        available_practitioners.append({
                            'practitioner_id': prac['practitioner_id'],
                            'practitioner_name': prac['practitioner_name'],
                            'available_services': []
                        })
                    
                    # Add service to practitioner's available services
                    prac_index = next(i for i, p in enumerate(available_practitioners) if p['practitioner_id'] == prac['practitioner_id'])
                    available_practitioners[prac_index]['available_services'].append(service['name'])
                    
                    # Break out of service loop since we found availability for this practitioner
                    break
                    
            except Exception as e:
                logger.warning(f"Error checking availability for {prac['practitioner_name']} - {service['name']}: {e}")
                continue
    
    # Format response
    date_str = check_date.strftime('%A, %B %d')
    
    if not available_practitioners:
        message = f"I don't see any available appointments at {business_name} on {date_str}. Would you like me to check another day?"
        return {
            "success": False,
            "message": message,
            "sessionId": session_id
        }
    else:
        names = [p['practitioner_name'] for p in available_practitioners]
        
        if len(names) == 1:
            message = f"On {date_str} at {business_name}, {names[0]} has availability."
        elif len(names) == 2:
            message = f"On {date_str} at {business_name}, {names[0]} and {names[1]} have availability."
        else:
            last = names[-1]
            others = names[:-1]
            message = f"On {date_str} at {business_name}, {', '.join(others)}, and {last} have availability."
    
    response = GetAvailablePractitionersResponse(
        success=True,
        sessionId=session_id,
        message=message,
        practitioners=[PractitionerData(
            id=p['practitioner_id'],
            name=p['practitioner_name'],
            firstName=p['practitioner_name'].split()[0] if p['practitioner_name'] else ""
        ) for p in available_practitioners],
        date=date_str,
        location=LocationData(id=business_id, name=business_name) if business_id and business_name else None
    )
    return response.dict()

@router.post("/find-next-available")
async def find_next_available(
    request: Request,
    authenticated: bool = Depends(verify_api_key)
) -> Dict[str, Any]:
    """Find next available appointment with flexible parameters"""
    try:
        body = await request.json()
        logger.info("=== FIND NEXT AVAILABLE START ===")
        logger.info(f"Request body: {body}")
    
        # Flexible inputs - handle both field names for compatibility
        service_name = body.get('service') or body.get('appointmentType')  # e.g., "massage"
        practitioner_name = body.get('practitioner')  # e.g., "Brendan"
        business_id = body.get('business_id')  # Optional: specific business
        business_name = body.get('businessName')  # For response formatting
        max_days = body.get('maxDays', 14)  # How far to search (default 2 weeks)
        dialed_number = body.get('dialedNumber', '')
        session_id = body.get('sessionId', '')
        
        logger.info(f"Parsed inputs - service: {service_name},\
            practitioner: {practitioner_name}, dialed_number: {dialed_number}")
    
        # Get database pool and cache
        pool = await get_db()
        cache = await get_cache()
    
        # Get clinic
        clinic = await get_clinic_by_dialed_number(dialed_number, pool)
        if not clinic:
            logger.error(f"Clinic not found for dialed number: {dialed_number}")
            return {
                "success": False,
                "message": "I couldn't find the clinic information.",
                "sessionId": session_id
            }
    
        logger.info(f"Found clinic: {clinic.clinic_name}")
        
        # Initialize Cliniko API
        cliniko = ClinikoAPI(
            clinic.cliniko_api_key,
            clinic.cliniko_shard,
            "VoiceBookingSystem/1.0"
        )
    
        # Set up timezone and search window before using search_start
        clinic_tz = get_clinic_timezone(clinic)
        requested_date = None
        if 'date' in body and body['date']:
            try:
                requested_date = parse_date_request(body['date'], clinic_tz)
            except Exception:
                requested_date = None
        search_start = requested_date if requested_date else datetime.now(clinic_tz).date()
        search_end = search_start + timedelta(days=max_days)
        logger.info(f"Searching from {search_start} to {search_end}")

        # --- SESSION-BASED REJECTED SLOTS TRACKING (Supabase) ---
        import json
        # Define criteria for this search
        current_criteria = {
            'practitioner': body.get('practitioner'),
            'service': body.get('service') or body.get('appointmentType'),
            'location': body.get('locationId') or body.get('business_id') or body.get('locationName') or body.get('businessName')
        }
        # Fetch previous rejected slots and criteria
        async with pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT rejected_slots, last_criteria FROM session_rejected_slots WHERE session_id = $1
            """, session_id)
            if row:
                rejected_slots = set(row['rejected_slots'] or [])
                last_criteria = row['last_criteria']
            else:
                rejected_slots = set()
                last_criteria = None
        # If criteria changed, reset rejected slots
        if last_criteria is not None and json.dumps(last_criteria, sort_keys=True) != json.dumps(current_criteria, sort_keys=True):
            rejected_slots = set()
        # --- END SESSION-BASED REJECTED SLOTS TRACKING ---

        # Build the search criteria
        search_criteria = []
    
        # CASE 1: Find specific practitioner (across all their businesses) - NO SERVICE SPECIFIED
        if practitioner_name and not service_name:
            logger.info(f"Case 1: Finding practitioner {practitioner_name} without service")
            practitioner_result = await match_practitioner(clinic.clinic_id, practitioner_name, pool)
            
            # Handle practitioner clarification if needed
            if practitioner_result.get("needs_clarification"):
                return {
                    "success": True,
                    "needs_clarification": True,
                    "message": practitioner_result["message"],
                    "options": practitioner_result["clarification_options"],
                    "sessionId": session_id
                }
            
            # Handle no practitioner matches
            if not practitioner_result.get("matches"):
                logger.error(f"Practitioner not found: {practitioner_name}")
                return {
                    "success": False,
                    "message": practitioner_result.get("message", "I couldn't find {practitioner_name}."),
                    "sessionId": session_id
                }
            
            # Get the single practitioner (should be only one at this point)
            practitioner = practitioner_result["matches"][0]
            
            # Ensure full_name is available
            if 'full_name' not in practitioner and 'first_name' in practitioner and 'last_name' in practitioner:
                practitioner['full_name'] = f"{practitioner['first_name']} {practitioner['last_name']}"
            
            # Get all services for this practitioner
            services_query = """
                SELECT DISTINCT at.name
                FROM practitioner_appointment_types pat
                JOIN appointment_types at ON pat.appointment_type_id = at.appointment_type_id
                WHERE pat.practitioner_id = $1
                ORDER BY at.name
            """
            async with pool.acquire() as conn:
                services = await conn.fetch(services_query, practitioner['practitioner_id'])
            if not service_name:
                if services:
                    service_names = [s['name'] for s in services]
                    logger.info(f"Services found for {practitioner_name}: {service_names}")
                    return {
                        "success": False,
                        "error": "service_required",
                        "message": f"What type of appointment would you like with {practitioner['full_name']}? They offer: {', '.join(service_names)}",
                        "sessionId": session_id
                    }
                else:
                    logger.error(f"No services found for {practitioner_name}")
                    return {
                        "success": False,
                        "error": "no_services",
                        "message": f"{practitioner['full_name']} does not offer any services.",
                        "sessionId": session_id
                    }
            
            # Get all businesses where this practitioner works
            query = """
                SELECT DISTINCT 
                    pb.business_id,
                    b.business_name,
                    MIN(pat.appointment_type_id) as default_service_id
                FROM practitioner_businesses pb
                JOIN businesses b ON pb.business_id = b.business_id
                JOIN practitioner_appointment_types pat ON pb.practitioner_id = pat.practitioner_id
                WHERE pb.practitioner_id = $1
                GROUP BY pb.business_id, b.business_name
            """
            
            async with pool.acquire() as conn:
                businesses = await conn.fetch(query, practitioner['practitioner_id'])
            
            for biz in businesses:
                search_criteria.append({
                    'practitioner_id': practitioner['practitioner_id'],
                    'practitioner_name': practitioner['full_name'],
                    'business_id': biz['business_id'],
                    'business_name': biz['business_name'],
                    'appointment_type_id': biz['default_service_id']
                })
        
        # CASE 1.5: Find specific practitioner WITH specific service
        elif practitioner_name and service_name:
            logger.info(f"Case 1.5: Finding practitioner {practitioner_name} with service {service_name}")
            practitioner_result = await match_practitioner(clinic.clinic_id, practitioner_name, pool)
            
            # Handle practitioner clarification if needed
            if practitioner_result.get("needs_clarification"):
                return {
                    "success": True,
                    "needs_clarification": True,
                    "message": practitioner_result["message"],
                    "options": practitioner_result["clarification_options"],
                    "sessionId": session_id
                }
            
            # Handle no practitioner matches
            if not practitioner_result.get("matches"):
                logger.error(f"Practitioner not found: {practitioner_name}")
                return {
                    "success": False,
                    "message": practitioner_result.get("message", "I couldn't find {practitioner_name}."),
                    "sessionId": session_id
                }
            
            # Get the single practitioner (should be only one at this point)
            practitioner = practitioner_result["matches"][0]
            
            # Ensure full_name is available
            if 'full_name' not in practitioner and 'first_name' in practitioner and 'last_name' in practitioner:
                practitioner['full_name'] = f"{practitioner['first_name']} {practitioner['last_name']}"
            
            # Get all services for this practitioner
            services_query = """
                SELECT DISTINCT at.name, at.appointment_type_id
                FROM practitioner_appointment_types pat
                JOIN appointment_types at ON pat.appointment_type_id = at.appointment_type_id
                WHERE pat.practitioner_id = $1
                ORDER BY at.name
            """
            async with pool.acquire() as conn:
                services = await conn.fetch(services_query, practitioner['practitioner_id'])
            
            # Find the specific service requested
            matching_service = None
            service_normalized = normalize_for_matching(service_name)
            for service in services:
                if (service_normalized in normalize_for_matching(service['name']) or
                    normalize_for_matching(service['name']) in service_normalized):
                    matching_service = service
                    break
            
            if not matching_service:
                service_names = [s['name'] for s in services]
                logger.error(f"Service {service_name} not found for {practitioner_name}. Available: {service_names}")
                return {
                    "success": False,
                    "error": "service_not_found",
                    "message": f"{practitioner['full_name']} doesn't offer {service_name}. They offer: {', '.join(service_names)}",
                    "sessionId": session_id
                }
            
            # Get all businesses where this practitioner works with this service
            query = """
                SELECT DISTINCT 
                    pb.business_id,
                    b.business_name
                FROM practitioner_businesses pb
                JOIN businesses b ON pb.business_id = b.business_id
                WHERE pb.practitioner_id = $1
            """
            
            async with pool.acquire() as conn:
                businesses = await conn.fetch(query, practitioner['practitioner_id'])
            
            for biz in businesses:
                search_criteria.append({
                    'practitioner_id': practitioner['practitioner_id'],
                    'practitioner_name': practitioner['full_name'],
                    'business_id': biz['business_id'],
                    'business_name': biz['business_name'],
                    'appointment_type_id': matching_service['appointment_type_id'],
                    'service_name': matching_service['name']
                })
        
        # CASE 2: Find specific service (across all practitioners/businesses) - NO PRACTITIONER SPECIFIED
        elif service_name:
            logger.info(f"Case 2: Finding service {service_name}")
            # Get all practitioners who offer this service
            services = await get_practitioner_services(clinic.clinic_id, pool)

            # Log all services fetched
            logger.info(f"[find-next-available] All services fetched:")
            for s in services:
                logger.info(f"  Practitioner: {s.get('practitioner_name')} | Service: {s.get('service_name')} | Business: {s.get('business_name')} | business_id: {s.get('business_id')}")

            # Filter by service name (fuzzy match)
            matching_services = []
            service_normalized = normalize_for_matching(service_name)
            logger.info(f"[find-next-available] Normalized requested service: {service_normalized}")

            for service in services:
                service_service_normalized = normalize_for_matching(service['service_name'])
                logger.info(f"Comparing to: {service['service_name']} (normalized: {service_service_normalized})")
                if (service_normalized in service_service_normalized or
                    service_service_normalized in service_normalized):
                    matching_services.append(service)

            logger.info(f"[find-next-available] Matching services found: {len(matching_services)}")
            logger.info(f"[find-next-available] Matching services list: {matching_services}")

            if not matching_services:
                logger.error(f"No {service_name} services found")
                return {
                    "success": False,
                    "message": f"I couldn't find any {service_name} services available.",
                    "sessionId": session_id
                }

            # --- FIX: Build search_criteria for all matching services ---
            search_criteria = []
            for match in matching_services:
                # If location is specified, only include that location
                if business_id and match['business_id'] != business_id:
                    continue
                search_criteria.append({
                    'practitioner_id': match['practitioner_id'],
                    'practitioner_name': match['practitioner_name'],
                    'business_id': match['business_id'],
                    'business_name': match['business_name'],
                    'appointment_type_id': match['appointment_type_id'],
                    'service_name': match['service_name']
                })
            if not search_criteria:
                logger.error(f"No {service_name} services found at the requested location.")
                return {
                    "success": False,
                    "message": f"I couldn't find any {service_name} services available at the requested location.",
                    "sessionId": session_id
                }
        
        else:
            logger.error("Neither practitioner nor service specified")
            return {
                "success": False,
                "message": "Please specify either a practitioner name or service type.",
                "sessionId": session_id
            }
        
        logger.info(f"Search criteria built: {len(search_criteria)} combinations")
        
        # --- NEW: Collect up to 2 earliest slots, then return ---
        found_slots = []  # Will hold tuples: (slot_datetime, slot_dict, criteria, check_date)
        for days_ahead in range(max_days):
            check_date = search_start + timedelta(days=days_ahead)
            logger.info(f"Checking date: {check_date}")
            for criteria in search_criteria:
                logger.info(f"Checking criteria: {criteria['practitioner_name']} at {criteria['business_name']}")
                cached_slots = await cache.get_availability(
                    criteria['practitioner_id'],
                    criteria['business_id'],
                    check_date
                )
                if cached_slots is not None:
                    slots = cached_slots
                    logger.info(f"[find-next-available] Using cached slots for {criteria['practitioner_name']} at {criteria['business_name']} on {check_date}: {len(slots)} slots")
                else:
                    if not cliniko:
                        cliniko = ClinikoAPI(
                            clinic.cliniko_api_key,
                            clinic.cliniko_shard,
                            clinic.contact_email
                        )
                    slots = await cliniko.get_available_times(
                        business_id=criteria['business_id'],
                        practitioner_id=criteria['practitioner_id'],
                        appointment_type_id=criteria['appointment_type_id'],
                        from_date=check_date.isoformat(),
                        to_date=check_date.isoformat()
                    )
                    logger.info(f"[find-next-available] Cliniko API returned {len(slots)} slots for practitioner_id={criteria['practitioner_id']}, business_id={criteria['business_id']}, appointment_type_id={criteria['appointment_type_id']}, date={check_date}")
                    await cache.set_availability(
                        criteria['practitioner_id'],
                        criteria['business_id'],
                        check_date,
                        clinic.clinic_id,
                        slots
                    )
                async with pool.acquire() as conn2:
                    failed_slots = await conn2.fetch("""
                        SELECT appointment_time::text as time
                        FROM failed_booking_attempts
                        WHERE practitioner_id = $1
                          AND business_id = $2
                          AND appointment_date = $3
                          AND created_at > NOW() - INTERVAL '2 hours'
                    """, criteria['practitioner_id'], criteria['business_id'], check_date)
                    failed_times = {row['time'] for row in failed_slots}
                    available_slots = cached_slots if cached_slots is not None else slots
                    filtered_slots = [
                        slot for slot in available_slots 
                        if slot.get('appointment_start', '').split('T')[1][:5] not in failed_times
                    ]
                for slot in filtered_slots:
                    try:
                        slot_dt = datetime.fromisoformat(slot['appointment_start'].replace('Z', '+00:00'))
                        slot_iso = slot_dt.isoformat()
                    except Exception:
                        continue
                    if slot_iso in rejected_slots:
                        continue  # Skip already rejected
                    found_slots.append((slot_dt, slot, criteria, check_date))
                    if len(found_slots) == 2:
                        break
                if len(found_slots) == 2:
                    break
            if len(found_slots) == 2:
                break
        # --- END NEW ---

        # Sort found slots just in case (should already be in order)
        found_slots.sort(key=lambda tup: tup[0])

        # Update rejected slots in DB if any new slots offered
        if found_slots:
            new_offered = [slot_dt.isoformat() for slot_dt, _, _, _ in found_slots]
            updated_rejected = list(rejected_slots.union(new_offered))
            async with pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO session_rejected_slots (session_id, rejected_slots, last_criteria, updated_at)
                    VALUES ($1, $2, $3, NOW())
                    ON CONFLICT (session_id) DO UPDATE SET rejected_slots = $2, last_criteria = $3, updated_at = NOW()
                """, session_id, updated_rejected, json.dumps(current_criteria))

        if found_slots:
            # Format up to 2 slots
            slot_msgs = []
            for slot_dt, slot, criteria, check_date in found_slots:
                slot_utc = slot_dt
                clinic_tz = get_clinic_timezone(clinic)
                slot_local = slot_utc.astimezone(clinic_tz)
                date_str = slot_local.strftime('%A, %B %d')
                time_str = format_time_for_voice(slot_local)
                slot_msgs.append(f"{date_str} at {time_str} at {criteria['business_name']}")
            # Compose message
            practitioner = found_slots[0][2]['practitioner_name']
            treatment = found_slots[0][2].get('service_name', service_name)
            if len(slot_msgs) == 2:
                message = f"{practitioner}'s next availability for {treatment} is {slot_msgs[0]} and {slot_msgs[1]}."
            else:
                message = f"{practitioner}'s next availability for {treatment} is {slot_msgs[0]}."
            logger.info(f"Returning slots: {slot_msgs}")
            return {
                "success": True,
                "found": True,
                "message": message,
                "slots": slot_msgs,
                "sessionId": session_id
            }
        else:
            # No slots found
            if practitioner_name:
                message = \
                    f"I couldn't find any available appointments with {practitioner_name} in the next {max_days} days."
            elif business_name:
                message = \
                    f"I couldn't find any available {service_name} appointments at {business_name} in the next {max_days} days."
            else:
                message = f"I couldn't find any available {service_name} appointments in the next {max_days} days."
            logger.info(f"No availability found: {message}")
            return {
                "success": True,
                "found": False,
                "message": message,
                "sessionId": session_id
            }
    except Exception as e:
        logger.error(f"Error in find_next_available: {str(e)}", exc_info=True)
        return {
            "success": False,
            "error": "internal_error",
            "message": f"An error occurred while finding availability: {str(e)}",
            "sessionId": body.get('sessionId', '') if 'body' in locals() else ''
        }
