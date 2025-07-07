# tools/location_tools.py
"""Location-related endpoints for the Voice Booking System"""

from fastapi import APIRouter, Request, Depends, BackgroundTasks
from typing import Dict, Any
import logging

# Local imports
from .dependencies import verify_api_key, get_db, get_cache
from models import (
    LocationResolverRequest,
    LocationResolverResponse,  # Use directly, no alias
    LocationData,
    create_error_response,
    GetPractitionersResponse, # Added this import
    PractitionerData # Added this import
)
from database import get_clinic_by_dialed_number, get_location_by_name
from location_resolver import LocationResolver
from utils import normalize_phone
from payload_logger import payload_logger
from .cache_utils import check_and_trigger_sync

logger = logging.getLogger(__name__)

# Create router
router = APIRouter(tags=["location"])

@router.post("/location-resolver")
async def resolve_location(
    location_request: LocationResolverRequest,
    background_tasks: BackgroundTasks,
    authenticated: bool = Depends(verify_api_key)
) -> Dict[str, Any]:
    """Resolve ambiguous location references - ElevenLabs optimized"""

    # Log the incoming request
    payload_logger.log_payload("/location-resolver", location_request.dict())

    try:
        logger.info("=== LOCATION RESOLUTION START ===")
        logger.info(f"Session: {location_request.sessionId}")
        logger.info("Query: '{location_request.locationQuery}'")
        logger.info(f"Caller: {location_request.callerPhone if location_request.callerPhone else 'Unknown'}")

        # Get database pool
        pool = await get_db()
        cache = await get_cache()

        # Get clinic information
        clinic = await get_clinic_by_dialed_number(location_request.dialedNumber, pool)
        if not clinic:
            return create_error_response(
                error_code="clinic_not_found",
                message="I couldn't find the clinic information. Please contact the clinic directly.",
                session_id=location_request.sessionId
            )
        # Trigger background sync if needed
        background_tasks.add_task(
            check_and_trigger_sync,
            clinic.clinic_id,
            pool,
            cache,
            clinic.cliniko_api_key,
            clinic.cliniko_shard
        )

        # Initialize location resolver
        resolver = LocationResolver(pool, cache)

        # Resolve location (this returns the new LocationResolverResponse)
        response = await resolver.resolve_location(location_request, clinic.clinic_id)

        # The response is already in the correct format, just convert to dict
        response_dict = response.dict()

        logger.info(f"Location resolution result: resolved = \
            {response.resolved}, needs_clarification={response.needs_clarification}, confidence={response.confidence}")

        return response_dict

    except Exception as e:
        logger.error(f"Location resolution error: {str(e)}", exc_info=True)
        return create_error_response(
            error_code="location_resolution_error",
            message="I encountered an error resolving the location. Please try again.",
            session_id=location_request.sessionId
        )

@router.post("/confirm-location")
async def confirm_location(
    request: Request,  # Changed from ConfirmLocationRequest to Request
    authenticated: bool = Depends(verify_api_key)
) -> Dict[str, Any]:
    """Handle location confirmation from user - ElevenLabs compatible"""

    # Extract JSON body
    body = await request.json()
    payload_logger.log_payload("/confirm-location", body)

    # Extract parameters with safe defaults (like get_practitioner_info does)
    user_response = body.get('userResponse', '')
    options = body.get('options', [])
    session_id = body.get('sessionId', '')
    dialed_number = body.get('dialedNumber', '')
    caller_phone = body.get('callerPhone') or body.get('systemCallerID', '')

    try:
        logger.info("=== LOCATION CONFIRMATION ===")
        logger.info(f"Session: {session_id}")
        logger.info("User response: '{user_response}'")
        logger.info(f"Options: {options}")

        # VALIDATION: Check if we have the required data
        if not options or len(options) == 0:
            logger.warning("confirm-location called without options - likely called without location-resolver first")
            # Guide the agent to the correct flow
            response = LocationResolverResponse(
                success=True,
                sessionId=session_id,
                message="I need to check which locations are available first. Let me look that up for you.",
                resolved=False,
                needsClarification=False,
                options=None,
                confidence=0.0
            )
            response_dict = response.dict()
            response_dict['action'] = 'need_location_resolver'  # Hint for the agent
            response_dict['location_confirmed'] = False
            return response_dict

        # If no user response provided
        if not user_response:
            return {
                "success": True,
                "location_confirmed": False,
                "message": "Could you please tell me which location you prefer?",
                "options": options,
                "sessionId": session_id
            }

        # Parse user response
        user_response_lower = user_response.lower().strip()

        # Rest of the confirmation logic remains the same...
        selected_location = None
        selected_index = None

        # Direct index reference: "the first one", "number 2", "1", "2"
        if any(x in user_response_lower for x in ["first", "1st", "one"]) or user_response_lower == "1":
            selected_index = 0
        elif any(x in user_response_lower for x in ["second", "2nd", "two"]) or user_response_lower == "2":
            selected_index = 1
        elif any(x in user_response_lower for x in ["third", "3rd", "three"]) or user_response_lower == "3":
            selected_index = 2

        # Yes/no responses (assume first option)
        if selected_index is None and any(x in user_response_lower for x in ["yes",\
            "yeah", "yep", "sure", "correct", "that's right", "that one"]):
            selected_index = 0

        # Direct name match
        if selected_index is None:
            for idx, option in enumerate(options):
                option_lower = option.lower()
                # Check if user response contains the option or vice versa
                if option_lower in user_response_lower or user_response_lower in option_lower:
                    selected_index = idx
                    break

                # Check for partial matches (at least 3 characters)
                words_in_response = user_response_lower.split()
                words_in_option = option_lower.split()
                for word in words_in_response:
                    if len(word) >= 3 and any(word in opt_word for opt_word in words_in_option):
                        selected_index = idx
                        break

        # Handle "last" or "other" for 2-option scenarios
        if selected_index is None and len(options) == 2:
            if any(x in user_response_lower for x in ["last", "other", "second", "latter"]):
                selected_index = 1

        # If we found a selection
        if selected_index is not None and selected_index < len(options):
            selected_location = options[selected_index]

            # Get database pool
            pool = await get_db()
            cache = await get_cache()

            # Get clinic to find location ID
            clinic = await get_clinic_by_dialed_number(dialed_number, pool)
            if not clinic:
                return {
                    "success": True,
                    "location_confirmed": False,
                    "message": "I'm having trouble accessing the clinic information. Could you please try again?",
                    "sessionId": session_id
                }

            # Resolve to actual business_id
            location_data = await get_location_by_name(
                clinic.clinic_id,
                selected_location,
                pool
            )

            if location_data:
                # Update caller's preferred location in cache
                if caller_phone:
                    phone_normalized = normalize_phone(caller_phone)
                    context = await cache.get_booking_context(phone_normalized) or {}
                    context['preferred_location'] = {
                        'business_id': location_data['business_id'],
                        'business_name': location_data['business_name']
                    }
                    await cache.set_booking_context(phone_normalized, clinic.clinic_id, context)

                logger.info(f"Location confirmed: {selected_location} -> {location_data['business_id']}")
                logger.info(f"✓ Location confirmed: {selected_location} -> {location_data['business_id']}")
                # Create successful response
                response = LocationResolverResponse(
                    success=True,
                    sessionId=session_id,
                    message="Perfect! I'll use our {selected_location} for your appointment.",
                    resolved=True,
                    needsClarification=False,
                    location=LocationData(
                        id=location_data['business_id'],
                        name=location_data['business_name']
                    ),
                    confidence=1.0
                )
                # Add compatibility fields
                response_dict = response.dict()
                response_dict['location_confirmed'] = True
                return response_dict
            else:
                logger.error(f"Could not find location data for: {selected_location}")
                return create_error_response(
                    error_code="location_not_found",
                    message = \
                        "I'm having trouble finding that location in our system. Let me check what locations are available.",
                    session_id=session_id
                )

        # Couldn't parse response - ask again with clearer instructions
        if len(options) == 1:
            # Single option - treat as yes/no
            return {
                "success": True,
                "location_confirmed": False,
                "message": f"Just to confirm, would you like to book at {options[0]}? Please say yes or no.",
                "options": options,
                "sessionId": session_id
            }
        elif len(options) == 2:
            return {
                "success": True,
                "location_confirmed": False,
                "message": f"I have two locations: {options[0]} and {options[1]}. You can say 'first', 'second', or the location name.",
                "options": options,
                "sessionId": session_id
            }
        else:
            # Multiple options
            return {
                "success": True,
                "location_confirmed": False,
                "message": "I didn't catch that. Could you please tell me which location you prefer? You can say 'first', 'second', 'third', or the location name.",
                "options": options,
                "sessionId": session_id
            }

    except Exception as e:
        logger.error(f"Location confirmation error: {str(e)}", exc_info=True)
        # Return a graceful response instead of an error
        return {
            "success": True,
            "location_confirmed": False,
            "message": "I'm having a little trouble with that. Could you please repeat which location you'd like?",
            "sessionId": session_id
        }

@router.post("/get-location-practitioners")
async def get_location_practitioners(
    request: Request,
    authenticated: bool = Depends(verify_api_key)
) -> Dict[str, Any]:
    """Get all practitioners who work at a specific business/location"""
    body = await request.json()
    business_id = body.get('business_id', '')  # From location-resolver
    business_name = body.get('businessName', '')
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
    
    # Query practitioners at this business
    query = """
        SELECT DISTINCT
            p.practitioner_id,
            CASE
                WHEN p.title IS NOT NULL AND p.title != ''
                THEN CONCAT(p.title, ' ', p.first_name, ' ', p.last_name)
                ELSE CONCAT(p.first_name, ' ', p.last_name)
            END as practitioner_name,
            p.first_name,
            p.last_name,
            COUNT(DISTINCT pat.appointment_type_id) as service_count
        FROM practitioners p
        JOIN practitioner_businesses pb ON p.practitioner_id = pb.practitioner_id
        JOIN practitioner_appointment_types pat ON p.practitioner_id = pat.practitioner_id
        WHERE pb.business_id = $1
          AND p.active = true
          AND p.clinic_id = $2
        GROUP BY p.practitioner_id, p.first_name, p.last_name, p.title
        ORDER BY practitioner_name
    """
    
    async with pool.acquire() as conn:
        rows = await conn.fetch(query, business_id, clinic.clinic_id)
    
    practitioners = [row for row in rows]
    
    if not practitioners:
        return {
            "success": False,
            "message": "I couldn't find any practitioners at that location.",
            "sessionId": session_id
        }
    
    # Create response using the proper model
    response = GetPractitionersResponse(
        success=True,
        sessionId=session_id,
        message=f"At {business_name}, we have {len(practitioners)} practitioners available.",
        location=LocationData(
            id=business_id,
            name=business_name
        ),
        practitioners=[
            PractitionerData(
                id=p['practitioner_id'],
                name=p['practitioner_name'],
                firstName=p.get('first_name', p['practitioner_name'].split()[0]),
                servicesCount=p.get('service_count', 0)
            )
            for p in practitioners
        ]
    )
    
    return response.dict()
