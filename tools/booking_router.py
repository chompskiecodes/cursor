# tools/booking_tools.py
"""Booking-related endpoints for the Voice Booking System"""

from fastapi import APIRouter, Request, Depends, BackgroundTasks
from typing import Dict, Any, Optional
from datetime import datetime, timedelta, timezone
import logging
import httpx
import asyncpg

# Local imports
from .dependencies import verify_api_key, get_db, get_cache
from models import (
    ActionType, BookingRequest,
    CancelRequest, RescheduleRequest,
    BookingResponse,
    PractitionerData,
    ServiceData,
    LocationData,
    TimeSlotData,
    create_error_response,
    BaseRequest
)
from database import (
    get_clinic_by_dialed_number,
    get_practitioner_services, match_practitioner,
    match_service, match_business, log_voice_booking,
    update_appointment_status,
    find_appointment_by_details, save_appointment_to_db,
    invalidate_practitioner_availability
)
from cliniko import ClinikoAPI
from utils import (
    parse_date_request, parse_time_request
)
from payload_logger import payload_logger
from .cache_utils import check_and_trigger_sync
from tools.timezone_utils import (
    get_clinic_timezone,
    convert_utc_to_local,
    format_time_for_voice,
    parse_cliniko_time
)
from error_handlers import (
    handle_clinic_not_found, handle_missing_information,
    handle_practitioner_not_found, handle_service_not_found,
    handle_no_availability, handle_booking_error,
    handle_cancellation_error, check_practitioner_location_compatibility,
    validate_booking_request, handle_appointment_creation_api_error
)

# Configure logging levels
logger = logging.getLogger(__name__)

# Create a custom logger for detailed booking flow - only shows in debug mode
booking_flow_logger = logging.getLogger(f"{__name__}.flow")
booking_flow_logger.setLevel(logging.DEBUG)

# Create router
router = APIRouter(tags=["booking"])

# Add after imports, before the router definition

async def find_patient_with_cache(
    clinic_id: str,
    phone: str,
    pool: asyncpg.Pool,
    cache: Any,  # or CacheManagerProtocol
    cliniko_api = None
) -> Optional[Dict[str, Any]]:
    """Find patient with caching layer"""
    from utils import normalize_phone
    phone_normalized = normalize_phone(phone)

    # Try cache first
    cached = await cache.get_patient(phone_normalized, clinic_id)
    if cached:
        logger.info(f"Patient cache hit for {phone_normalized[:3]}***")
        return cached

    # Try database
    from database import find_patient_by_phone
    patient = await find_patient_by_phone(clinic_id, phone, pool)

    if patient:
        # Cache the result
        await cache.set_patient(phone_normalized, clinic_id, patient['patient_id'], patient)
        return patient

    # If not in DB and we have Cliniko API, check there
    if cliniko_api:
        cliniko_patient = await cliniko_api.find_patient(phone)
        if cliniko_patient:
            # Transform to our format
            patient_data = {
                "patient_id": str(cliniko_patient['id']),
                "first_name": cliniko_patient['first_name'],
                "last_name": cliniko_patient['last_name'],
                "phone_number": phone,
                "email": cliniko_patient.get('email')
            }

            # Cache it
            await cache.set_patient(
                phone_normalized,
                clinic_id,
                patient_data['patient_id'],
                patient_data
            )

            return patient_data

    return None

# Helper function to check and trigger sync
async def check_and_trigger_sync(
    clinic_id: str,
    pool,
    cache,
    cliniko_api_key: str,
    cliniko_shard: str
):
    """Check if sync needed and trigger if so"""
    try:
        # Check last sync time
        async with pool.acquire() as conn:
            last_sync = await conn.fetchval("""
                SELECT MAX(cached_at)
                FROM availability_cache
                WHERE clinic_id = $1
            """, clinic_id)

        # Use timezone-aware current time
        current_time = datetime.now(timezone.utc)

        # If no sync or older than 5 minutes, trigger sync
        if not last_sync:
            should_sync = True
        else:
            # Ensure last_sync is timezone-aware
            if last_sync.tzinfo is None:
                # Assume database times are UTC
                last_sync = last_sync.replace(tzinfo=timezone.utc)

            time_diff = (current_time - last_sync).total_seconds()
            should_sync = time_diff > 300

        if should_sync:
            from cache_manager import IncrementalCacheSync
            from cliniko import ClinikoAPI

            cliniko = ClinikoAPI(cliniko_api_key, cliniko_shard, user_agent="sync@voicebookingsystem")
            sync = IncrementalCacheSync(cache, pool)
            await sync.sync_appointments_incremental(clinic_id, cliniko)
    except Exception as e:
        logger.warning(f"Sync check failed: {e}")

# Main appointment handler
@router.post("/appointment-handler")
async def handle_appointment(
    request: BookingRequest,
    background_tasks: BackgroundTasks,
    authenticated: bool = Depends(verify_api_key)
) -> Dict[str, Any]:
    """Main appointment booking handler"""
    payload_logger.log_payload("/appointment-handler", request.model_dump())

    # Use INFO for important milestones only
    logger.info(f"Booking request: session={request.sessionId}, action={request.action}")

    # Use DEBUG for detailed flow tracking
    booking_flow_logger.debug("=== BOOKING REQUEST START ===")
    booking_flow_logger.debug(f"Session: {request.sessionId}")
    booking_flow_logger.debug(f"Action: {request.action}")
    booking_flow_logger.debug(f"Practitioner: '{request.practitioner}'")
    booking_flow_logger.debug(f"Service: '{getattr(request, 'service', getattr(request, 'appointmentType', None))}'")

    try:
        # Route based on action
        if request.action == ActionType.BOOK:
            return await handle_booking(request, background_tasks)
        elif request.action == ActionType.MODIFY:
            return await handle_modify(request)
        elif request.action == ActionType.RESCHEDULE:
            return await handle_reschedule(request)
        elif request.action == ActionType.CANCEL:
            # Convert to CancelRequest
            cancel_request = CancelRequest(
                sessionId=request.sessionId,
                callerPhone=request.callerPhone,
                dialedNumber=request.dialedNumber,
                appointmentId=request.appointmentId,
                appointmentDetails=request.notes
            )
            return await cancel_appointment(cancel_request)
        else:
            return create_error_response(
                error_code="invalid_action",
                message=f"Action '{request.action}' is not supported.",
                session_id=request.sessionId
            )

        # Log success at INFO level
        logger.info(f"✓ Booking completed: appointment_id={appointment['id']}, session={request.sessionId}")
        # Detailed success info at DEBUG
        booking_flow_logger.debug(f"Appointment details: {appointment}")
    except Exception as e:
        # Errors always at ERROR level
        logger.error(f"Booking failed: session={request.sessionId}, error={str(e)}")
        raise

@router.post("/appointment-handler")
async def appointment_handler_direct(
    request: Request,
    authenticated: bool = Depends(verify_api_key)
) -> Dict[str, Any]:
    """
    Direct appointment booking handler for ElevenLabs voice agent.
    Creates the actual appointment after find_next_available has been called.
    This is a separate endpoint from handle_appointment to avoid routing complexity.
    """

    body = await request.json()
    payload_logger.log_payload("/appointment-handler", body)

    logger.info("=== APPOINTMENT HANDLER DIRECT START ===")
    logger.info(f"Session: {body.get('sessionId')}")
    logger.info(f"Patient: {body.get('patientName')}")
    logger.info(f"Service: {body.get('appointmentType')}")
    logger.info(f"Date/Time: {body.get('appointmentDate')} at {body.get('appointmentTime')}")
    logger.info(f"Location ID: {body.get('business_id')}")

    clinic = None

    try:
        # Get database pool and cache
        pool = await get_db()
        cache = await get_cache()

        # Extract required fields from request body
        dialed_number = body.get('dialedNumber')
        session_id = body.get('sessionId', 'unknown')
        patient_name = body.get('patientName')
        practitioner_name = body.get('practitioner')
        appointment_type = body.get('appointmentType')
        appointment_date_str = body.get('appointmentDate')  # YYYY-MM-DD
        appointment_time_str = body.get('appointmentTime')  # HH:MM
        business_id = body.get('business_id')
        caller_phone = body.get('callerPhone') or body.get('systemCallerID')
        patient_phone = body.get('patientPhone') or caller_phone
        notes = body.get('notes', '')

        # Validate required fields
        missing_fields = []
        if not patient_name:
            missing_fields.append("patient name")
        if not practitioner_name:
            missing_fields.append("practitioner")
        if not appointment_type:
            missing_fields.append("appointment type")
        if not appointment_date_str:
            missing_fields.append("appointment date")
        if not appointment_time_str:
            missing_fields.append("appointment time")
        if not business_id:
            missing_fields.append("business ID")

        if missing_fields:
            return {
                "success": False,
                "error": "missing_information",
                "message": f"I need the following information to book the appointment: {', '.join(missing_fields)}",
                "sessionId": session_id,
                "missingFields": missing_fields
            }

        # Get clinic information
        clinic = await get_clinic_by_dialed_number(dialed_number, pool)
        if not clinic:
            return {
                "success": False,
                "error": "clinic_not_found",
                "message": "I couldn't find the clinic information.",
                "sessionId": session_id
            }

        # Validate clinic timezone
        clinic_tz = get_clinic_timezone(clinic)

        logger.info(f"✓ Found clinic: {clinic.clinic_name}")

        # Initialize Cliniko API
        cliniko = ClinikoAPI(
            clinic.cliniko_api_key,
            clinic.cliniko_shard,
            clinic.contact_email
        )

        # Find or create patient
        logger.info(f"Looking for patient with phone: {patient_phone}")

        # Use cached patient lookup
        patient = await find_patient_with_cache(
            clinic.clinic_id,
            patient_phone,
            pool,
            cache,
            cliniko
        )

        if not patient:
            logger.info("Patient not found, creating new patient...")
            name_parts = patient_name.strip().split(' ', 1)
            patient_data = {
                "first_name": name_parts[0],
                "last_name": name_parts[1] if len(name_parts) > 1 else "Patient",
                "phone": patient_phone
            }
            cliniko_patient = await cliniko.create_patient(patient_data)
            patient = {
                "patient_id": str(cliniko_patient['id']),
                "first_name": cliniko_patient['first_name'],
                "last_name": cliniko_patient['last_name'],
                "phone_number": patient_phone
            }
            logger.info(f"✓ Created patient ID: {patient['patient_id']}")
        else:
            logger.info(f"✓ Found existing patient: {patient['patient_id']}")

        # Match practitioner by name
        logger.info(f"Matching practitioner: '{practitioner_name}'")
        practitioner_result = await match_practitioner(clinic.clinic_id, practitioner_name, pool)
        
        if not practitioner_result.get("matches"):
            return create_error_response(
                error_code="practitioner_not_found",
                message=f"I couldn't find a practitioner named '{practitioner_name}'.",
                session_id=session_id
            )
        
        practitioner = practitioner_result["matches"][0]
        
        # Ensure full_name is available
        if 'full_name' not in practitioner and 'first_name' in practitioner and 'last_name' in practitioner:
            practitioner['full_name'] = f"{practitioner['first_name']} {practitioner['last_name']}"
        
        logger.info(f"✓ Matched practitioner: {practitioner['full_name']} (ID: {practitioner['practitioner_id']})")

        # Match service for this practitioner
        logger.info(f"Matching service: '{appointment_type}' for practitioner {practitioner['practitioner_id']}")
        service = await match_service(clinic.clinic_id, practitioner['practitioner_id'], appointment_type, pool)
        if not service:
            return {
                "success": False,
                "error": "service_not_found",
                "message": f"I couldn't find the service '{appointment_type}' for {practitioner['full_name']}",
                "sessionId": session_id
            }

        logger.info(f"✓ Matched service: {service['service_name']} (ID: {service['appointment_type_id']})")

        # Find business by business ID
        business = None
        for biz in clinic.businesses:
            if biz['business_id'] == business_id:
                business = biz
                break

        if not business:
            # Try database lookup
            query = \
                "SELECT business_id, business_name, is_primary FROM businesses WHERE business_id = $1 AND clinic_id = $2"
            async with pool.acquire() as conn:
                row = await conn.fetchrow(query, business_id, clinic.clinic_id)
                if row:
                    business = dict(row)

        if not business:
            return {
                "success": False,
                "error": "invalid_business_id",
                "message": "The business ID provided is not valid.",
                "sessionId": session_id
            }

        logger.info(f"✓ Found business: {business['business_name']} (ID: {business['business_id']})")

        # Parse date and time
        try:
            appointment_date = datetime.strptime(appointment_date_str, "%Y-%m-%d").date()
            time_parts = appointment_time_str.split(':')
            hour = int(time_parts[0])
            minute = int(time_parts[1]) if len(time_parts) > 1 else 0

            # Create datetime in clinic timezone
            clinic_tz = get_clinic_timezone(clinic)
            appointment_datetime = datetime.combine(
                appointment_date,
                datetime.min.time().replace(hour=hour, minute=minute),
                tzinfo=clinic_tz
            )
            appointment_datetime_utc = appointment_datetime.astimezone(timezone.utc)

            # Convert to UTC for Cliniko
            appointment_start_utc = appointment_datetime.astimezone(timezone.utc)
            appointment_end_utc = appointment_start_utc + timedelta(minutes=service['duration_minutes'])

        except ValueError as e:
            return {
                "success": False,
                "error": "invalid_datetime",
                "message": "Invalid date or time format. Please use YYYY-MM-DD for date and HH:MM for time.",
                "sessionId": session_id
            }

        # Create appointment data for Cliniko
        appointment_data = {
            "patient_id": patient['patient_id'],
            "practitioner_id": practitioner['practitioner_id'],
            "appointment_type_id": service['appointment_type_id'],
            "business_id": business['business_id'],
            "appointment_start": appointment_start_utc.isoformat().replace('+00:00', 'Z'),
            "appointment_end": appointment_end_utc.isoformat().replace('+00:00', 'Z')
        }

        if notes:
            appointment_data['notes'] = notes

        logger.info(f"Creating appointment with data: {appointment_data}")

        # Create the appointment in Cliniko
        appointment = await cliniko.create_appointment(appointment_data)

        logger.info(f"✓ Appointment created successfully! ID: {appointment['id']}")

        # Save to database
        await save_appointment_to_db({
            "appointment_id": str(appointment['id']),
            "clinic_id": clinic.clinic_id,
            "patient_id": patient['patient_id'],
            "practitioner_id": practitioner['practitioner_id'],
            "appointment_type_id": service['appointment_type_id'],
            "business_id": business['business_id'],
            "starts_at": appointment_start_utc,
            "ends_at": appointment_end_utc,
            "status": "booked",
            "notes": notes
        }, pool)

        # Log the booking
        await log_voice_booking({
            "appointment_id": str(appointment['id']),
            "clinic_id": clinic.clinic_id,
            "session_id": session_id,
            "caller_phone": caller_phone,
            "action": "book",
            "status": "completed"
        }, pool)

        # Invalidate availability cache
        await invalidate_practitioner_availability(
            practitioner['practitioner_id'],
            business['business_id'],
            appointment_date,
            pool
        )

        # Format confirmation message
        display_time = appointment_datetime.strftime("%I:%M %p").lstrip('0')
        display_date = appointment_date.strftime("%A, %B %d, %Y")

        # Create standardized response
        response = BookingResponse(
            success=True,
            sessionId=session_id,
            message = \
                "Perfect! I've successfully booked your {service['service_name']} appointment with {practitioner['full_name']} for {display_date} at {display_time} at our {business['business_name']}.",
            bookingId=str(appointment['id']),
            confirmationNumber=f"APT-{str(appointment['id'])[-6:]}",
            practitioner=PractitionerData(
                id=practitioner['practitioner_id'],
                name=practitioner['full_name'],
                firstName=practitioner.get('first_name', practitioner['full_name'].split()[0])
            ),
            service=ServiceData(
                id=service['appointment_type_id'],
                name=service['service_name'],
                duration=service['duration_minutes']
            ),
            location=LocationData(
                id=business['business_id'],
                name=business['business_name']
            ),
            timeSlot=TimeSlotData(
                date=appointment_date.isoformat(),
                time=display_time,
                displayTime=display_time
            ),
            patientName=patient_name
        )

        return response.dict()

    except httpx.HTTPStatusError as e:
        # Check if it's a "slot taken" error
        error_text = str(e.response.text).lower()
        if e.response.status_code == 422 and "already booked" in error_text:
            # Invalidate the cache for this specific date to force a refresh
            await cache.invalidate_availability(
                practitioner['practitioner_id'],
                business['business_id'],
                appointment_date
            )
            # Optional: Add a temporary block for this specific slot
            # This prevents it from being offered again immediately
            async with pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO failed_booking_attempts
                    (clinic_id, practitioner_id, business_id, appointment_date, appointment_time, failure_reason)
                    VALUES ($1, $2, $3, $4, $5, 'slot_taken')
                    ON CONFLICT DO NOTHING
                """, clinic.clinic_id, practitioner['practitioner_id'], business['business_id'], appointment_date, appointment_time_str)
        return await handle_appointment_creation_api_error(
            e,
            appointment_data,
            BaseRequest(
                sessionId=body.get('sessionId', 'unknown'),
                callerPhone=body.get('callerPhone'),
                dialedNumber=body.get('dialedNumber'),
                timestamp=datetime.now()
            )
        )

    except Exception as e:
        logger.error(f"Appointment handler error: {str(e)}", exc_info=True)
        return {
            "success": False,
            "error": "booking_failed",
            "message": "I'm sorry, I encountered an error while booking your appointment. Please try again or contact the clinic directly.",
            "sessionId": body.get('sessionId', 'unknown')
        }

async def handle_booking(request: BookingRequest, background_tasks: BackgroundTasks) -> Dict[str, Any]:
    """Handle new appointment booking with clean error handling"""
    clinic = None

    try:
        # Get database pool and cache
        pool = await get_db()
        cache = await get_cache()

        # Get clinic information
        clinic = await get_clinic_by_dialed_number(request.dialedNumber, pool)
        if not clinic:
            return await handle_clinic_not_found(request)
        # Trigger background sync if needed
        background_tasks.add_task(
            check_and_trigger_sync,
            clinic.clinic_id,
            pool,
            cache,
            clinic.cliniko_api_key,
            clinic.cliniko_shard
        )

        # Validate clinic timezone
        clinic_tz = get_clinic_timezone(clinic)

        logger.info(f"✓ Found clinic: {clinic.clinic_name} (ID: {clinic.clinic_id})")

        # Initialize clinic timezone
        clinic_tz = get_clinic_timezone(clinic)

        # Initialize Cliniko API
        cliniko = ClinikoAPI(
            clinic.cliniko_api_key,
            clinic.cliniko_shard,
            clinic.contact_email
        )

        # Validate required fields
        missing_fields = validate_booking_request(request)
        if missing_fields:
            return await handle_missing_information(missing_fields, request)

        # Find or create patient (with caching)
        patient_phone = request.patientPhone or request.callerPhone
        logger.info(f"Looking for patient with phone: {patient_phone}")

        # Validate phone number format - Australian mobile (04) or landline (02, 03, 07, 08)
        if not patient_phone or len(patient_phone) != 10:
            return create_error_response(
                error_code="invalid_phone_number",
                message="Please provide a valid 10-digit Australian phone number.",
                session_id=request.sessionId
            )

        # Check if it's a valid Australian phone prefix
        valid_prefixes = ['02', '03', '04', '07', '08']
        if not any(patient_phone.startswith(prefix) for prefix in valid_prefixes):
            return create_error_response(
                error_code="invalid_phone_number",
                message="Please provide a valid Australian phone number starting with 02, 03, 04, 07, or 08.",
                session_id=request.sessionId
            )

        # Use cached patient lookup
        patient = await find_patient_with_cache(
            clinic.clinic_id,
            patient_phone,
            pool,
            cache,
            cliniko
        )

        if not patient:
            logger.info("Patient not found in cache or database, creating new...")
            # Validate phone before creating patient
            if len(patient_phone) != 10:
                return create_error_response(
                    error_code="invalid_phone_number",
                    message = \
                        "Cannot create patient with invalid phone number. Please provide a valid 10-digit Australian phone number.",
                    session_id=request.sessionId
                )
            name_parts = request.patientName.split(' ', 1)
            patient_data = {
                "first_name": name_parts[0],
                "last_name": name_parts[1] if len(name_parts) > 1 else "Patient",
                "phone": patient_phone
            }
            cliniko_patient = await cliniko.create_patient(patient_data)
            logger.info(f"✓ Created patient ID: {cliniko_patient['id']}")
            patient = {
                "patient_id": str(cliniko_patient['id']),
                "first_name": cliniko_patient['first_name'],
                "last_name": cliniko_patient['last_name'],
                "phone_number": patient_phone
            }
        else:
            logger.info(f"✓ Found patient: {patient['first_name']} {patient['last_name']} (ID: {patient['patient_id']})")

        # Match practitioner
        logger.info(f"Matching practitioner: '{request.practitioner}'")
        practitioner_result = await match_practitioner(clinic.clinic_id, request.practitioner, pool)
        if practitioner_result.get("needs_clarification"):
            return {
                "success": False,
                "needs_clarification": True,
                "message": practitioner_result["message"],
                "options": practitioner_result["clarification_options"],
                "sessionId": request.sessionId
            }
        if not practitioner_result or not practitioner_result.get("matches"):
            services = await get_practitioner_services(clinic.clinic_id, pool)
            available_practitioners = list(set(s['practitioner_name'] for s in services))
            return await handle_practitioner_not_found(
                request.practitioner,
                available_practitioners,
                request
            )
        practitioner = practitioner_result["matches"][0]
        
        # Ensure full_name is available
        if 'full_name' not in practitioner and 'first_name' in practitioner and 'last_name' in practitioner:
            practitioner['full_name'] = f"{practitioner['first_name']} {practitioner['last_name']}"
        
        logger.info(f"✓ Matched practitioner: {practitioner['full_name']} (ID: {practitioner['practitioner_id']})")

        # Match service
        logger.info(f"Matching service: '{request.appointmentType}' for practitioner {practitioner['practitioner_id']}")
        service = await match_service(clinic.clinic_id, practitioner['practitioner_id'], request.appointmentType, pool)
        if not service:
            return await handle_service_not_found(
                request.appointmentType,
                practitioner['full_name'],
                request
            )

        logger.info(f"✓ Matched service: {service['service_name']} (ID: {service['appointment_type_id']})")

        # Match business/location - HANDLE PRE-RESOLVED LOCATION
        business = None

        # If business_id provided, use it directly (already resolved by ElevenLabs)
        if hasattr(request, 'business_id') and request.business_id:
            logger.info("=== PRE-RESOLVED LOCATION DEBUG ===")
            logger.info(f"Session: {request.sessionId}")
            logger.info(f"Using pre-resolved business_id: {request.business_id}")
            logger.info(f"Available clinic businesses: {[biz['business_id'] for biz in clinic.businesses]}")

            # Find business by ID
            for biz in clinic.businesses:
                if biz['business_id'] == request.business_id:
                    business = biz
                    logger.info(f"✓ Found business in clinic.businesses: {biz['business_name']} ({biz['business_id']})")
                    break

            if not business:
                logger.info(f"business_id {request.business_id} not found in clinic.businesses, checking database...")
                # Try to fetch from database
                query = \
                    "SELECT business_id, business_name, is_primary FROM businesses WHERE business_id = $1 AND clinic_id = $2"
                async with pool.acquire() as conn:
                    row = await conn.fetchrow(query, request.business_id, clinic.clinic_id)
                    if row:
                        business = dict(row)
                        logger.info(f"✓ Found business in database: {business['business_name']} ({business['business_id']})")
                    else:
                        logger.warning(f"business_id {request.business_id} not found in database for clinic {clinic.clinic_id}")

            if not business:
                logger.error(f"Invalid business_id: {request.business_id} for clinic: {clinic.clinic_id}")
                return create_error_response(
                    error_code="invalid_business_id",
                    message="The business ID provided is not valid for this clinic.",
                    session_id=request.sessionId
                )

            logger.info("=== END PRE-RESOLVED LOCATION DEBUG ===")

        # Otherwise, try to match by location text (EXISTING CODE)
        elif request.location:
            logger.info(f"Matching business by text: '{request.location}'")
            business = await match_business(clinic.clinic_id, request.location, pool)
        else:
            logger.info("No business_id or location text provided - will use default business")

        # Use default if still no business
        if not business and clinic.businesses:
            business = clinic.businesses[0]
            logger.info(f"Using default business: {business}")

        if not business:
            return create_error_response(
                error_code="no_location",
                message="No business location found for this clinic.",
                session_id=request.sessionId
            )

        logger.info(f"✓ Using business: {business['business_name']} (ID: {business['business_id']})")

        # Pre-check practitioner-location compatibility
        location_check = await check_practitioner_location_compatibility(
            practitioner['practitioner_id'],
            business['business_id'],
            clinic.clinic_id,
            pool
        )

        if not location_check:
            # Practitioner doesn't work at this location
            return create_error_response(
                error_code="practitioner_location_mismatch",
                message=f"{practitioner['full_name']} doesn't work at {business['business_name']}. Please choose a different location.",
                session_id=request.sessionId
            )

        # Parse date and time
        clinic_tz = get_clinic_timezone(clinic)
        appointment_date = parse_date_request(request.appointmentDate or "tomorrow", clinic_tz)
        hour, minute = parse_time_request(request.appointmentTime or "10:00am")
        logger.info(f"Parsed date/time: {appointment_date} at {hour}:{minute:02d}")

        # Create datetime in clinic timezone
        clinic_tz = get_clinic_timezone(clinic)
        appointment_datetime = datetime.combine(
            appointment_date,
            datetime.min.time().replace(hour=hour, minute=minute),
            tzinfo=clinic_tz
        )
        appointment_datetime_utc = appointment_datetime.astimezone(timezone.utc)

        # CRITICAL FIX: Ensure we query for the correct date range
        # Cliniko expects dates in YYYY-MM-DD format and interprets them in the clinic's timezone
        # We need to ensure we're querying for slots on the correct date

        # For Sydney timezone (UTC+10/+11), we need to be careful about date boundaries
        # If we want slots for July 7th Sydney time, we need to query July 7th
        from_date = appointment_date.isoformat()
        to_date = appointment_date.isoformat()  # SAME DATE - fixes timezone boundary issue

        logger.info("Getting available times for:")
        logger.info(f"  Business: {business['business_id']}")
        logger.info(f"  Practitioner: {practitioner['practitioner_id']}")
        logger.info(f"  Service: {service['appointment_type_id']}")
        logger.info(f"  Date: {from_date} (single day query)")

        available_times = await cliniko.get_available_times(
            business['business_id'],
            practitioner['practitioner_id'],
            service['appointment_type_id'],
            from_date,
            to_date  # Same as from_date for single day query
        )

        logger.info(f"Available times response: {len(available_times)} slots")

        # If no slots found, search up to 14 days ahead at the same location/practitioner/service
        if not available_times:
            logger.info(f"No slots found for {practitioner['full_name']} at {business['business_name']} on {appointment_date}, searching next 14 days...")
            for offset in range(1, 15):
                next_date = appointment_date + timedelta(days=offset)
                next_from_date = next_date.isoformat()
                next_to_date = next_date.isoformat()
                next_slots = await cliniko.get_available_times(
                    business['business_id'],
                    practitioner['practitioner_id'],
                    service['appointment_type_id'],
                    next_from_date,
                    next_to_date
                )
                if next_slots:
                    logger.info(f"Found next available slot for {practitioner['full_name']} at {business['business_name']} on {next_date}: {next_slots[0]}")
                    available_times = next_slots
                    appointment_date = next_date
                    break

        # Ensure practitioner_name is always defined for fallback
        practitioner_name = practitioner.get('full_name') if isinstance(practitioner, dict) and 'full_name' in practitioner else str(practitioner)
        
        if not available_times:
            # --- SUPABASE-ONLY FALLBACK ---
            cached_slots = await cache.get_availability(
                practitioner['practitioner_id'],
                business['business_id'],
                appointment_date
            )
            if cached_slots:
                logger.warning(f"[SUPABASE-ONLY FALLBACK] Returning {len(cached_slots)} slots from cache for practitioner {practitioner['practitioner_id']} at business {business['business_id']} on {appointment_date}")
                available_times_local = []
                for slot in cached_slots:
                    slot_utc = parse_cliniko_time(slot.get('appointment_start') or slot.get('start', ''))
                    slot_local = slot_utc.astimezone(clinic_tz)
                    if slot_local.date() == appointment_date:
                        available_times_local.append(format_time_for_voice(slot_local))
                display_time = format_time_for_voice(
                    datetime.combine(appointment_date, datetime.min.time().replace(hour=hour, minute=minute))
                )
                display_date = appointment_date.strftime('%A, %B %d, %Y')
                if available_times_local:
                    return {
                        "success": False,
                        "error": "time_not_available",
                        "message": f"[From local system] I'm sorry, {display_time} is not available on {display_date}. {practitioner_name} has these times available: {', '.join(available_times_local)}. (Note: These may be slightly out of date.) Which time would you prefer?",
                        "sessionId": request.sessionId,
                        "availableTimes": available_times_local
                    }
            # Ensure practitioner is a dict, not a result dict
            practitioner_name = \
                practitioner['full_name'] if isinstance(practitioner, dict) and 'full_name' in practitioner else str(practitioner)
            return await handle_no_availability(
                request,
                appointment_date.strftime('%A, %B %d, %Y'),
                practitioner_name
            )

        # Find exact matching time slot
        logger.info(f"Looking for exact time slot: {appointment_date} at {hour}:{minute:02d} Sydney time")
        logger.info("Available slots (showing first 3):")
        for i, slot in enumerate(available_times[:3]):
            slot_utc = datetime.fromisoformat(slot['appointment_start'].replace('Z', '+00:00'))
            slot_local = slot_utc.astimezone(clinic_tz)
            logger.info(f"  Slot {i+1}: UTC: {slot['appointment_start']} -> Local: {slot_local.strftime('%Y-%m-%d %H:%M')}")

        exact_slot = None
        for slot in available_times:
            slot_utc = parse_cliniko_time(slot.get('appointment_start') or slot.get('start', ''))
            # Compare timestamps for exact match (handles DST changes correctly)
            if abs((slot_utc - appointment_datetime_utc).total_seconds()) < 60:  # Within 1 minute
                exact_slot = slot
                logger.info(f"Found matching slot: {slot_utc.isoformat()}")
                break

        if not exact_slot:
            # --- SUPABASE-ONLY FALLBACK (for exact slot) ---
            cached_slots = await cache.get_availability(
                practitioner['practitioner_id'],
                business['business_id'],
                appointment_date
            )
            if cached_slots:
                logger.warning(f"[SUPABASE-ONLY FALLBACK] Returning {len(cached_slots)} slots from cache for practitioner {practitioner['practitioner_id']} at business {business['business_id']} on {appointment_date}")
                available_times_local = []
                for slot in cached_slots:
                    slot_utc = parse_cliniko_time(slot.get('appointment_start') or slot.get('start', ''))
                    slot_local = slot_utc.astimezone(clinic_tz)
                    if slot_local.date() == appointment_date:
                        available_times_local.append(format_time_for_voice(slot_local))
                display_time = format_time_for_voice(
                    datetime.combine(appointment_date, datetime.min.time().replace(hour=hour, minute=minute))
                )
                display_date = appointment_date.strftime('%A, %B %d, %Y')
                if available_times_local:
                    return {
                        "success": False,
                        "error": "time_not_available",
                        "message": f"[From local system] I'm sorry, {display_time} is not available on {display_date}. {practitioner_name} has these times available: {', '.join(available_times_local)}. (Note: These may be slightly out of date.) Which time would you prefer?",
                        "sessionId": request.sessionId,
                        "availableTimes": available_times_local
                    }
            # Log why no match was found
            logger.warning(f"No exact slot match found for {appointment_datetime_utc.isoformat()}")
            logger.warning("Available slots (first 5):")
            for i, slot in enumerate(available_times[:5]):
                slot_str = slot.get('appointment_start', slot.get('start', ''))
                logger.warning(f"  Slot {i+1}: {slot_str}")

        if not exact_slot:
            # Get a few available times to offer
            available_times_local = []
            for slot in available_times[:5]:  # Show up to 5 options
                slot_utc = parse_cliniko_time(slot.get('appointment_start') or slot.get('start', ''))
                slot_local = slot_utc.astimezone(clinic_tz)
                if slot_local.date() == appointment_date:
                    available_times_local.append(format_time_for_voice(slot_local))

            display_time = format_time_for_voice(
                datetime.combine(appointment_date, datetime.min.time().replace(hour=hour, minute=minute))
            )
            display_date = appointment_date.strftime('%A, %B %d, %Y')

            if available_times_local:
                return {
                    "success": False,
                    "error": "time_not_available",
                    "message": "I'm sorry, {display_time} is not available on {display_date}. "
                              f"{practitioner_name} has these times available: {', '.join(available_times_local)}. "
                              "Which time would you prefer?",
                    "sessionId": request.sessionId,
                    "availableTimes": available_times_local
                }
            else:
                return await handle_no_availability(
                    request,
                    appointment_date.strftime('%A, %B %d, %Y'),
                    practitioner_name
                )

        # Use exact slot
        best_slot = exact_slot
        logger.info(f"Found exact matching slot: {best_slot['appointment_start']}")

        # Create appointment
        start_time = datetime.fromisoformat(best_slot['appointment_start'].replace('Z', '+00:00'))
        end_time = start_time + timedelta(minutes=service['duration_minutes'])

        appointment_data = {
            "patient_id": patient['patient_id'],
            "practitioner_id": practitioner['practitioner_id'],
            "appointment_type_id": service['appointment_type_id'],
            "business_id": business['business_id'],
            "appointment_start": best_slot['appointment_start'],
            "appointment_end": end_time.isoformat().replace('+00:00', 'Z')
        }

        if request.notes:
            appointment_data['notes'] = request.notes

        logger.info(f"Creating appointment with data: {appointment_data}")

        appointment = await cliniko.create_appointment(appointment_data)

        logger.info(f"✓ Appointment created successfully! ID: {appointment['id']}")

        # Save to database
        await save_appointment_to_db({
            "appointment_id": str(appointment['id']),
            "clinic_id": clinic.clinic_id,
            "patient_id": patient['patient_id'],
            "practitioner_id": practitioner['practitioner_id'],
            "appointment_type_id": service['appointment_type_id'],
            "business_id": business['business_id'],
            "starts_at": start_time,
            "ends_at": end_time,
            "status": "booked",
            "notes": request.notes
        }, pool)

        # Log the booking
        await log_voice_booking({
            "appointment_id": str(appointment['id']),
            "clinic_id": clinic.clinic_id,
            "session_id": request.sessionId,
            "caller_phone": request.callerPhone,
            "action": "book",
            "status": "completed"
        }, pool)

        # Invalidate cache
        await invalidate_practitioner_availability(
            practitioner['practitioner_id'],
            business['business_id'],
            appointment_date,
            pool
        )

        # Format response
        start_time_local = convert_utc_to_local(best_slot['appointment_start'], clinic_tz)
        display_time = format_time_for_voice(start_time_local)
        display_date = appointment_date.strftime("%A, %B %d, %Y")

        return {
            "success": True,
            "message": "Perfect! I've successfully booked your {service['service_name']} appointment with {practitioner['full_name']} for {display_date} at {display_time}.",
            "appointmentDetails": {
                "appointmentId": str(appointment['id']),
                "practitioner": practitioner['full_name'],
                "service": service['service_name'],
                "duration": f"{service['duration_minutes']} minutes",
                "date": display_date,
                "time": display_time,
                "location": business['business_name'],
                "patient": f"{patient['first_name']} {patient['last_name']}"
            },
            "sessionId": request.sessionId
        }

    except httpx.HTTPStatusError as e:
        # Check if it's a "slot taken" error
        error_text = str(e.response.text).lower()
        if e.response.status_code == 422 and "already booked" in error_text:
            # Invalidate the cache for this specific date to force a refresh
            await cache.invalidate_availability(
                practitioner['practitioner_id'],
                business['business_id'],
                appointment_date
            )
            # Optional: Add a temporary block for this specific slot
            # This prevents it from being offered again immediately
            async with pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO failed_booking_attempts
                    (clinic_id, practitioner_id, business_id, appointment_date, appointment_time, failure_reason)
                    VALUES ($1, $2, $3, $4, $5, 'slot_taken')
                    ON CONFLICT DO NOTHING
                """, clinic.clinic_id, practitioner['practitioner_id'], business['business_id'], appointment_date, request.appointmentTime)
        return await handle_appointment_creation_api_error(
            e,
            appointment_data,
            BaseRequest(
                sessionId=request.sessionId,
                callerPhone=request.callerPhone,
                dialedNumber=request.dialedNumber,
                timestamp=datetime.now()
            )
        )

    except Exception as e:
        pool = await get_db()
        return await handle_booking_error(
            e,
            request,
            clinic.clinic_id if clinic else None,
            {'db_pool': pool}
        )

async def handle_reschedule(request: RescheduleRequest) -> Dict[str, Any]:
    """Handle appointment rescheduling with proper timezone handling"""
    clinic = None

    try:
        # Get database pool and cache
        pool = await get_db()
        cache = await get_cache()

        # Get clinic information
        clinic = await get_clinic_by_dialed_number(request.dialedNumber, pool)
        if not clinic:
            return await handle_clinic_not_found(request)

        # Validate clinic timezone
        clinic_tz = get_clinic_timezone(clinic)

        logger.info(f"✓ Found clinic: {clinic.clinic_name}")

        # Initialize Cliniko API
        cliniko = ClinikoAPI(
            clinic.cliniko_api_key,
            clinic.cliniko_shard,
            clinic.contact_email
        )

        # Find the appointment to reschedule
        if not request.appointmentId:
            # Try to find by description
            details = request.currentAppointmentDetails or request.notes or ""
            found_appointment = await find_appointment_by_details(
                clinic_id=clinic.clinic_id,
                caller_phone=request.callerPhone,
                details=details,
                pool=pool
            )

            if not found_appointment:
                return create_error_response(
                    error_code="appointment_not_found",
                    message = \
                        "I couldn't find your appointment. Could you provide more details like the practitioner's name or the current appointment time?",
                    session_id=request.sessionId
                )

            request.appointmentId = found_appointment['appointment_id']
            logger.info(f"Found appointment to reschedule: {request.appointmentId}")

        # Get current appointment details from Cliniko
        logger.info(f"Fetching appointment {request.appointmentId} from Cliniko")
        current_appointment = await cliniko.get_appointment(request.appointmentId)
        if not current_appointment:
            return create_error_response(
                error_code="appointment_not_found",
                message="I couldn't find that appointment in the system.",
                session_id=request.sessionId
            )

        # Extract current appointment details
        current_practitioner_id = \
            str(current_appointment.get('practitioner', {}).get('links', {}).get('sel', '').split('/')[-1])
        current_appointment_type_id = \
            str(current_appointment.get('appointment_type', {}).get('links', {}).get('sel', '').split('/')[-1])
        current_business_id = \
            str(current_appointment.get('business', {}).get('links', {}).get('sel', '').split('/')[-1])
        current_patient_id = str(current_appointment.get('patient', {}).get('links', {}).get('sel', '').split('/')[-1])

        # Initialize variables that might be used in error handlers
        clinic_tz = get_clinic_timezone(clinic)
        new_date = parse_date_request(request.newDate or "tomorrow", clinic_tz)
        new_practitioner_id = current_practitioner_id
        new_appointment_type_id = current_appointment_type_id
        new_business_id = current_business_id
        try:
            # If changing practitioner
            if request.newPractitioner:
                practitioner_result = await match_practitioner(clinic.clinic_id, request.newPractitioner, pool)
                if not practitioner_result or not practitioner_result.get("matches"):
                                    return create_error_response(
                    error_code="practitioner_not_found",
                    message=f"I couldn't find a practitioner named {request.newPractitioner}.",
                    session_id=request.sessionId
                )
                practitioner = practitioner_result["matches"][0]
                new_practitioner_id = practitioner['practitioner_id']
                logger.info(f"Changing practitioner to: {practitioner['full_name']}")

            # If changing appointment type
            if request.newAppointmentType:
                service = await match_service(clinic.clinic_id, new_practitioner_id, request.newAppointmentType, pool)
                if not service:
                                    return create_error_response(
                    error_code="service_not_found",
                    message=f"I couldn't find the service '{request.newAppointmentType}'.",
                    session_id=request.sessionId
                )
                new_appointment_type_id = service['appointment_type_id']
                logger.info(f"Changing service to: {service['service_name']}")

            # Parse new date and time
            hour, minute = parse_time_request(request.newTime or "10:00am")

            logger.info(f"Rescheduling to: {new_date} at {hour:02d}:{minute:02d}")

            # Create datetime in clinic timezone
            new_datetime_local = datetime.combine(
                new_date,
                datetime.min.time().replace(hour=hour, minute=minute),
                tzinfo=clinic_tz
            )
            new_datetime_utc = new_datetime_local.astimezone(timezone.utc)

            # FIX 2: Use single-day query for availability
            from_date = new_date.isoformat()
            to_date = new_date.isoformat()  # SAME DATE - fixes timezone boundary issue

            logger.info(f"Checking availability for {from_date} (single day query)")

            # Check availability for the new time
            available_times = await cliniko.get_available_times(
                new_business_id,
                new_practitioner_id,
                new_appointment_type_id,
                from_date,
                to_date
            )

            if not available_times:
                return create_error_response(
                    error_code="no_availability",
                    message = \
                        "I'm sorry, there are no available times on {new_date.strftime('%A, %B %d, %Y')}. Would you like to try another date?",
                    session_id=request.sessionId
                )

            logger.info(f"Found {len(available_times)} available slots")

            # Find exact matching time slot
            exact_slot = None

            for slot in available_times:
                slot_utc = parse_cliniko_time(slot.get('appointment_start') or slot.get('start', ''))

                # Compare timestamps for exact match (handles DST changes correctly)
                if abs((slot_utc - new_datetime_utc).total_seconds()) < 60:  # Within 1 minute
                    exact_slot = slot
                    logger.info(f"Found matching slot: {slot_utc.isoformat()}")
                    break

            if not exact_slot:
                # Log available slots for debugging
                logger.warning(f"No exact match found for {new_datetime_utc.isoformat()}")

                # Get available times to offer
                available_times_local = []
                for slot in available_times[:5]:  # Show up to 5 options
                    slot_utc = parse_cliniko_time(slot.get('appointment_start', slot.get('start', '')))
                    slot_local = slot_utc.astimezone(clinic_tz)
                    if slot_local.date() == new_date:
                        available_times_local.append(format_time_for_voice(slot_local))

                display_time = format_time_for_voice(new_datetime_local)

                if available_times_local:
                    return create_error_response(
                        error_code="time_not_available",
                        message=f"I'm sorry, {display_time} is not available on {new_date.strftime('%A, %B %d, %Y')}. "
                                f"Available times are: {', '.join(available_times_local)}. Which would you prefer?",
                        session_id=request.sessionId,
                        availableTimes=available_times_local
                    )
                else:
                    return create_error_response(
                        error_code="no_availability",
                        message = f"I'm sorry, there are no available times on {new_date.strftime('%A, %B %d, %Y')}. Would you like to try another date?",
                        session_id=request.sessionId
                    )

            # Get appointment duration (from service or current appointment)
            duration_minutes = 30  # Default
            if 'service' in locals() and service:
                duration_minutes = service.get('duration_minutes', 30)
            elif current_appointment.get('duration_in_minutes'):
                duration_minutes = current_appointment['duration_in_minutes']

            # Calculate end time
            start_time_utc = datetime.fromisoformat(exact_slot['appointment_start'].replace('Z', '+00:00'))
            end_time_utc = start_time_utc + timedelta(minutes=duration_minutes)

            # Prepare new appointment data
            new_appointment_data = {
                "patient_id": current_patient_id,
                "practitioner_id": new_practitioner_id,
                "appointment_type_id": new_appointment_type_id,
                "business_id": new_business_id,
                "appointment_start": exact_slot['appointment_start'],
                "appointment_end": end_time_utc.isoformat().replace('+00:00', 'Z')
            }

            # Add notes if provided
            notes = request.notes or f"Rescheduled from appointment {request.appointmentId}"
            new_appointment_data['notes'] = notes

            logger.info(f"Creating new appointment with data: {new_appointment_data}")

            try:
                # Create the new appointment first
                new_appointment = await cliniko.create_appointment(new_appointment_data)
                logger.info(f"✓ New appointment created: {new_appointment['id']}")

                # Only cancel the old appointment after successful creation
                logger.info(f"Cancelling old appointment: {request.appointmentId}")
                cancel_success = await cliniko.cancel_appointment(request.appointmentId)

                if not cancel_success:
                    logger.warning(f"Failed to cancel old appointment {request.appointmentId},\
                        but new appointment was created")
            except httpx.HTTPStatusError as e:
                # Check if it's a "slot taken" error
                error_text = str(e.response.text).lower()
                if e.response.status_code == 422 and "already booked" in error_text:
                    # Invalidate cache for this specific slot
                    try:
                        await cache.invalidate_availability(
                            new_practitioner_id,
                            new_business_id,
                            new_date
                        )
                    except Exception as cache_error:
                        logger.warning(f"Failed to invalidate cache: {cache_error}")
                    return create_error_response(
                        error_code="slot_no_longer_available",
                        message = \
                            "I'm sorry, that time slot was just booked by someone else. Please choose another time.",
                        session_id=request.sessionId
                    )

                # Other API errors
                return await handle_appointment_creation_api_error(
                    e,
                    new_appointment_data,
                    request
                )

            # Update database records
            await update_appointment_status(request.appointmentId, 'cancelled', pool)

            await save_appointment_to_db({
                "appointment_id": str(new_appointment['id']),
                "clinic_id": clinic.clinic_id,
                "patient_id": current_patient_id,
                "practitioner_id": new_practitioner_id,
                "appointment_type_id": new_appointment_type_id,
                "business_id": new_business_id,
                "starts_at": start_time_utc,
                "ends_at": end_time_utc,
                "status": "booked",
                "notes": notes
            }, pool)

            # Log the reschedule
            await log_voice_booking({
                "appointment_id": str(new_appointment['id']),
                "clinic_id": clinic.clinic_id,
                "session_id": request.sessionId,
                "caller_phone": request.callerPhone,
                "action": "reschedule",
                "status": "completed"
            }, pool)

            # Invalidate cache for both dates
            await invalidate_practitioner_availability(
                current_practitioner_id,
                current_business_id,
                datetime.fromisoformat(current_appointment['appointment_start'].replace('Z', '+00:00')).date(),
                pool
            )

            await invalidate_practitioner_availability(
                new_practitioner_id,
                new_business_id,
                new_date,
                pool
            )

            # Get practitioner name for response
            practitioner_name = "your practitioner"
            if new_practitioner_id:
                query = """
                    SELECT CONCAT(
                        CASE WHEN title IS NOT NULL AND title != '' THEN title || ' ' ELSE '' END,
                        first_name, ' ', last_name
                    ) as full_name
                    FROM practitioners
                    WHERE practitioner_id = $1
                """
                async with pool.acquire() as conn:
                    row = await conn.fetchrow(query, new_practitioner_id)
                    if row:
                        practitioner_name = row['full_name']

            # Format response
            start_time_local = convert_utc_to_local(exact_slot['appointment_start'], clinic_tz)
            display_time = format_time_for_voice(start_time_local)
            display_date = new_date.strftime("%A, %B %d, %Y")

            # Build confirmation message
            message = "Perfect! I've successfully rescheduled your appointment"

            # Add details about what changed
            changes = []
            if request.newDate or request.newTime:
                changes.append(f"to {display_date} at {display_time}")
            if request.newPractitioner:
                changes.append(f"with {practitioner_name}")
            if request.newAppointmentType and 'service' in locals():
                changes.append(f"for {service['service_name']}")

            if changes:
                message += " " + ", ".join(changes)

            message += "."

            return {
                "success": True,
                "message": message,
                "appointmentDetails": {
                    "appointmentId": str(new_appointment['id']),
                    "oldAppointmentId": request.appointmentId,
                    "practitioner": practitioner_name,
                    "date": display_date,
                    "time": display_time,
                    "confirmationNumber": str(new_appointment['id'])
                },
                "sessionId": request.sessionId
            }

        except Exception as e:
            logger.error(f"Reschedule error: {str(e)}", exc_info=True)
            pool = await get_db()

            # Log the failed reschedule attempt
            if clinic:
                await log_voice_booking({
                    "appointment_id": request.appointmentId,
                    "clinic_id": clinic.clinic_id,
                    "session_id": request.sessionId,
                    "caller_phone": request.callerPhone,
                    "action": "reschedule",
                    "status": "failed",
                    "error_message": str(e)[:500]  # Truncate error message
                }, pool)

            return create_error_response(
                error_code="reschedule_failed",
                message = \
                    "I'm sorry, I encountered an error while rescheduling your appointment. Please try again or contact the clinic directly.",
                session_id=request.sessionId
            )

    except Exception as e:
        logger.error(f"Reschedule error: {str(e)}", exc_info=True)
        pool = await get_db()

        # Log the failed reschedule attempt
        if clinic:
            await log_voice_booking({
                "appointment_id": request.appointmentId,
                "clinic_id": clinic.clinic_id,
                "session_id": request.sessionId,
                "caller_phone": request.callerPhone,
                "action": "reschedule",
                "status": "failed",
                "error_message": str(e)[:500]  # Truncate error message
            }, pool)

        return create_error_response(
            error_code="reschedule_failed",
            message = \
                "I'm sorry, I encountered an error while rescheduling your appointment. Please try again or contact the clinic directly.",
            session_id=request.sessionId
        )

async def handle_modify(request: BookingRequest) -> Dict[str, Any]:
    """Handle appointment modification"""
    try:
        # Get database pool
        pool = await get_db()

        # Get clinic information
        clinic = await get_clinic_by_dialed_number(request.dialedNumber, pool)
        if not clinic:
            return await handle_clinic_not_found(request)

        return create_error_response(
            error_code="modify_not_implemented",
            message = \
                "To change your appointment type, I'll need to reschedule your appointment. Please say 'reschedule' and provide the new details.",
            session_id=request.sessionId
        )

    except Exception as e:
        logger.error(f"Modify error: {str(e)}", exc_info=True)
        return create_error_response(
            error_code="modify_failed",
            message="I'm sorry, I encountered an error while modifying your appointment.",
            session_id=request.sessionId
        )

@router.post("/cancel-appointment")
async def cancel_appointment(
    request: CancelRequest,
    authenticated: bool = Depends(verify_api_key)
) -> Dict[str, Any]:
    """Cancel an appointment with clean error handling"""
    payload_logger.log_payload("/cancel-appointment", request.model_dump())
    clinic = None

    try:
        # Get database pool
        pool = await get_db()

        # Get clinic information
        clinic = await get_clinic_by_dialed_number(request.dialedNumber, pool)
        if not clinic:
            return await handle_clinic_not_found(request)

        # Initialize Cliniko API
        cliniko = ClinikoAPI(
            clinic.cliniko_api_key,
            clinic.cliniko_shard,
            clinic.contact_email
        )

        # Find appointment if no ID provided
        if not request.appointmentId and request.appointmentDetails:
            logger.info(f"Searching for appointment with details: {request.appointmentDetails}")

            found_appointment = await find_appointment_by_details(
                clinic_id=clinic.clinic_id,
                caller_phone=request.callerPhone,
                details=request.appointmentDetails,
                pool=pool
            )

            if not found_appointment:
                return create_error_response(
                    error_code="appointment_not_found",
                    message = \
                        "I couldn't find your appointment. Could you provide more details like the practitioner's name or the appointment time?",
                    session_id=request.sessionId
                )

            # Format confirmation message
            appointment_time = datetime.fromisoformat(found_appointment['starts_at'].isoformat())
            appointment_time_local = convert_utc_to_local(appointment_time.isoformat(), get_clinic_timezone(clinic))

            confirm_message = (
                f"I found your {found_appointment['service_name']} appointment "
                f"with {found_appointment['practitioner_name']} on "
                f"{appointment_time_local.strftime('%A, %B %d at %I:%M %p').replace(' 0', ' ')}. "
                "Your appointment has been successfully cancelled."
            )

            request.appointmentId = found_appointment['appointment_id']
            logger.info(f"Found appointment ID: {request.appointmentId}")

        # Cancel in Cliniko
        if request.appointmentId:
            success = await cliniko.cancel_appointment(request.appointmentId)

            if success:
                # Update database
                await update_appointment_status(request.appointmentId, 'cancelled', pool)

                # Log the cancellation
                await log_voice_booking({
                    "appointment_id": request.appointmentId,
                    "clinic_id": clinic.clinic_id,
                    "session_id": request.sessionId,
                    "caller_phone": request.callerPhone,
                    "action": "cancel",
                    "status": "completed"
                }, pool)

                return {
                    "success": True,
                    "message": confirm_message if 'confirm_message' in locals() else "Your appointment has been successfully cancelled.",\
                                            "sessionId": request.sessionId
                }
            else:
                return create_error_response(
                    error_code="cancellation_failed",
                    message = \
                        "I wasn't able to cancel that appointment. It may have already been cancelled or completed.",
                    session_id=request.sessionId
                )

        return create_error_response(
            error_code="appointment_not_found",
            message = \
                "I need more information to find your appointment. Please provide details like the practitioner's name, date, or time.",
            session_id=request.sessionId
        )

    except Exception as e:
        return await handle_cancellation_error(
            e,
            request,
            clinic.clinic_id if clinic else None
        )
