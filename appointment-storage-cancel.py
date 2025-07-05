# appointment_functions.py
"""
Functions for storing appointments and handling cancellations
Add these to your database.py or create as a new file
"""

import asyncpg
import logging
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta
from utils import normalize_phone, parse_date_request, parse_time_request

logger = logging.getLogger(__name__)

# === Appointment Storage Functions ===

async def save_appointment_to_db(appointment_data: Dict[str, Any], pool: asyncpg.Pool) -> None:
    """Save appointment to database after successful Cliniko booking"""
    query = """
        INSERT INTO appointments (
            appointment_id, clinic_id, patient_id, practitioner_id,
            appointment_type_id, business_id, starts_at, ends_at,
            status, notes
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
        ON CONFLICT (appointment_id) DO UPDATE SET
            status = EXCLUDED.status,
            updated_at = NOW()
    """
    
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                query,
                appointment_data['appointment_id'],
                appointment_data['clinic_id'],
                appointment_data['patient_id'],
                appointment_data['practitioner_id'],
                appointment_data['appointment_type_id'],
                appointment_data['business_id'],
                appointment_data['starts_at'],
                appointment_data['ends_at'],
                appointment_data.get('status', 'booked'),
                appointment_data.get('notes')
            )
            logger.info(f"Saved appointment {appointment_data['appointment_id']} to database")
    except Exception as e:
        logger.error(f"Failed to save appointment: {str(e)}")
        # Don't raise - appointment is already in Cliniko

async def find_appointment_by_details(
    clinic_id: str,
    caller_phone: str,
    details: str,
    practitioner_name: Optional[str] = None,
    date_str: Optional[str] = None,
    time_str: Optional[str] = None,
    pool: asyncpg.Pool = None
) -> Optional[Dict[str, Any]]:
    """
    Find appointment by natural language details
    Examples:
    - "my appointment tomorrow with Cameron"
    - "my 2pm appointment with Dr. Smith"
    - "my massage appointment next Monday"
    """
    
    # Normalize caller phone for matching
    caller_phone_normalized = normalize_phone(caller_phone)
    
    # Parse date from details or use provided
    if date_str:
        appointment_date = parse_date_request(date_str)
    else:
        # Try to extract date from details
        date_keywords = ['today', 'tomorrow', 'monday', 'tuesday', 'wednesday', 
                        'thursday', 'friday', 'saturday', 'sunday', 'next week']
        details_lower = details.lower()
        appointment_date = None
        
        for keyword in date_keywords:
            if keyword in details_lower:
                appointment_date = parse_date_request(keyword)
                break
        
        if not appointment_date:
            # Default to next 7 days if no date specified
            appointment_date = datetime.now().date()
    
    # Build query
    query = """
        SELECT DISTINCT
            a.appointment_id,
            a.patient_id,
            a.practitioner_id,
            a.appointment_type_id,
            a.starts_at,
            a.ends_at,
            a.status,
            p.first_name || ' ' || p.last_name as patient_name,
            pr.first_name || ' ' || pr.last_name as practitioner_name,
            at.name as service_name,
            pat.phone_number as patient_phone
        FROM appointments a
        JOIN patients pat ON a.patient_id = pat.patient_id
        JOIN practitioners pr ON a.practitioner_id = pr.practitioner_id
        JOIN appointment_types at ON a.appointment_type_id = at.appointment_type_id
        LEFT JOIN patients p ON a.patient_id = p.patient_id
        WHERE a.clinic_id = $1
          AND a.status = 'booked'
          AND DATE(a.starts_at) >= $2
          AND DATE(a.starts_at) <= $3
          AND (pat.phone_number = $4 OR p.phone_number = $4)
    """
    
    params = [
        clinic_id,
        appointment_date,
        appointment_date + timedelta(days=7),  # Search up to a week ahead
        caller_phone_normalized
    ]
    
    # Add practitioner filter if specified
    if practitioner_name:
        query += " AND (LOWER(pr.first_name) LIKE $5 OR LOWER(pr.last_name) LIKE $5 OR LOWER(pr.first_name || ' ' || pr.last_name) LIKE $5)"
        params.append(f"%{practitioner_name.lower()}%")
    
    # Add time filter if specified
    if time_str:
        hour, minute = parse_time_request(time_str)
        query += f" AND EXTRACT(HOUR FROM a.starts_at) = ${len(params)+1} AND EXTRACT(MINUTE FROM a.starts_at) = ${len(params)+2}"
        params.extend([hour, minute])
    
    query += " ORDER BY a.starts_at LIMIT 5"
    
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(query, *params)
            
            if not rows:
                return None
            
            # If multiple matches, try to find best match
            if len(rows) == 1:
                return dict(rows[0])
            
            # Multiple matches - try to match more details
            for row in rows:
                row_dict = dict(row)
                details_lower = details.lower()
                
                # Check if practitioner name is mentioned
                if row_dict['practitioner_name'].lower() in details_lower:
                    return row_dict
                
                # Check if service name is mentioned
                if row_dict['service_name'].lower() in details_lower:
                    return row_dict
            
            # Return the earliest appointment if no better match
            return dict(rows[0])
            
    except Exception as e:
        logger.error(f"Error finding appointment: {str(e)}")
        return None

async def update_appointment_status(
    appointment_id: str,
    status: str,
    pool: asyncpg.Pool
) -> bool:
    """Update appointment status in database"""
    query = """
        UPDATE appointments 
        SET status = $1, updated_at = NOW()
        WHERE appointment_id = $2
    """
    
    try:
        async with pool.acquire() as conn:
            result = await conn.execute(query, status, appointment_id)
            return result.split()[-1] == '1'  # Returns "UPDATE 1" if successful
    except Exception as e:
        logger.error(f"Error updating appointment status: {str(e)}")
        return False

# === Add to your main.py imports ===
# from appointment_functions import save_appointment_to_db, find_appointment_by_details, update_appointment_status

# === Add to your handle_appointment function after successful Cliniko booking ===
"""
# Save to database
await save_appointment_to_db({
    "appointment_id": str(appointment['id']),
    "clinic_id": clinic.clinic_id,
    "patient_id": patient['patient_id'],
    "practitioner_id": practitioner['practitioner_id'],
    "appointment_type_id": service['appointment_type_id'],
    "business_id": business['business_id'],
    "starts_at": best_slot['appointment_start'],
    "ends_at": best_slot['appointment_end'],
    "status": "booked",
    "notes": request.notes
}, db.pool)
"""

# === Updated cancel_appointment function for main.py ===
"""
@app.post("/cancel-appointment")
async def cancel_appointment(
    request: CancelRequest,
    authenticated: bool = Depends(verify_api_key)
) -> Dict[str, Any]:
    try:
        # Get clinic information
        clinic = await get_clinic_by_dialed_number(request.dialedNumber, db.pool)
        if not clinic:
            return {
                "success": False,
                "error": "clinic_not_found",
                "message": "I'm sorry, I couldn't find a clinic associated with this phone number.",
                "sessionId": request.sessionId
            }
        
        # Initialize Cliniko API
        cliniko = ClinikoAPI(
            clinic.cliniko_api_key,
            clinic.cliniko_shard,
            clinic.contact_email
        )
        
        # If no appointment ID, try to find by details
        if not request.appointmentId and request.appointmentDetails:
            logger.info(f"Searching for appointment with details: {request.appointmentDetails}")
            
            # Find appointment in database
            found_appointment = await find_appointment_by_details(
                clinic_id=clinic.clinic_id,
                caller_phone=request.callerPhone,
                details=request.appointmentDetails,
                pool=db.pool
            )
            
            if not found_appointment:
                return {
                    "success": False,
                    "error": "appointment_not_found",
                    "message": "I couldn't find your appointment. Could you provide more details like the practitioner's name or the appointment time?",
                    "sessionId": request.sessionId
                }
            
            # Confirm details with user
            appointment_time = datetime.fromisoformat(found_appointment['starts_at'].isoformat())
            confirm_message = (
                f"I found your {found_appointment['service_name']} appointment "
                f"with {found_appointment['practitioner_name']} on "
                f"{appointment_time.strftime('%A, %B %d at %I:%M %p')}. "
                f"Cancelling this appointment now."
            )
            
            request.appointmentId = found_appointment['appointment_id']
            logger.info(f"Found appointment ID: {request.appointmentId}")
        
        # Cancel in Cliniko
        if request.appointmentId:
            success = await cliniko.cancel_appointment(request.appointmentId)
            
            if success:
                # Update status in database
                await update_appointment_status(request.appointmentId, 'cancelled', db.pool)
                
                # Log the cancellation
                await log_voice_booking({
                    "appointment_id": request.appointmentId,
                    "clinic_id": clinic.clinic_id,
                    "session_id": request.sessionId,
                    "caller_phone": request.callerPhone,
                    "action": "cancel",
                    "status": "completed"
                }, db.pool)
                
                return {
                    "success": True,
                    "message": confirm_message if 'confirm_message' in locals() else "Your appointment has been successfully cancelled.",
                    "sessionId": request.sessionId
                }
            else:
                return {
                    "success": False,
                    "error": "cancellation_failed",
                    "message": "I wasn't able to cancel that appointment. It may have already been cancelled or completed.",
                    "sessionId": request.sessionId
                }
        
        return {
            "success": False,
            "error": "appointment_not_found",
            "message": "I need more information to find your appointment. Please provide details like the practitioner's name, date, or time.",
            "sessionId": request.sessionId
        }
        
    except Exception as e:
        logger.error(f"Cancellation error: {str(e)}", exc_info=True)
        return {
            "success": False,
            "error": "cancel_failed",
            "message": "I'm sorry, I encountered an error while cancelling your appointment. Please try again or contact the clinic directly.",
            "sessionId": request.sessionId
        }
"""