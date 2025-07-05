# error_handlers.py
"""
Centralized error handling module for the Voice Booking System.
All error responses maintain consistent format for the voice agent.
"""

import logging
import httpx
import asyncpg
from typing import Dict, Any, Optional, List
from datetime import datetime
from database import get_practitioner_services, log_voice_booking
from models import BaseRequest, create_error_response

logger = logging.getLogger(__name__)

# === Standard Error Response Builder ===
def create_error_response(
    error_code: str,
    message: str,
    session_id: str,
    additional_fields: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Create a standardized error response"""
    response = {
        "success": False,
        "error": error_code,
        "message": message,
        "sessionId": session_id
    }
    
    if additional_fields:
        response.update(additional_fields)
    
    return response

# === Error Logging ===
async def log_error(
    error_type: str,
    error_message: str,
    request: BaseRequest,
    clinic_id: Optional[str] = None,
    additional_context: Optional[Dict[str, Any]] = None
) -> None:
    """Log error with context"""
    log_message = f"{error_type}: {error_message}"
    
    if additional_context:
        log_message += f" | Context: {additional_context}"
    
    logger.error(log_message)
    
    # Log to database if we have clinic info
    if clinic_id:
        try:
            await log_voice_booking({
                "clinic_id": clinic_id,
                "session_id": request.sessionId,
                "caller_phone": request.callerPhone,
                "action": getattr(request, 'action', 'unknown'),
                "status": "failed",
                "error_message": error_message[:500]  # Truncate for DB
            }, additional_context.get('db_pool') if additional_context else None)
        except Exception as e:
            logger.error(f"Failed to log error to database: {str(e)}")

# === Specific Error Handlers ===

async def handle_clinic_not_found(request: BaseRequest) -> Dict[str, Any]:
    """Handle clinic not found errors"""
    logger.error(f"Clinic not found for number: {request.dialedNumber}")
    
    return create_error_response(
        error_code="clinic_not_found",
        message="I couldn't find the clinic information. Please contact the clinic directly.",
        session_id=request.sessionId
    )

async def handle_missing_information(missing_fields: List[str], request: BaseRequest) -> Dict[str, Any]:
    """Handle missing required information"""
    logger.warning(f"Missing fields: {missing_fields}")
    
    return create_error_response(
        error_code="missing_information",
        message=f"I need some more information to book your appointment. Please provide: {', '.join(missing_fields)}",
        session_id=request.sessionId,
        additional_fields={"missingData": missing_fields}
    )

async def handle_practitioner_not_found(
    requested_name: str,
    available_practitioners: List[str],
    request: BaseRequest
) -> Dict[str, Any]:
    """Handle practitioner not found errors"""
    logger.error(f"Practitioner not found: '{requested_name}'")
    
    # Limit the list to avoid overwhelming the voice response
    displayed_practitioners = available_practitioners[:5]
    message = f"I couldn't find a practitioner named \"{requested_name}\". Available practitioners: {', '.join(displayed_practitioners)}"
    
    if len(available_practitioners) > 5:
        message += f" and {len(available_practitioners) - 5} others"
    
    return create_error_response(
        error_code="practitioner_not_found",
        message=message,
        session_id=request.sessionId
    )

async def handle_service_not_found(
    requested_service: str,
    practitioner_name: str,
    request: BaseRequest
) -> Dict[str, Any]:
    """Handle service not found errors"""
    logger.error(f"Service not found: '{requested_service}' for practitioner {practitioner_name}")
    
    return create_error_response(
        error_code="service_not_found",
        message=f"I couldn't find \"{requested_service}\" services with {practitioner_name}.",
        session_id=request.sessionId
    )

async def handle_invalid_phone_number(request: BaseRequest) -> Dict[str, Any]:
    """Handle invalid phone number errors"""
    logger.error(f"Invalid phone number provided")
    
    return create_error_response(
        error_code="invalid_phone_number",
        message="Please provide a valid 10-digit Australian mobile number starting with 04.",
        session_id=request.sessionId
    )

async def handle_no_availability(
    service_name: str,
    practitioner_name: str,
    date_str: str,
    request: BaseRequest
) -> Dict[str, Any]:
    """Handle no availability errors"""
    logger.warning("No available times found")
    
    return create_error_response(
        error_code="no_availability",
        message=f"I'm sorry, there are no available appointments for {service_name} with {practitioner_name} on {date_str}.",
        session_id=request.sessionId
    )

async def handle_time_not_available(
    requested_time: str,
    requested_date: str,
    practitioner_name: str,
    available_times: List[str],
    request: BaseRequest
) -> Dict[str, Any]:
    """Handle when exact requested time is not available"""
    
    if available_times:
        times_str = ", ".join(available_times[:5])  # Limit to 5 options
        if len(available_times) > 5:
            times_str += f" and {len(available_times) - 5} other times"
            
        message = (
            f"I'm sorry, {requested_time} is not available on {requested_date}. "
            f"{practitioner_name} has these times available: {times_str}. "
            f"Which time would you prefer?"
        )
    else:
        message = f"I'm sorry, there are no available times on {requested_date}."
    
    return create_error_response(
        error_code="time_not_available",
        message=message,
        session_id=request.sessionId,
        additional_fields={"availableTimes": available_times}
    )

async def handle_practitioner_location_mismatch(
    practitioner: Dict[str, Any],
    business: Dict[str, Any],
    clinic_id: str,
    request: BaseRequest,
    db_pool: Any
) -> Dict[str, Any]:
    """Handle practitioner-location mismatch errors"""
    # Get practitioners who actually work at this location
    services = await get_practitioner_services(clinic_id, db_pool)
    
    # Find practitioners at the requested location
    location_practitioners = list(set(
        s['practitioner_name'] 
        for s in services 
        if s['business_id'] == business['business_id']
    ))
    
    # Find where the requested practitioner actually works
    practitioner_locations = list(set(
        s['business_name'] 
        for s in services
        if s['practitioner_id'] == practitioner['practitioner_id']
    ))
    
    message = f"{practitioner['full_name']} doesn't work at {business['business_name']}. "
    
    if practitioner_locations:
        message += f"They are available at: {', '.join(practitioner_locations)}. "
        message += "Would you like to book at one of those locations instead?"
    elif location_practitioners:
        message += f"Practitioners at {business['business_name']}: {', '.join(location_practitioners[:3])}"
        if len(location_practitioners) > 3:
            message += f" and {len(location_practitioners) - 3} others"
    
    return create_error_response(
        error_code="practitioner_location_mismatch",
        message=message,
        session_id=request.sessionId
    )

# === API Error Handlers ===

async def handle_cliniko_api_error(
    error: httpx.HTTPStatusError,
    request: BaseRequest,
    context: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Handle Cliniko API HTTP errors"""
    logger.error(f"Cliniko API HTTP error: {error.response.status_code} - {error.response.text}")
    
    # Check for specific 404 case - practitioner/location mismatch
    if error.response.status_code == 404 and context:
        practitioner = context.get('practitioner')
        business = context.get('business')
        clinic_id = context.get('clinic_id')
        db_pool = context.get('db_pool')
        
        if all([practitioner, business, clinic_id, db_pool]):
            return await handle_practitioner_location_mismatch(
                practitioner, business, clinic_id, request, db_pool
            )
    
    # Generic API error messages
    if error.response.status_code == 401:
        message = "Authentication error with the booking system. Please contact the clinic."
    elif error.response.status_code == 403:
        message = "Access denied to the booking system. Please contact the clinic."
    elif error.response.status_code == 404:
        message = "The requested resource was not found. Please verify your details and try again."
    elif error.response.status_code >= 500:
        message = "The booking system is temporarily unavailable. Please try again in a few moments."
    else:
        message = "I encountered an error with the booking system. Please try again or contact the clinic directly."
    
    return create_error_response(
        error_code="cliniko_api_error",
        message=message,
        session_id=request.sessionId
    )

# --- NEW: Appointment creation API error handler ---
async def handle_appointment_creation_api_error(
    error: httpx.HTTPStatusError,
    appointment_data: Dict[str, Any],
    request: BaseRequest
) -> Dict[str, Any]:
    """Handle Cliniko API errors specific to appointment creation"""
    logger.error(f"Cliniko appointment creation error: {error.response.status_code}")
    logger.error(f"Response body: {error.response.text}")
    
    # Parse Cliniko error response
    try:
        error_body = error.response.json()
        error_message = error_body.get('message', '') or error_body.get('error', '')
    except:
        error_message = error.response.text
    
    # Handle specific Cliniko appointment errors
    if error.response.status_code == 422:  # Unprocessable Entity
        if "already booked" in error_message.lower():
            # Invalidate cache for this slot to prevent offering it again
            try:
                # Get cache instance
                from tools.dependencies import get_cache
                cache = await get_cache()
                
                # Extract date from appointment data
                if cache and appointment_data:
                    # Parse the appointment start time to get the date
                    appointment_start = appointment_data.get('appointment_start', '')
                    if appointment_start:
                        from datetime import datetime
                        if appointment_start.endswith('Z'):
                            dt = datetime.fromisoformat(appointment_start.replace('Z', '+00:00'))
                        else:
                            dt = datetime.fromisoformat(appointment_start)
                        
                        await cache.invalidate_availability(
                            appointment_data.get('practitioner_id'),
                            appointment_data.get('business_id'),
                            dt.date()
                        )
                        logger.info(f"Invalidated cache for slot at {appointment_start}")
            except Exception as cache_error:
                logger.warning(f"Failed to invalidate cache after slot conflict: {cache_error}")
            
            return create_error_response(
                error_code="time_slot_taken",
                message="That time slot has just been taken. Let me find another available time for you.",
                session_id=request.sessionId
            )
        elif "outside business hours" in error_message.lower():
            return create_error_response(
                error_code="outside_business_hours",
                message="That time is outside business hours. Let me find an available time during business hours.",
                session_id=request.sessionId
            )
        elif "practitioner" in error_message.lower() and "not available" in error_message.lower():
            return create_error_response(
                error_code="practitioner_not_available",
                message="The practitioner is not available at that time. Would you like to see other available times?",
                session_id=request.sessionId
            )
    
    # Use generic handler for other cases
    return await handle_cliniko_api_error(error, request)

async def handle_cliniko_request_error(
    error: httpx.RequestError,
    request: BaseRequest
) -> Dict[str, Any]:
    """Handle Cliniko API request/network errors"""
    logger.error(f"Cliniko API request error: {type(error).__name__}: {str(error)}")
    
    return create_error_response(
        error_code="network_error",
        message="I'm having trouble connecting to the booking system. Please check your connection and try again.",
        session_id=request.sessionId
    )

# === Database Error Handlers ===

async def handle_database_error(
    error: Exception,
    request: BaseRequest
) -> Dict[str, Any]:
    """Handle database connection errors"""
    logger.error(f"Database error: {type(error).__name__}: {str(error)}")
    
    return create_error_response(
        error_code="database_error",
        message="I'm experiencing technical difficulties. Please try again in a moment or contact the clinic directly.",
        session_id=request.sessionId
    )

# === Generic Error Handlers ===

async def handle_booking_error(
    error: Exception,
    request: BaseRequest,
    clinic_id: Optional[str] = None,
    context: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Handle any booking-related error"""
    # Log the error
    await log_error(
        error_type="Booking Error",
        error_message=str(error),
        request=request,
        clinic_id=clinic_id,
        additional_context=context
    )
    
    # Check for specific error types
    if isinstance(error, httpx.HTTPStatusError):
        return await handle_cliniko_api_error(error, request, context)
    elif isinstance(error, httpx.RequestError):
        return await handle_cliniko_request_error(error, request)
    elif isinstance(error, asyncpg.PostgresError):
        return await handle_database_error(error, request)
    
    # Generic error response
    return create_error_response(
        error_code="booking_failed",
        message="I'm sorry, I encountered an error while booking your appointment. Please try again or contact the clinic directly.",
        session_id=request.sessionId
    )

async def handle_availability_error(
    error: Exception,
    request: BaseRequest,
    clinic_id: Optional[str] = None
) -> Dict[str, Any]:
    """Handle availability check errors"""
    # Log the error
    await log_error(
        error_type="Availability Error",
        error_message=str(error),
        request=request,
        clinic_id=clinic_id
    )
    
    # Check for specific error types
    if isinstance(error, httpx.HTTPStatusError):
        return await handle_cliniko_api_error(error, request)
    elif isinstance(error, httpx.RequestError):
        return await handle_cliniko_request_error(error, request)
    
    return create_error_response(
        error_code="availability_check_failed",
        message="I'm sorry, I encountered an error while checking availability. Please try again.",
        session_id=request.sessionId
    )

async def handle_cancellation_error(
    error: Exception,
    request: BaseRequest,
    clinic_id: Optional[str] = None
) -> Dict[str, Any]:
    """Handle cancellation errors"""
    # Log the error
    await log_error(
        error_type="Cancellation Error",
        error_message=str(error),
        request=request,
        clinic_id=clinic_id
    )
    
    return create_error_response(
        error_code="cancellation_failed",
        message="I'm sorry, I encountered an error while cancelling your appointment. Please try again or contact the clinic directly.",
        session_id=request.sessionId
    )

# === Pre-check Functions ===

async def check_practitioner_location_compatibility(
    practitioner_id: str,
    business_id: str,
    clinic_id: str,
    db_pool: Any
) -> Optional[Dict[str, Any]]:
    """
    Pre-check if practitioner works at the specified location.
    Returns error response if mismatch, None if OK.
    """
    services = await get_practitioner_services(clinic_id, db_pool)
    
    # Check if practitioner has any services at this location
    services_at_location = [
        s for s in services
        if s['practitioner_id'] == practitioner_id 
        and s['business_id'] == business_id
    ]
    
    if not services_at_location:
        # Get where they actually work
        practitioner_info = next(
            (s for s in services if s['practitioner_id'] == practitioner_id),
            None
        )
        
        if practitioner_info:
            practitioner_locations = list(set(
                s['business_name'] 
                for s in services
                if s['practitioner_id'] == practitioner_id
            ))
            
            requested_business = next(
                (s['business_name'] for s in services if s['business_id'] == business_id),
                "the requested location"
            )
            
            return {
                "error": "practitioner_location_mismatch",
                "practitioner_name": practitioner_info['practitioner_name'],
                "requested_location": requested_business,
                "actual_locations": practitioner_locations
            }
    
    return None  # No error - practitioner works at this location

# === Validation Functions ===

def validate_booking_request(request: Any) -> List[str]:
    """Validate booking request and return list of missing fields"""
    missing_fields = []
    
    if not getattr(request, 'patientName', None):
        missing_fields.append("patient name")
    if not getattr(request, 'practitioner', None):
        missing_fields.append("practitioner name")
    if not getattr(request, 'appointmentType', None):
        missing_fields.append("appointment type")
    
    return missing_fields

# --- NEW: Appointment creation error handler ---
async def handle_appointment_creation_error(
    error: Exception,
    patient_name: str,
    practitioner_name: str,
    service_name: str,
    date_time: str,
    location_name: str,
    request: BaseRequest
) -> Dict[str, Any]:
    """Handle appointment creation failures with specific context"""
    logger.error(f"Appointment creation failed: {str(error)}")
    
    # Check if it's a duplicate booking attempt
    if "duplicate" in str(error).lower() or "already booked" in str(error).lower():
        return create_error_response(
            error_code="duplicate_booking",
            message=f"It looks like there's already an appointment booked for {patient_name} at this time. Please choose a different time slot.",
            session_id=request.sessionId
        )
    
    # Check if it's a time slot no longer available
    if "no longer available" in str(error).lower() or "already taken" in str(error).lower():
        return create_error_response(
            error_code="slot_taken",
            message=f"I'm sorry, that {date_time} slot with {practitioner_name} is no longer available. Would you like me to find another time?",
            session_id=request.sessionId
        )
    
    # Generic creation error
    return create_error_response(
        error_code="appointment_creation_failed",
        message=f"I couldn't complete the booking for your {service_name} appointment with {practitioner_name} at {location_name}. Please try again or contact the clinic directly.",
        session_id=request.sessionId,
        additional_fields={
            "attemptedBooking": {
                "patient": patient_name,
                "practitioner": practitioner_name,
                "service": service_name,
                "dateTime": date_time,
                "location": location_name
            }
        }
    )

# --- NEW: Appointment-handler validation helper ---
def validate_appointment_handler_request(request_body: Dict[str, Any]) -> List[str]:
    """Validate appointment-handler request from ElevenLabs and return list of missing fields"""
    missing_fields = []
    
    # Required fields for appointment creation
    required_fields = {
        'patientName': 'patient name',
        'practitioner': 'practitioner name',
        'appointmentType': 'appointment type',
        'appointmentDate': 'appointment date',
        'appointmentTime': 'appointment time',
        'business_id': 'business ID'
    }
    
    for field, display_name in required_fields.items():
        if not request_body.get(field):
            missing_fields.append(display_name)
    
    # Validate date format (YYYY-MM-DD)
    if request_body.get('appointmentDate'):
        try:
            datetime.strptime(request_body['appointmentDate'], '%Y-%m-%d')
        except ValueError:
            missing_fields.append('valid appointment date (format: YYYY-MM-DD)')
    
    # Validate time format (HH:MM)
    if request_body.get('appointmentTime'):
        try:
            time_parts = request_body['appointmentTime'].split(':')
            if len(time_parts) != 2:
                raise ValueError
            hour = int(time_parts[0])
            minute = int(time_parts[1])
            if not (0 <= hour <= 23 and 0 <= minute <= 59):
                raise ValueError
        except ValueError:
            missing_fields.append('valid appointment time (format: HH:MM in 24-hour)')
    
    # Validate business_id is a valid Cliniko ID
    business_id = request_body.get('business_id', '')
    if not business_id or not isinstance(business_id, str):
        missing_fields.append('valid business ID from location-resolver')
    
    return missing_fields