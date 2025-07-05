# tools/availability_tools.py
"""Availability-related endpoints for the Voice Booking System"""

from fastapi import APIRouter, Request, Depends, BackgroundTasks
from typing import Dict, Any, List, Optional, Union
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import logging
import json
import asyncio
from shared_types import CacheManagerProtocol
import asyncpg

# Local imports
from .dependencies import verify_api_key, get_db, get_cache, get_settings
from models import AvailabilityRequest
from database import (
    get_clinic_by_dialed_number, match_practitioner, match_service,
    get_practitioner_services,
    normalize_for_matching
)
from cliniko import ClinikoAPI
from utils import parse_date_request, mask_phone
from location_resolver import LocationResolver
from models import LocationResolverRequest
from payload_logger import payload_logger
from tools.timezone_utils import (
    get_clinic_timezone,
    convert_utc_to_local,
    format_time_for_voice
)
from .cache_utils import check_and_trigger_sync, get_cached_practitioner_services
from models import (
    AvailabilityResponse,
    PractitionerData,
    LocationData,
    TimeSlotData,
    create_error_response,
    GetAvailablePractitionersResponse,
    NextAvailableResponse
)

logger = logging.getLogger(__name__)

# Create router
router = APIRouter(tags=["availability"])

@router.post("/availability-checker")
async def check_availability(
    request: AvailabilityRequest,
    background_tasks: BackgroundTasks,
    authenticated: bool = Depends(verify_api_key)
) -> Dict[str, Any]:
    """Check practitioner availability with location disambiguation"""
    payload_logger.log_payload("/availability-checker", request.dict())
    clinic = None
    
    try:
        logger.info(f"=== AVAILABILITY CHECK START ===")
        logger.info(f"Session: {request.sessionId}")
        logger.info(f"Practitioner: '{request.practitioner}'")
        logger.info(f"Date: {request.date}")
        
        # Get database pool and cache
        pool = await get_db()
        cache = await get_cache()
        
        # Get clinic information
        clinic = await get_clinic_by_dialed_number(request.dialedNumber, pool)
        if not clinic:
            return {
                "success": False,
                "error": "clinic_not_found",
                "message": "I couldn't find the clinic information.",
                "sessionId": request.sessionId
            }
        # Trigger background sync if needed
        background_tasks.add_task(
            check_and_trigger_sync,
            clinic.clinic_id,
            pool,
            cache,
            clinic.cliniko_api_key,
            clinic.cliniko_shard
        )
        
        logger.info(f"✓ Found clinic: {clinic.clinic_name}")
        
        # Initialize Cliniko API
        cliniko = ClinikoAPI(
            clinic.cliniko_api_key,
            clinic.cliniko_shard,
            clinic.contact_email
        )
        
        # Match practitioner (with caching)
        logger.info(f"Matching practitioner: '{request.practitioner}'")
        practitioner_result = await match_practitioner(clinic.clinic_id, request.practitioner, pool)
        
        # Handle practitioner clarification if needed
        if practitioner_result.get("needs_clarification"):
            return {
                "success": True,
                "action_completed": False,
                "needs_clarification": True,
                "message": practitioner_result["message"],
                "options": practitioner_result["clarification_options"],
                "sessionId": request.sessionId
            }
        
        # Handle no practitioner matches
        if not practitioner_result.get("matches"):
            return {
                "success": False,
                "error": "practitioner_not_found",
                "message": practitioner_result.get("message", f"I couldn't find a practitioner named \"{request.practitioner}\"."),
                "sessionId": request.sessionId
            }
        
        # Get the single practitioner (should be only one at this point)
        practitioner = practitioner_result["matches"][0]
        logger.info(f"✓ Matched practitioner: {practitioner['full_name']}")
        
        # Get services for practitioner (cached)
        services = await get_cached_practitioner_services(clinic.clinic_id, pool, cache)
        practitioner_services = [s for s in services if s['practitioner_id'] == practitioner['practitioner_id']]
        
        if not practitioner_services:
            return {
                "success": False,
                "error": "no_services",
                "message": f"{practitioner['full_name']} doesn't have any appointment types configured.",
                "sessionId": request.sessionId
            }
        
        # Default to first service
        service = practitioner_services[0]
        
        # If specific appointment type requested, try to match it
        if request.appointmentType:
            matched_service = await match_service(clinic.clinic_id, practitioner['practitioner_id'], request.appointmentType, pool)
            if matched_service:
                service = matched_service
                logger.info(f"✓ Matched requested service: {service['service_name']}")
            else:
                # Service not found - list available services
                available_services = [s['service_name'] for s in practitioner_services]
                return {
                    "success": False,
                    "error": "service_not_found",
                    "message": f"I couldn't find \"{request.appointmentType}\" services with {practitioner['full_name']}. They offer: {', '.join(available_services)}",
                    "sessionId": request.sessionId
                }
        else:
            logger.info(f"Using default service: {service['service_name']}")
        
        logger.info(f"Using service: {service['service_name']}")
        
        # Location Resolution
        business = None
        
        # If business_id provided, use it directly (already resolved)
        if request.business_id:
            logger.info(f"Using pre-resolved business_id: {request.business_id}")
            
            # Find business by ID
            for biz in clinic.businesses:
                if biz['business_id'] == request.business_id:
                    business = biz
                    break
            
            if not business:
                # Try to fetch from database
                query = "SELECT business_id, business_name, is_primary FROM businesses WHERE business_id = $1 AND clinic_id = $2"
                async with pool.acquire() as conn:
                    row = await conn.fetchrow(query, request.business_id, clinic.clinic_id)
                    if row:
                        business = dict(row)
                        
            if not business:
                return {
                    "success": False,
                    "error": "invalid_business_id",
                    "message": "The business ID provided is not valid for this clinic.",
                    "sessionId": request.sessionId
                }
        
        # If location text provided but not resolved, try to resolve it
        elif request.location:
            logger.info(f"Location text provided: '{request.location}' - attempting resolution")
            location_resolver = LocationResolver(pool, cache)
            location_request = LocationResolverRequest(
                locationQuery=request.location,
                sessionId=request.sessionId,
                dialedNumber=request.dialedNumber,
                callerPhone=getattr(request, 'callerPhone', None)
            )
            
            location_response = await location_resolver.resolve_location(location_request, clinic.clinic_id)
            
            # If not resolved with high confidence, return disambiguation response
            if location_response.needs_clarification:
                return {
                    "success": True,
                    "action_completed": False,
                    "needs_clarification": True,
                    "message": location_response.message,
                    "options": location_response.options,
                    "sessionId": request.sessionId
                }
            
            # Use the resolved location
            if location_response.business_id:
                business = {
                    'business_id': location_response.business_id,
                    'business_name': location_response.business_name
                }
        
        # Fall back to default if no location specified
        if not business:
            # AVAILABILITY_CHECKER: Only handles specific date queries
            # If no date provided, direct user to use find_next_available instead
            if not request.date:
                return {
                    "success": False,
                    "error": "date_required",
                    "message": f"Please specify a date to check availability for {practitioner['full_name']}. For general availability, use the find_next_available tool instead.",
                    "sessionId": request.sessionId
                }
        
            # Get businesses where this practitioner actually works
            async with pool.acquire() as conn:
                query = """
                    SELECT DISTINCT b.business_id, b.business_name
                    FROM businesses b
                    JOIN practitioner_businesses pb ON b.business_id = pb.business_id
                    WHERE pb.practitioner_id = $1 AND b.clinic_id = $2
                    ORDER BY b.business_name
                """
                practitioner_businesses = await conn.fetch(query, practitioner['practitioner_id'], clinic.clinic_id)
            
            if not practitioner_businesses:
                return {
                    "success": False,
                    "error": "no_practitioner_locations",
                    "message": f"{practitioner['full_name']} doesn't work at any of our locations. Please check with our staff about their schedule.",
                    "sessionId": request.sessionId
                }
        
            # If single business where practitioner works, use it
            if len(practitioner_businesses) == 1:
                business = dict(practitioner_businesses[0])
                logger.info(f"Using single practitioner business: {business['business_name']}")
            else:
                # Multiple businesses where practitioner works - need clarification
                # For availability_checker, we need to check actual availability on the specific date
                logger.info(f"Specific date provided ({request.date}), checking actual availability")
                
                # Parse the date
                clinic_tz = get_clinic_timezone(clinic)
                check_date = parse_date_request(request.date, clinic_tz)
                
                # Check availability at each location
                available_locations = []
                for biz in practitioner_businesses:
                    # Get cached availability or fetch from Cliniko
                    cached_slots = await cache.get_availability(
                        practitioner['practitioner_id'],
                        biz['business_id'],
                        check_date
                    )
                    
                    if cached_slots is not None:
                        has_availability = len(cached_slots) > 0
                    else:
                        # Fetch from Cliniko
                        if not cliniko:
                            cliniko = ClinikoAPI(
                                clinic.cliniko_api_key,
                                clinic.cliniko_shard,
                                clinic.contact_email
                            )
                        from_date = check_date.isoformat()
                        to_date = check_date.isoformat()
                        available_times = await cliniko.get_available_times(
                            biz['business_id'],
                            practitioner['practitioner_id'],
                            service['appointment_type_id'],
                            from_date,
                            to_date
                        )
                        
                        # Cache the results
                        await cache.set_availability(
                            practitioner['practitioner_id'],
                            biz['business_id'],
                            check_date,
                            clinic.clinic_id,
                            available_times
                        )
                        
                        has_availability = len(available_times) > 0
                    
                    if has_availability:
                        available_locations.append(biz['business_name'])
                
                if not available_locations:
                    # No availability at any location on this date
                    all_location_names = [biz['business_name'] for biz in practitioner_businesses]
                    # For each location, find the next available date
                    next_available_per_location = []
                    max_days_to_search = 30
                    for biz in practitioner_businesses:
                        found_next = False
                        for days_ahead in range(1, max_days_to_search+1):
                            next_date = check_date + timedelta(days=days_ahead)
                            cached_slots = await cache.get_availability(
                                practitioner['practitioner_id'],
                                biz['business_id'],
                                next_date
                            )
                            if cached_slots is not None:
                                has_availability = len(cached_slots) > 0
                            else:
                                if not cliniko:
                                    cliniko = ClinikoAPI(
                                        clinic.cliniko_api_key,
                                        clinic.cliniko_shard,
                                        clinic.contact_email
                                    )
                                from_date = next_date.isoformat()
                                to_date = next_date.isoformat()
                                available_times = await cliniko.get_available_times(
                                    biz['business_id'],
                                    practitioner['practitioner_id'],
                                    service['appointment_type_id'],
                                    from_date,
                                    to_date
                                )
                                await cache.set_availability(
                                    practitioner['practitioner_id'],
                                    biz['business_id'],
                                    next_date,
                                    clinic.clinic_id,
                                    available_times
                                )
                                has_availability = len(available_times) > 0
                            if has_availability:
                                next_available_per_location.append(
                                    f"{biz['business_name']}: {next_date.strftime('%A, %B %d, %Y')}"
                                )
                                found_next = True
                                break
                        if not found_next:
                            next_available_per_location.append(f"{biz['business_name']}: no availability in next {max_days_to_search} days")
                    next_msg = "\n".join(next_available_per_location)
                    return {
                        "success": True,
                        "message": f"{practitioner['full_name']} doesn't have any availability on {check_date.strftime('%A, %B %d, %Y')} at any of their locations ({', '.join(all_location_names)}).\nNext available days by location:\n{next_msg}",
                        "sessionId": request.sessionId
                    }
                elif len(available_locations) == 1:
                    # Only one location has availability - use it
                    business = next(biz for biz in practitioner_businesses if biz['business_name'] == available_locations[0])
                    logger.info(f"Using single available location: {business['business_name']}")
                else:
                    # Multiple locations have availability - need clarification
                    return {
                        "success": True,
                        "action_completed": False,
                        "needs_clarification": True,
                        "message": f"Which location would you like to check? {practitioner['full_name']} has availability on {check_date.strftime('%A, %B %d, %Y')} at: {', '.join(available_locations)}",
                        "options": available_locations,
                        "sessionId": request.sessionId
                    }
        
        if not business:
            return {
                "success": False,
                "error": "no_location",
                "message": "I need to know which location you'd like to check. Which of our clinics would you prefer?",
                "sessionId": request.sessionId
            }
        
        logger.info(f"Using business: {business['business_name']}")
        
        # AVAILABILITY_CHECKER: Only handles specific date queries
        # Regular date parsing for the specific date provided
        clinic_tz = get_clinic_timezone(clinic)
        check_date = parse_date_request(request.date, clinic_tz)

        # Fix: Use single day query to avoid timezone boundary issues
        from_date = check_date.isoformat()
        to_date = check_date.isoformat()  # SAME DATE

        logger.info(f"Checking availability for {from_date} (single day)")
        
        # Get available times (with caching)
        cached_slots = await cache.get_availability(
            practitioner['practitioner_id'],
            business['business_id'],
            check_date
        )

        if cached_slots is not None:
            available_times = cached_slots
            logger.info(f"Availability cache hit for {practitioner['practitioner_id']} on {check_date}")
        else:
            # Always fetch from Cliniko on cache miss
            if not cliniko:
                cliniko = ClinikoAPI(
                    clinic.cliniko_api_key,
                    clinic.cliniko_shard,
                    clinic.contact_email
                )
            logger.info(f"Availability cache miss, fetching from Cliniko")
            available_times = await cliniko.get_available_times(
                business['business_id'],
                practitioner['practitioner_id'],
                service['appointment_type_id'],
                from_date,
                to_date
            )
            # Cache the results
            await cache.set_availability(
                practitioner['practitioner_id'],
                business['business_id'],
                check_date,
                clinic.clinic_id,
                available_times
            )
        
        logger.info(f"Found {len(available_times)} available slots")
        
        # Filter out recently failed slots
        async with pool.acquire() as conn:
            failed_slots = await conn.fetch("""
                SELECT appointment_time::text as time
                FROM failed_booking_attempts
                WHERE practitioner_id = $1
                  AND business_id = $2
                  AND appointment_date = $3
                  AND created_at > NOW() - INTERVAL '2 hours'
            """, practitioner['practitioner_id'], business['business_id'], check_date)
            failed_times = {row['time'] for row in failed_slots}
            # Filter slots - use cached_slots if available, otherwise slots
            available_slots = cached_slots if cached_slots is not None else available_times
            filtered_slots = [
                slot for slot in available_slots 
                if slot.get('appointment_start', '').split('T')[1][:5] not in failed_times
            ]
        
        # Format times for response
        clinic_tz = get_clinic_timezone(clinic)
        formatted_times = []
        if filtered_slots:
            for slot in filtered_slots:
                slot_local = convert_utc_to_local(slot['appointment_start'], clinic_tz)
                formatted_times.append(format_time_for_voice(slot_local))
        
        # Build response message
        if not filtered_slots:
            message = f"I'm sorry, {practitioner['full_name']} doesn't have any available appointments at {business['business_name']} on {check_date.strftime('%A, %B %d, %Y')}. Would you like me to check another day or location?"
        elif len(formatted_times) <= 4:
            message = f"{practitioner['full_name']} has the following times available at {business['business_name']} on {check_date.strftime('%A, %B %d, %Y')}: {', '.join(formatted_times)}"
        else:
            # Group by morning/afternoon/evening
            morning = []
            afternoon = []
            evening = []
            
            for time_str in formatted_times:
                hour = int(time_str.split(':')[0])
                is_pm = 'pm' in time_str.lower()
                
                if is_pm:
                    if hour == 12 or hour < 5:
                        afternoon.append(time_str)
                    else:
                        evening.append(time_str)
                else:
                    morning.append(time_str)
            
            message = f"{practitioner['full_name']} has availability at {business['business_name']} on {check_date.strftime('%A, %B %d, %Y')}:"
            if morning:
                message += f"\n\nMorning: {', '.join(morning[:5])}"
                if len(morning) > 5:
                    message += f" and {len(morning) - 5} more"
            if afternoon:
                message += f"\n\nAfternoon: {', '.join(afternoon[:5])}"
                if len(afternoon) > 5:
                    message += f" and {len(afternoon) - 5} more"
            if evening:
                message += f"\n\nEvening: {', '.join(evening[:3])}"
                if len(evening) > 3:
                    message += f" and {len(evening) - 3} more"
        
        # Create standardized response
        response = AvailabilityResponse(
            success=True,
            sessionId=request.sessionId,
            message=message,
            practitioner=PractitionerData(
                id=practitioner['practitioner_id'],
                name=practitioner['full_name'],
                firstName=practitioner['first_name']
            ),
            date=check_date.strftime('%A, %B %d, %Y'),
            slots=[
                TimeSlotData(
                    date=check_date.strftime('%A, %B %d, %Y'),
                    time=slot,  # Should be in HH:MM format
                    displayTime=slot  # Human readable
                )
                for slot in formatted_times
            ],
            location=LocationData(
                id=business['business_id'],
                name=business['business_name']
            ) if business else None
        )
        
        return response.dict()
        
    except Exception as e:
        logger.error(f"Availability check error: {str(e)}", exc_info=True)
        return {
            "success": False,
            "error": "availability_check_failed",
            "message": "I'm sorry, I encountered an error while checking availability. Please try again.",
            "sessionId": request.sessionId if 'request' in locals() else 'unknown'
        }

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
        clinic.contact_email
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
        # Require explicit appointmentType for availability check
        # If not provided, return error listing available services
        services_query = """
            SELECT DISTINCT at.name
            FROM practitioner_appointment_types pat
            JOIN appointment_types at ON pat.appointment_type_id = at.appointment_type_id
            WHERE pat.practitioner_id = $1
            ORDER BY at.name
        """
        services = await conn.fetch(services_query, prac['practitioner_id'])
        service_names = [s['name'] for s in services]
        # If no appointmentType specified, return error
        # (This logic may need to be moved up depending on endpoint design)
        # For now, skip practitioners without explicit service selection
        continue  # Remove this line and implement explicit selection logic as needed
    
    # Format response
    if not available_practitioners:
        message = f"I don't see any available appointments at {business_name} on {check_date.strftime('%A, %B %d')}. Would you like me to check another day?"
    else:
        names = [p['practitioner_name'] for p in available_practitioners]
        date_str = check_date.strftime('%A, %B %d')
        
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
        sessionId=request.sessionId,
        message=f"Found {len(practitioners)} available practitioners.",
        practitioners=[PractitionerData(id=p['practitioner_id'], name=p['practitioner_name']) for p in available_practitioners],
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
        logger.info(f"=== FIND NEXT AVAILABLE START ===")
        logger.info(f"Request body: {body}")
    
        # Flexible inputs - handle both field names for compatibility
        service_name = body.get('service') or body.get('appointmentType')  # e.g., "massage"
        practitioner_name = body.get('practitioner')  # e.g., "Brendan"
        business_id = body.get('business_id')  # Optional: specific business
        business_name = body.get('businessName')  # For response formatting
        max_days = body.get('maxDays', 14)  # How far to search (default 2 weeks)
        dialed_number = body.get('dialedNumber', '')
        session_id = body.get('sessionId', '')
        
        logger.info(f"Parsed inputs - service: {service_name}, practitioner: {practitioner_name}, dialed_number: {dialed_number}")
    
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
            clinic.contact_email
        )
    
        # Build the search criteria
        search_criteria = []
    
        # CASE 1: Find specific practitioner (across all their businesses)
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
                    "message": practitioner_result.get("message", f"I couldn't find {practitioner_name}."),
                    "sessionId": session_id
                }
            
            # Get the single practitioner (should be only one at this point)
            practitioner = practitioner_result["matches"][0]
            
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
        
        # CASE 2: Find specific service (across all practitioners/businesses)
        elif service_name:
            logger.info(f"Case 2: Finding service {service_name}")
            # Get all practitioners who offer this service
            services = await get_practitioner_services(clinic.clinic_id, pool)
            
            # Filter by service name (fuzzy match)
            matching_services = []
            service_normalized = normalize_for_matching(service_name)
            
            for service in services:
                if (service_normalized in normalize_for_matching(service['service_name']) or
                    normalize_for_matching(service['service_name']) in service_normalized):
                    
                    # If business specified, filter by it
                    if not business_id or service['business_id'] == business_id:
                        matching_services.append(service)
            
            if not matching_services:
                if business_name:
                    logger.error(f"No {service_name} services found at {business_name}")
                return {
                    "success": False,
                    "message": f"I couldn't find {service_name} services at {business_name}.",
                    "sessionId": session_id
                }
            else:
                logger.error(f"No {service_name} services found")
                return {
                    "success": False,
                    "message": f"I couldn't find any {service_name} services available.",
                    "sessionId": session_id
                }
            
            # Group by practitioner and location
            seen = set()
            for service in matching_services:
                key = (service['practitioner_id'], service['business_id'])
                if key not in seen:
                    seen.add(key)
                    search_criteria.append({
                        'practitioner_id': service['practitioner_id'],
                        'practitioner_name': service['practitioner_name'],
                        'business_id': service['business_id'],
                        'business_name': service['business_name'],
                        'appointment_type_id': service['appointment_type_id'],
                        'service_name': service['service_name']
                    })
        
        else:
            logger.error("Neither practitioner nor service specified")
            return {
                "success": False,
                "message": "Please specify either a practitioner name or service type.",
                "sessionId": session_id
            }
        
        logger.info(f"Search criteria built: {len(search_criteria)} combinations")
        
        # Search for availability across all criteria
        earliest_slot = None
        earliest_date = None
        earliest_criteria = None
        
        clinic_tz = get_clinic_timezone(clinic)
        search_start = datetime.now(clinic_tz).date()
        search_end = search_start + timedelta(days=max_days)
        
        logger.info(f"Searching from {search_start} to {search_end}")
        
        # Check each day
        for days_ahead in range(max_days):
            check_date = search_start + timedelta(days=days_ahead)
            from_date = check_date.isoformat()
            to_date = check_date.isoformat()  # SAME DATE
            
            logger.info(f"Checking date: {check_date}")
            
            # Check each practitioner/location combination
            for criteria in search_criteria:
                logger.info(f"Checking criteria: {criteria['practitioner_name']} at {criteria['business_name']}")
                
                # Get available times (with caching)
                cached_slots = await cache.get_availability(
                    criteria['practitioner_id'],
                    criteria['business_id'],
                    check_date
                )
                
                if cached_slots is not None:
                    slots = cached_slots
                    logger.info(f"Using cached slots: {len(slots)}")
                else:
                    # Always fetch from Cliniko on cache miss
                    if not cliniko:
                        cliniko = ClinikoAPI(
                            clinic.cliniko_api_key,
                            clinic.cliniko_shard,
                            clinic.contact_email
                        )
                    logger.info(f"Availability cache miss, fetching from Cliniko")
                    slots = await cliniko.get_available_times(
                        criteria['business_id'],
                        criteria['practitioner_id'],
                        criteria['appointment_type_id'],
                        from_date,
                        to_date
                    )
                    # Cache the results
                    await cache.set_availability(
                        criteria['practitioner_id'],
                        criteria['business_id'],
                        check_date,
                        clinic.clinic_id,
                        slots
                    )
                
                # Filter out recently failed slots
                async with pool.acquire() as conn:
                    failed_slots = await conn.fetch("""
                        SELECT appointment_time::text as time
                        FROM failed_booking_attempts
                        WHERE practitioner_id = $1
                          AND business_id = $2
                          AND appointment_date = $3
                          AND created_at > NOW() - INTERVAL '2 hours'
                    """, criteria['practitioner_id'], criteria['business_id'], check_date)
                    failed_times = {row['time'] for row in failed_slots}
                    # Filter slots - use cached_slots if available, otherwise slots
                    available_slots = cached_slots if cached_slots is not None else slots
                    filtered_slots = [
                        slot for slot in available_slots 
                        if slot.get('appointment_start', '').split('T')[1][:5] not in failed_times
                    ]
                
                # If we found slots, this is our earliest
                if filtered_slots and len(filtered_slots) > 0:
                    earliest_slot = filtered_slots[0]
                    earliest_date = check_date
                    earliest_criteria = criteria
                    logger.info(f"Found earliest slot: {earliest_slot}")
                    break
            
            # If we found something, stop searching
            if earliest_slot:
                break
        
        # Format response
        if not earliest_slot:
            if practitioner_name:
                message = f"I couldn't find any available appointments with {practitioner_name} in the next {max_days} days."
            elif business_name:
                message = f"I couldn't find any available {service_name} appointments at {business_name} in the next {max_days} days."
            else:
                message = f"I couldn't find any available {service_name} appointments in the next {max_days} days."
            
            logger.info(f"No availability found: {message}")
            return {
                "success": True,
                "found": False,
                "message": message,
                "sessionId": session_id
            }
        
        # Convert to local time
        slot_utc = datetime.fromisoformat(earliest_slot['appointment_start'].replace('Z', '+00:00'))
        clinic_tz = get_clinic_timezone(clinic)
        slot_local = slot_utc.astimezone(clinic_tz)
        
        # Format the response message
        date_str = slot_local.strftime('%A, %B %d')
        time_str = format_time_for_voice(slot_local)
        
        if practitioner_name:
            message = f"The next available appointment with {earliest_criteria['practitioner_name']} is {date_str} at {time_str} at our {earliest_criteria['business_name']}."
        else:
            message = f"The next available {earliest_criteria.get('service_name', 'appointment')} is {date_str} at {time_str} with {earliest_criteria['practitioner_name']} at our {earliest_criteria['business_name']}."
        
        logger.info(f"Success response: {message}")
        
        response = NextAvailableResponse(
            success=True,
            sessionId=session_id,
            message=message,
            found=True,
            slot=TimeSlotData(
                date=date_str,
                time=time_str,
                displayTime=time_str
            ),
            practitioner=PractitionerData(
                id=earliest_criteria['practitioner_id'],
                name=earliest_criteria['practitioner_name'],
                firstName=earliest_criteria['practitioner_name'].split()[0] if earliest_criteria['practitioner_name'] else ""
            ),
            service=None, # No specific service object in this endpoint's response
            location=LocationData(
                id=earliest_criteria['business_id'],
                name=earliest_criteria['business_name']
            )
        )
        return response.dict()
    except Exception as e:
        logger.error(f"Error in find_next_available: {str(e)}", exc_info=True)
        return {
            "success": False,
            "error": "internal_error",
            "message": f"An error occurred while finding availability: {str(e)}",
            "sessionId": body.get('sessionId', '') if 'body' in locals() else ''
        }