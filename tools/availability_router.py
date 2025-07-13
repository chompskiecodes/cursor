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
from .cache_utils import check_and_trigger_sync, get_availability_with_fallback
from shared_types import CacheManagerProtocol
from models import (
    AvailabilityResponse,
    PractitionerData,
    LocationData,
    TimeSlotData,
    GetAvailablePractitionersResponse,
    NextAvailableResponse,
    ClinicData
)
from tools.shared import get_scheduled_working_days

# Import parallel implementation (used by find-next-available-parallel)
# from .availability_router_parallel import ParallelAvailabilityChecker

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
            cliniko = ClinikoAPI(clinic.cliniko_api_key, clinic.cliniko_shard, "VoiceBookingSystem/1.0")
            cached_slots = await get_availability_with_fallback(
                practitioner['practitioner_id'],
                location['business_id'] if location else None,
                appointment_date,
                clinic.clinic_id,
                db,
                cache,
                cliniko
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
                    "slots": available_times_local,  # NEW: always include both keys
                    "practitioner": practitioner["full_name"],
                    "service": service_match.get("name", "the requested service"),
                    "date": appointment_date.strftime("%A, %B %d, %Y"),
                    "message": f"[From local system] {practitioner['full_name']} has these times available on {appointment_date.strftime('%A, %B %d, %Y')}: {', '.join(available_times_local)}. (Note: These may be slightly out of date.)"
                }
            # If no availability on requested date, search for next available slot
            logger.info(f"No availability found for {practitioner['full_name']} on {appointment_date}, searching for next available slot...")
            cliniko = ClinikoAPI(
                clinic.cliniko_api_key,
                clinic.cliniko_shard,
                "VoiceBookingSystem/1.0"
            )
            # --- STRICT LOCATION FALLBACK ---
            earliest_slot = None
            earliest_date = None
            earliest_location = None
            clinic_tz = get_clinic_timezone(clinic)
            search_start = datetime.now(clinic_tz).date()
            search_end = search_start + timedelta(days=14)  # Search next 2 weeks
            if location and location.get('business_id'):
                # Only search the requested location
                business_ids = [location['business_id']]
            else:
                # No location specified, search all locations (legacy behavior)
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
                business_ids = [biz['business_id'] for biz in businesses]

            # Build date range and filter to scheduled working days
            date_range = [search_start + timedelta(days=i) for i in range(14)]
            async with db.acquire() as conn:
                scheduled_dates = []
                for biz_id in business_ids:
                    scheduled = await get_scheduled_working_days(conn, practitioner['practitioner_id'], biz_id, date_range)
                    scheduled_dates.extend([(d, biz_id) for d in scheduled])

            # Now search only on scheduled dates
            earliest_slot = None
            earliest_date = None
            earliest_location = None
            for d, biz_id in scheduled_dates:
                try:
                    available_times = await cliniko.get_available_times(
                        business_id=biz_id,
                        practitioner_id=practitioner['practitioner_id'],
                        appointment_type_id=service_match['appointment_type_id'],
                        from_date=d.isoformat(),
                        to_date=d.isoformat()
                    )
                    if available_times and len(available_times) > 0:
                        earliest_slot = available_times[0]
                        earliest_date = d
                        earliest_location = biz_id
                        logger.info(f"Found available slot on {d} at business_id {biz_id}")
                        break
                except Exception as e:
                    logger.warning(f"Error checking availability for {practitioner['full_name']} at business_id {biz_id} on {d}: {e}")
                    continue
            if earliest_slot:
                slot_utc = datetime.fromisoformat(earliest_slot['appointment_start'].replace('Z', '+00:00'))
                slot_local = slot_utc.astimezone(clinic_tz)
                return {
                    "success": True,
                    "sessionId": availability_request.sessionId,
                    "available_times": [format_time_for_voice(slot_local)],
                    "slots": [format_time_for_voice(slot_local)],
                    "practitioner": practitioner["full_name"],
                    "service": service_match.get("name", "the requested service"),
                    "date": earliest_date.strftime("%A, %B %d, %Y"),
                    "message": f"{practitioner['full_name']} has an available time on {earliest_date.strftime('%A, %B %d, %Y')} at {format_time_for_voice(slot_local)}."
                }
            else:
                return create_error_response(
                    error_code="no_availability",
                    message=f"I'm sorry, {practitioner['full_name']} doesn't have any available times "
                            f"on {appointment_date.strftime('%A, %B %d, %Y')} or in the next 2 weeks.",
                    session_id=availability_request.sessionId,
                    extra={"slots": [], "available_times": []}  # NEW: always include both keys
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
            "slots": available_times_local,  # NEW: always include both keys
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
            session_id=body.get("sessionId", "unknown") if 'body' in locals() else "unknown",
            extra={"slots": [], "available_times": []}  # NEW: always include both keys
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
        # Only check if practitioner is scheduled to work on check_date
        scheduled = await get_scheduled_working_days(conn, prac['practitioner_id'], business_id, [check_date])
        if not scheduled:
            continue  # Not working that day
        # Get services for this practitioner
        services_query = """
            SELECT DISTINCT at.name, at.appointment_type_id
            FROM practitioner_appointment_types pat
            JOIN appointment_types at ON pat.appointment_type_id = at.appointment_type_id
            WHERE pat.practitioner_id = $1
            ORDER BY at.name, at.appointment_type_id
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
            "slots": [],  # NEW: always include both keys
            "available_times": [],  # NEW: always include both keys
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
    result = response.dict()
    result['slots'] = []  # NEW: always include both keys
    result['available_times'] = []  # NEW: always include both keys
    return result

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
                cliniko = ClinikoAPI(clinic.cliniko_api_key, clinic.cliniko_shard, "VoiceBookingSystem/1.0")
                cached_slots = await get_availability_with_fallback(
                    criteria['practitioner_id'],
                    criteria['business_id'],
                    check_date,
                    clinic.clinic_id,
                    pool,
                    cache,
                    cliniko
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
                # --- ENFORCE: Only include slots for the requested business_id if provided ---
                if business_id:
                    filtered_slots = [slot for slot in filtered_slots if criteria['business_id'] == business_id]
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
                "available_times": slot_msgs,  # NEW: always include both keys
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
                "slots": [],  # NEW: always include both keys
                "available_times": [],  # NEW: always include both keys
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

async def find_next_available_parallel_impl(
    search_criteria: List[Dict[str, Any]],
    max_days: int,
    session_id: str,
    practitioner_name: Optional[str],
    service_name: Optional[str],
    location_name: Optional[str],
    business_id: Optional[str],
    clinic: ClinicData,
    pool: asyncpg.Pool,
    cache: CacheManagerProtocol
) -> Dict[str, Any]:
    """Parallel implementation for finding next available appointment"""
    
    import asyncio
    import time
    from datetime import date, timedelta
    
    start_time = time.time()
    logger.info("=== FIND NEXT AVAILABLE PARALLEL IMPLEMENTATION ===")
    
    # Initialize Cliniko API
    cliniko = ClinikoAPI(
        clinic.cliniko_api_key,
        clinic.cliniko_shard,
        "VoiceBookingSystem/1.0"
    )
    
    # Generate dates to check (4 days at a time for efficiency)
    dates_to_check = []
    current_date = date.today()
    for i in range(0, max_days, 4):  # Check 4 days at a time
        batch_start = current_date + timedelta(days=i)
        batch_end = min(batch_start + timedelta(days=3), current_date + timedelta(days=max_days-1))
        dates_to_check.append((batch_start, batch_end))
    
    logger.info(f"Will check {len(dates_to_check)} date batches: {dates_to_check}")
    
    # Create tasks for parallel availability checking
    async def check_availability_batch(date_batch: tuple, criteria: dict) -> tuple:
        """Check availability for a specific date range and criteria"""
        start_date, end_date = date_batch
        from_date = start_date.isoformat()
        to_date = end_date.isoformat()
        
        logger.info(f"Checking {criteria['practitioner_name']} ({criteria['service_name']}) from {from_date} to {to_date}")
        try:
            available_times = await cliniko.get_available_times(
                business_id=criteria['business_id'],
                practitioner_id=criteria['practitioner_id'],
                appointment_type_id=criteria['appointment_type_id'],
                from_date=from_date,
                to_date=to_date
            )
            logger.info(f"Raw Cliniko response for {criteria['practitioner_name']} ({criteria['service_name']}) {from_date}-{to_date}: {available_times}")
            # Filter times within the date range
            filtered_times = []
            for time_slot in available_times or []:
                # Cliniko API returns 'appointment_start' not 'time'
                time_key = 'appointment_start' if 'appointment_start' in time_slot else 'time'
                slot_date = datetime.fromisoformat(time_slot[time_key].replace('Z', '+00:00')).date()
                if start_date <= slot_date <= end_date:
                    filtered_times.append(time_slot)
            logger.info(f"Filtered times for {criteria['practitioner_name']} ({criteria['service_name']}) {from_date}-{to_date}: {filtered_times}")
            has_availability = len(filtered_times) > 0
            logger.debug(f"Batch {start_date}-{end_date} for {criteria['practitioner_name']} {criteria['service_name']}: {'AVAILABLE' if has_availability else 'NO SLOTS'}")
            return (start_date, end_date, criteria, filtered_times, has_availability)
        except Exception as e:
            logger.warning(f"Error checking availability for batch {start_date}-{end_date} {criteria['practitioner_name']} {criteria['service_name']}: {e}")
            return (start_date, end_date, criteria, [], False)
    
    # Create all tasks (date batches × search criteria)
    tasks = []
    for date_batch in dates_to_check:
        for criteria in search_criteria:
            task = check_availability_batch(date_batch, criteria)
            tasks.append(task)
    
    logger.info(f"Created {len(tasks)} parallel tasks ({len(dates_to_check)} date batches × {len(search_criteria)} criteria)")
    
    # Execute tasks with concurrency limit and timeout
    # Cliniko API documented limit: 60 req/min (1 req/sec). Set concurrency to 25 for optimal performance.
    max_concurrent = 25
    timeout_seconds = 90  # Longer timeout for larger batches
    
    try:
        # Use asyncio.gather with semaphore for concurrency control
        semaphore = asyncio.Semaphore(max_concurrent)
        
        async def limited_task(task):
            async with semaphore:
                return await task
        
        limited_tasks = [limited_task(task) for task in tasks]
        
        # Execute with timeout
        results = await asyncio.wait_for(
            asyncio.gather(*limited_tasks, return_exceptions=True),
            timeout=timeout_seconds
        )
        
        logger.info(f"Completed {len(results)} availability batch checks")
        
    except asyncio.TimeoutError:
        logger.error(f"Timeout after {timeout_seconds} seconds")
        return {
            "success": False,
            "message": "The availability check took too long. Please try again.",
            "sessionId": session_id
        }
    except Exception as e:
        logger.error(f"Error during parallel availability check: {e}")
        return {
            "success": False,
            "message": f"An error occurred while checking availability: {str(e)}",
            "sessionId": session_id
        }
    
    # Process results to find the earliest available slot
    earliest_slot = None
    earliest_date = None
    available_practitioners = {}
    
    for result in results:
        if isinstance(result, Exception):
            logger.warning(f"Task failed with exception: {result}")
            continue
            
        start_date, end_date, criteria, times, has_availability = result
        
        if has_availability and times:
            # Find the earliest slot in this batch
            for time_slot in times:
                # Cliniko API returns 'appointment_start' not 'time'
                time_key = 'appointment_start' if 'appointment_start' in time_slot else 'time'
                slot_datetime = datetime.fromisoformat(time_slot[time_key].replace('Z', '+00:00'))
                slot_date = slot_datetime.date()
                
                if earliest_slot is None or slot_datetime < earliest_slot['datetime']:
                    earliest_slot = {
                        'datetime': slot_datetime,
                        'date': slot_date,
                        'time': time_slot[time_key],
                        'practitioner_name': criteria['practitioner_name'],
                        'service_name': criteria['service_name'],
                        'business_name': criteria['business_name'],
                        'practitioner_id': criteria['practitioner_id'],
                        'appointment_type_id': criteria['appointment_type_id'],
                        'business_id': criteria['business_id']
                    }
                    earliest_date = slot_date
            
            # Track available practitioners
            prac_key = criteria['practitioner_id']
            if prac_key not in available_practitioners:
                available_practitioners[prac_key] = {
                    'practitioner_name': criteria['practitioner_name'],
                    'earliest_date': slot_date,
                    'services': []
                }
            
            if criteria['service_name'] not in available_practitioners[prac_key]['services']:
                available_practitioners[prac_key]['services'].append(criteria['service_name'])
    
    # Format response
    if earliest_slot:
        # Found availability
        date_str = earliest_slot['date'].strftime('%A, %B %d')
        time_str = earliest_slot['datetime'].strftime('%I:%M %p')
        
        if practitioner_name and service_name:
            message = f"I found availability for {practitioner_name} for {service_name} on {date_str} at {time_str}."
        elif practitioner_name:
            message = f"I found availability for {practitioner_name} on {date_str} at {time_str}."
        elif service_name:
            message = f"I found {service_name} availability with {earliest_slot['practitioner_name']} on {date_str} at {time_str}."
        else:
            message = f"I found availability with {earliest_slot['practitioner_name']} on {date_str} at {time_str}."
        
        response = {
            "success": True,
            "message": message,
            "sessionId": session_id,
            "available_times": [earliest_slot['time']],
            "practitioner": {
                "id": earliest_slot['practitioner_id'],
                "name": earliest_slot['practitioner_name']
            },
            "service": earliest_slot['service_name'],
            "date": date_str,
            "time": time_str,
            "location": {
                "id": earliest_slot['business_id'],
                "name": earliest_slot['business_name']
            }
        }
    else:
        # No availability found
        if practitioner_name and service_name:
            message = f"I couldn't find any availability for {practitioner_name} for {service_name} in the next {max_days} days."
        elif practitioner_name:
            message = f"I couldn't find any availability for {practitioner_name} in the next {max_days} days."
        elif service_name:
            message = f"I couldn't find any {service_name} availability in the next {max_days} days."
        else:
            message = f"I couldn't find any availability in the next {max_days} days."
        
        response = {
            "success": False,
            "message": message,
            "sessionId": session_id,
            "available_times": []
        }
    
    elapsed_time = time.time() - start_time
    logger.info(f"=== FIND NEXT AVAILABLE PARALLEL COMPLETE in {elapsed_time:.2f}s ===")
    
    return response

@router.post("/find-next-available-parallel")
async def find_next_available_parallel(
    request: Request,
    authenticated: bool = Depends(verify_api_key)
) -> Dict[str, Any]:
    """Find next available appointment using parallel implementation for better performance"""
    
    logger.info("=== FIND NEXT AVAILABLE PARALLEL START ===")
    
    try:
        body = await request.json()
        logger.info(f"Request body: {body}")
        
        # Extract parameters (same as sequential version)
        service_name = body.get('service')
        practitioner_name = body.get('practitioner')
        business_id = body.get('business_id')  # Use business_id from request
        location_id = body.get('locationId') or business_id  # Support both for compatibility
        location_name = body.get('locationName')
        max_days = body.get('maxDays', 14)
        dialed_number = body.get('dialedNumber', '')
        session_id = body.get('sessionId', '')
        
        logger.info(f"Parsed inputs - service: {service_name}, practitioner: {practitioner_name}, dialed_number: {dialed_number}")
        
        # Get database pool and cache
        pool = await get_db()
        cache = await get_cache()
        
        # Get clinic
        clinic = await get_clinic_by_dialed_number(dialed_number, pool)
        if not clinic:
            return {
                "success": False,
                "message": "I couldn't find the clinic information.",
                "sessionId": session_id
            }
        
        logger.info(f"Found clinic: {clinic.clinic_name}")
        logger.info(f"Searching from {datetime.now().date()} to {datetime.now().date() + timedelta(days=max_days)}")
        
        # Build search criteria (same logic as sequential version)
        search_criteria = []
        
        # CASE 1: Find specific practitioner (across all their locations)
        if practitioner_name and not service_name:
            logger.info(f"Case 1: Finding practitioner {practitioner_name} (no service specified)")
            practitioner_match = await match_practitioner(clinic.clinic_id, practitioner_name, pool)
            if not practitioner_match or not practitioner_match.get('matches'):
                return {
                    "success": False,
                    "message": f"I couldn't find {practitioner_name}.",
                    "sessionId": session_id
                }
            
            # Get the first/best match
            practitioner = practitioner_match['matches'][0]
            
            # Get all locations where this practitioner works
            query = """
                SELECT DISTINCT pat.practitioner_id, pat.appointment_type_id, b.business_id, b.business_name
                FROM practitioner_appointment_types pat
                JOIN practitioner_businesses pb ON pat.practitioner_id = pb.practitioner_id
                JOIN businesses b ON pb.business_id = b.business_id
                WHERE pat.practitioner_id = $1 AND b.clinic_id = $2
            """
            async with pool.acquire() as conn:
                rows = await conn.fetch(query, practitioner['practitioner_id'], clinic.clinic_id)
            logger.info(f"Raw DB rows for practitioner/locations: {[dict(row) for row in rows]}")
            
            # Filter by location if specified
            if location_id:
                rows = [row for row in rows if row['business_id'] == location_id]
                if not rows:
                    return {
                        "success": False,
                        "message": f"I couldn't find {practitioner_name} at the requested location.",
                        "sessionId": session_id
                    }
            
            for row in rows:
                row_dict = dict(row)
                search_criteria.append({
                    'practitioner_id': row_dict.get('practitioner_id'),
                    'practitioner_name': practitioner['full_name'],
                    'business_id': row_dict.get('business_id'),
                    'business_name': row_dict.get('business_name'),
                    'appointment_type_id': row_dict.get('appointment_type_id'),
                    'service_name': 'appointment'
                })
        
        # CASE 2: Find specific practitioner with specific service
        elif practitioner_name and service_name:
            logger.info(f"Case 1.5: Finding practitioner {practitioner_name} with service {service_name}")
            practitioner_match = await match_practitioner(clinic.clinic_id, practitioner_name, pool)
            if not practitioner_match or not practitioner_match.get('matches'):
                return {
                    "success": False,
                    "message": f"I couldn't find {practitioner_name}.",
                    "sessionId": session_id
                }
            
            # Get the first/best match
            practitioner = practitioner_match['matches'][0]
            
            # Find matching services
            services_query = """
                SELECT DISTINCT pat.practitioner_id, pat.appointment_type_id, b.business_id, b.business_name, at.name as service_name
                FROM practitioner_appointment_types pat
                JOIN practitioner_businesses pb ON pat.practitioner_id = pb.practitioner_id
                JOIN businesses b ON pb.business_id = b.business_id
                JOIN appointment_types at ON pat.appointment_type_id = at.appointment_type_id
                WHERE pat.practitioner_id = $1 
                  AND b.clinic_id = $2
                  AND LOWER(at.name) LIKE LOWER($3)
            """
            async with pool.acquire() as conn:
                rows = await conn.fetch(
                    services_query, 
                    practitioner['practitioner_id'], 
                    clinic.clinic_id,
                    f'%{service_name}%'
                )
            logger.info(f"Raw DB rows for practitioner/services: {[dict(row) for row in rows]}")
            if location_id:
                # Filter by location if specified
                rows = [row for row in rows if row['business_id'] == location_id]
            for row in rows:
                row_dict = dict(row)
                search_criteria.append({
                    'practitioner_id': row_dict.get('practitioner_id'),
                    'practitioner_name': practitioner['full_name'],
                    'business_id': row_dict.get('business_id'),
                    'business_name': row_dict.get('business_name'),
                    'appointment_type_id': row_dict.get('appointment_type_id'),
                    'service_name': row_dict.get('service_name')
                })
        
        # CASE 3: Find any practitioner offering a service
        elif service_name:
            logger.info(f"Case 2: Finding any practitioner with service {service_name}")
            
            query = """
                SELECT DISTINCT pat.practitioner_id, pat.appointment_type_id, 
                       CONCAT(p.first_name, ' ', p.last_name) as practitioner_name, 
                       b.business_id, b.business_name, at.name as service_name
                FROM practitioner_appointment_types pat
                JOIN practitioners p ON pat.practitioner_id = p.practitioner_id
                JOIN practitioner_businesses pb ON pat.practitioner_id = pb.practitioner_id
                JOIN businesses b ON pb.business_id = b.business_id
                JOIN appointment_types at ON pat.appointment_type_id = at.appointment_type_id
                WHERE b.clinic_id = $1 AND LOWER(at.name) LIKE LOWER($2)
            """
            
            search_term = f'%{service_name}%'
            async with pool.acquire() as conn:
                matching_services = await conn.fetch(query, clinic.clinic_id, search_term)
            logger.info(f"Raw DB rows for any practitioner/services: {[dict(row) for row in matching_services]}")
            if location_id:
                matching_services = [row for row in matching_services if row['business_id'] == location_id]
            if not matching_services:
                if location_name:
                    return {
                        "success": False,
                        "message": f"I couldn't find any practitioners offering {service_name} at {location_name}.",
                        "sessionId": session_id
                    }
                else:
                    return {
                        "success": False,
                        "message": f"I couldn't find any {service_name} services available.",
                        "sessionId": session_id
                    }
            # Group by practitioner and location
            seen = set()
            for row in matching_services:
                row_dict = dict(row)
                key = (row_dict.get('practitioner_id'), row_dict.get('business_id'))
                if key not in seen:
                    seen.add(key)
                    search_criteria.append({
                        'practitioner_id': row_dict.get('practitioner_id'),
                        'practitioner_name': row_dict.get('practitioner_name'),
                        'business_id': row_dict.get('business_id'),
                        'business_name': row_dict.get('business_name'),
                        'appointment_type_id': row_dict.get('appointment_type_id'),
                        'service_name': row_dict.get('service_name')
                    })
        
        else:
            return {
                "success": False,
                "message": "Please specify either a practitioner name or service type.",
                "sessionId": session_id
            }
        
        logger.info(f"Search criteria built: {len(search_criteria)} combinations")
        
        # Debug: Log the search criteria structure
        for i, criteria in enumerate(search_criteria):
            logger.info(f"Criteria {i}: {criteria}")
            if 'practitioner_id' not in criteria:
                logger.error(f"Missing practitioner_id in criteria {i}: {criteria}")
        
        # Use parallel implementation to check multiple days at once
        return await find_next_available_parallel_impl(
            search_criteria=search_criteria,
            max_days=max_days,
            session_id=session_id,
            practitioner_name=practitioner_name,
            service_name=service_name,
            location_name=location_name,
            business_id=location_id,
            clinic=clinic,
            pool=pool,
            cache=cache
        )
        
    except Exception as e:
        logger.error(f"Error in find_next_available_parallel: {str(e)}", exc_info=True)
        return {
            "success": False,
            "error": "internal_error",
            "message": f"An error occurred while finding availability: {str(e)}",
            "sessionId": body.get('sessionId', '') if 'body' in locals() else ''
        }

@router.post("/get-available-practitioners-parallel")
async def get_available_practitioners_parallel(
    request: Request,
    authenticated: bool = Depends(verify_api_key)
) -> Dict[str, Any]:
    """Get practitioners with availability on a specific date - PARALLEL VERSION"""
    
    import asyncio
    from concurrent.futures import ThreadPoolExecutor
    import time
    
    start_time = time.time()
    logger.info("=== GET AVAILABLE PRACTITIONERS PARALLEL START ===")
    
    body = await request.json()
    logger.info(f"Request body: {body}")
    business_id = body.get('business_id', '')
    business_name = body.get('businessName', '')
    date_str = body.get('date', 'today')
    dialed_number = body.get('dialedNumber', '')
    session_id = body.get('sessionId', '')
    
    logger.info(f"Request: business_id={business_id}, date={date_str}, dialed_number={dialed_number}")
    
    # Get database pool
    pool = await get_db()
    
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
    
    # Parse date
    clinic_tz = get_clinic_timezone(clinic)
    check_date = parse_date_request(date_str, clinic_tz)
    from_date = check_date.isoformat()
    to_date = check_date.isoformat()
    
    logger.info(f"Checking availability for date: {from_date}")
    
    # Initialize Cliniko API
    cliniko = ClinikoAPI(
        clinic.cliniko_api_key,
        clinic.cliniko_shard,
        "VoiceBookingSystem/1.0"
    )
    
    # Get all practitioners at this business with their services
    query = """
        SELECT DISTINCT
            p.practitioner_id,
            p.first_name,
            p.last_name,
            CASE 
                WHEN p.title IS NOT NULL AND p.title != '' 
                THEN CONCAT(p.title, ' ', p.first_name, ' ', p.last_name)
                ELSE CONCAT(p.first_name, ' ', p.last_name)
            END as practitioner_name,
            at.name as service_name,
            at.appointment_type_id
        FROM practitioners p
        JOIN practitioner_businesses pb ON p.practitioner_id = pb.practitioner_id
        JOIN practitioner_appointment_types pat ON p.practitioner_id = pat.practitioner_id
        JOIN appointment_types at ON pat.appointment_type_id = at.appointment_type_id
        WHERE pb.business_id = $1
          AND p.active = true
          AND p.clinic_id = $2
          AND at.active = true
        ORDER BY p.last_name, p.first_name, at.name, at.appointment_type_id
    """
    
    async with pool.acquire() as conn:
        rows = await conn.fetch(query, business_id, clinic.clinic_id)
    
    logger.info(f"Found {len(rows)} practitioner-service combinations to check")
    
    # Group by practitioner
    practitioners_data = {}
    for row in rows:
        prac_id = row['practitioner_id']
        if prac_id not in practitioners_data:
            practitioners_data[prac_id] = {
                'practitioner_id': prac_id,
                'practitioner_name': row['practitioner_name'],
                'services': []
            }
        practitioners_data[prac_id]['services'].append({
            'name': row['service_name'],
            'appointment_type_id': row['appointment_type_id']
        })
    
    logger.info(f"Grouped into {len(practitioners_data)} practitioners")
    
    # Create tasks for parallel availability checking
    async def check_practitioner_service_availability(prac_id: str, service: dict) -> tuple:
        """Check availability for a single practitioner-service combination"""
        try:
            available_times = await cliniko.get_available_times(
                business_id=business_id,
                practitioner_id=prac_id,
                appointment_type_id=service['appointment_type_id'],
                from_date=from_date,
                to_date=to_date
            )
            
            has_availability = available_times and len(available_times) > 0
            logger.debug(f"Practitioner {prac_id} service {service['name']}: {'AVAILABLE' if has_availability else 'NO SLOTS'}")
            
            return (prac_id, service['name'], has_availability)
            
        except Exception as e:
            logger.warning(f"Error checking availability for practitioner {prac_id} service {service['name']}: {e}")
            return (prac_id, service['name'], False)
    
    # Create all tasks
    tasks = []
    for prac_id, prac_data in practitioners_data.items():
        for service in prac_data['services']:
            task = check_practitioner_service_availability(prac_id, service)
            tasks.append(task)
    
    logger.info(f"Created {len(tasks)} parallel tasks")
    
    # Execute tasks with concurrency limit and timeout
    # Cliniko API documented limit: 60 req/min (1 req/sec). Set concurrency to 25 for optimal performance.
    max_concurrent = 25
    timeout_seconds = 90  # Longer timeout for larger batches
    
    try:
        # Use asyncio.gather with semaphore for concurrency control
        semaphore = asyncio.Semaphore(max_concurrent)
        
        async def limited_task(task):
            async with semaphore:
                return await task
        
        limited_tasks = [limited_task(task) for task in tasks]
        
        # Execute with timeout
        results = await asyncio.wait_for(
            asyncio.gather(*limited_tasks, return_exceptions=True),
            timeout=timeout_seconds
        )
        
        logger.info(f"Completed {len(results)} availability checks")
        
    except asyncio.TimeoutError:
        logger.error(f"Timeout after {timeout_seconds} seconds")
        return {
            "success": False,
            "message": "The availability check took too long. Please try again.",
            "slots": [],
            "available_times": [],
            "sessionId": session_id
        }
    except Exception as e:
        logger.error(f"Error during parallel availability check: {e}")
        logger.error(f"Exception type: {type(e).__name__}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        return {
            "success": False,
            "message": f"An error occurred while checking availability: {str(e)}",
            "slots": [],
            "available_times": [],
            "sessionId": session_id
        }
    
    # Process results
    available_practitioners = {}
    
    for result in results:
        if isinstance(result, Exception):
            logger.warning(f"Task failed with exception: {result}")
            continue
            
        prac_id, service_name, has_availability = result
        
        if has_availability:
            if prac_id not in available_practitioners:
                available_practitioners[prac_id] = {
                    'practitioner_id': prac_id,
                    'practitioner_name': practitioners_data[prac_id]['practitioner_name'],
                    'available_services': []
                }
            available_practitioners[prac_id]['available_services'].append(service_name)
    
    # Convert to list
    available_practitioners_list = list(available_practitioners.values())
    
    # Format response
    date_str = check_date.strftime('%A, %B %d')
    
    if not available_practitioners_list:
        message = f"I don't see any available appointments at {business_name} on {date_str}. Would you like me to check another day?"
        response = {
            "success": False,
            "message": message,
            "slots": [],
            "available_times": [],
            "sessionId": session_id
        }
    else:
        names = [p['practitioner_name'] for p in available_practitioners_list]
        
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
            ) for p in available_practitioners_list],
            date=date_str,
            location=LocationData(id=business_id, name=business_name) if business_id and business_name else None
        ).dict()
        response['slots'] = []
        response['available_times'] = []
    
    elapsed_time = time.time() - start_time
    logger.info(f"=== GET AVAILABLE PRACTITIONERS PARALLEL COMPLETE in {elapsed_time:.2f}s ===")
    
    return response
