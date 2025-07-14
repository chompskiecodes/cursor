# tools/booking_router_simplified.py
"""Simplified appointment handler using single transaction"""

from fastapi import APIRouter, Depends, HTTPException
from typing import Dict, Any, Optional
from datetime import datetime, date, time, timedelta
import logging
import asyncpg
from models import BookingRequest
from .dependencies import verify_api_key, get_db, get_cache
from database import get_clinic_by_dialed_number
from cliniko import ClinikoAPI
from payload_logger import payload_logger
from tools.timezone_utils import (
    get_clinic_timezone, 
    combine_date_time_local,
    format_time_for_voice
)
from utils import normalize_phone, parse_date_request, parse_time_request

logger = logging.getLogger(__name__)
router = APIRouter(tags=["booking"])

@router.post("/appointment-handler")
async def handle_appointment(
    request: BookingRequest,
    authenticated: bool = Depends(verify_api_key)
) -> Dict[str, Any]:
    """Handle appointment booking with all validation in single transaction"""
    
    payload_logger.log_payload("/appointment-handler", request.dict())
    
    # Parse action type
    action = (request.action or "book").lower()
    if action not in ["book", "reschedule", "cancel"]:
        return {
            "success": False,
            "error": "invalid_action",
            "message": f"I don't understand the action '{action}'.",
            "sessionId": request.sessionId
        }
    
    try:
        logger.info(f"=== APPOINTMENT HANDLER START ({action.upper()}) ===")
        logger.info(f"Session: {request.sessionId}")
        
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
        
        clinic_tz = get_clinic_timezone(clinic)
        
        # Initialize Cliniko API
        cliniko = ClinikoAPI(
            clinic.cliniko_api_key,
            clinic.cliniko_shard,
            clinic.contact_email
        )
        
        # Single transaction for all operations
        async with pool.acquire() as conn:
            async with conn.transaction():
                
                # Step 1: Validate and get/create patient
                patient_phone = normalize_phone(request.patientPhone or request.callerPhone)
                
                patient_result = await conn.fetchrow("""
                    WITH patient_lookup AS (
                        -- Try to find existing patient
                        SELECT 
                            patient_id,
                            first_name,
                            last_name,
                            email,
                            phone_number
                        FROM patients
                        WHERE clinic_id = $1 AND phone_number = $2
                        LIMIT 1
                    ),
                    patient_create AS (
                        -- Create if not exists
                        INSERT INTO patients (
                            patient_id, 
                            clinic_id, 
                            phone_number, 
                            first_name, 
                            last_name
                        )
                        SELECT 
                            'temp_' || gen_random_uuid()::text,
                            $1,
                            $2,
                            $3,
                            $4
                        WHERE NOT EXISTS (SELECT 1 FROM patient_lookup)
                        RETURNING patient_id, first_name, last_name, email, phone_number
                    )
                    SELECT * FROM patient_lookup
                    UNION ALL
                    SELECT * FROM patient_create
                    LIMIT 1
                """, clinic.clinic_id, patient_phone, 
                    request.patientName.split()[0] if request.patientName else "Guest",
                    request.patientName.split()[1] if request.patientName and len(request.patientName.split()) > 1 else "Patient"
                )
                
                if not patient_result:
                    raise Exception("Failed to find or create patient")
                
                patient_id = patient_result['patient_id']
                is_new_patient = patient_id.startswith('temp_')
                
                # Step 2: Match practitioner and validate location
                practitioner_result = await conn.fetchrow("""
                    WITH matched_practitioner AS (
                        SELECT 
                            p.practitioner_id,
                            p.first_name,
                            p.last_name,
                            COALESCE(p.title || ' ', '') || p.first_name || ' ' || p.last_name as full_name,
                            similarity(
                                LOWER(COALESCE(p.title || ' ', '') || p.first_name || ' ' || p.last_name),
                                LOWER($2)
                            ) as match_score
                        FROM practitioners p
                        WHERE p.clinic_id = $1 AND p.active = true
                        ORDER BY match_score DESC
                        LIMIT 1
                    ),
                    practitioner_locations AS (
                        SELECT 
                            mp.practitioner_id,
                            mp.full_name,
                            array_agg(pb.business_id) as business_ids,
                            bool_or(pb.business_id = $3) as works_at_location
                        FROM matched_practitioner mp
                        JOIN practitioner_businesses pb ON mp.practitioner_id = pb.practitioner_id
                        GROUP BY mp.practitioner_id, mp.full_name
                    )
                    SELECT * FROM practitioner_locations
                """, clinic.clinic_id, request.practitioner, request.locationId or request.business_id)
                
                if not practitioner_result:
                    return {
                        "success": False,
                        "error": "practitioner_not_found",
                        "message": f"I couldn't find a practitioner named '{request.practitioner}'.",
                        "sessionId": request.sessionId
                    }
                
                if not practitioner_result['works_at_location']:
                    return {
                        "success": False,
                        "error": "practitioner_location_mismatch",
                        "message": f"{practitioner_result['full_name']} doesn't work at that location.",
                        "sessionId": request.sessionId
                    }
                
                practitioner_id = practitioner_result['practitioner_id']
                practitioner_name = practitioner_result['full_name']
                
                # Step 3: Match service and get appointment type
                service_result = await conn.fetchrow("""
                    SELECT 
                        at.appointment_type_id,
                        at.name as service_name,
                        at.duration_minutes
                    FROM appointment_types at
                    JOIN practitioner_appointment_types pat ON at.appointment_type_id = pat.appointment_type_id
                    WHERE pat.practitioner_id = $1
                        AND at.active = true
                        AND (
                            LOWER(at.name) = LOWER($2)
                            OR at.name ILIKE '%' || $2 || '%'
                        )
                    ORDER BY 
                        CASE WHEN LOWER(at.name) = LOWER($2) THEN 0 ELSE 1 END,
                        similarity(LOWER(at.name), LOWER($2)) DESC
                    LIMIT 1
                """, practitioner_id, request.appointmentType)
                
                if not service_result:
                    return {
                        "success": False,
                        "error": "service_not_found",
                        "message": f"{practitioner_name} doesn't offer {request.appointmentType}.",
                        "sessionId": request.sessionId
                    }
                
                appointment_type_id = service_result['appointment_type_id']
                service_name = service_result['service_name']
                duration_minutes = service_result['duration_minutes']
                
                # Step 4: Parse and validate date/time
                appointment_date = parse_date_request(request.appointmentDate, clinic_tz)
                if not appointment_date:
                    return {
                        "success": False,
                        "error": "invalid_date",
                        "message": "I couldn't understand the date. Please try again.",
                        "sessionId": request.sessionId
                    }
                
                appointment_time = parse_time_request(request.appointmentTime)
                if not appointment_time:
                    return {
                        "success": False,
                        "error": "invalid_time",
                        "message": "I couldn't understand the time. Please try again.",
                        "sessionId": request.sessionId
                    }
                
                # Combine date and time in clinic timezone
                start_datetime = combine_date_time_local(
                    appointment_date,
                    appointment_time.hour,
                    appointment_time.minute,
                    clinic_tz
                )
                end_datetime = start_datetime + timedelta(minutes=duration_minutes)
                
                # Step 5: Check availability in cache
                availability_check = await conn.fetchrow("""
                    SELECT EXISTS (
                        SELECT 1 
                        FROM availability_cache ac
                        WHERE ac.practitioner_id = $1
                            AND ac.business_id = $2
                            AND ac.date = $3
                            AND NOT ac.is_stale
                            AND ac.expires_at > NOW()
                            AND EXISTS (
                                SELECT 1 
                                FROM jsonb_array_elements(ac.available_slots) slot
                                WHERE (slot->>'appointment_start')::timestamptz = $4
                            )
                    ) as is_available
                """, practitioner_id, request.locationId or request.business_id, 
                    appointment_date, start_datetime)
                
                if not availability_check or not availability_check['is_available']:
                    return {
                        "success": False,
                        "error": "time_not_available",
                        "message": f"That time is no longer available with {practitioner_name}.",
                        "sessionId": request.sessionId
                    }
                
                # Step 6: Create patient in Cliniko if new
                if is_new_patient:
                    try:
                        name_parts = (request.patientName or "Guest Patient").split(' ', 1)
                        cliniko_patient = await cliniko.create_patient({
                            "first_name": name_parts[0],
                            "last_name": name_parts[1] if len(name_parts) > 1 else "Patient",
                            "phone": patient_phone
                        })
                        
                        # Update patient_id with real Cliniko ID
                        await conn.execute("""
                            UPDATE patients 
                            SET patient_id = $1 
                            WHERE patient_id = $2
                        """, str(cliniko_patient['id']), patient_id)
                        
                        patient_id = str(cliniko_patient['id'])
                    except Exception as e:
                        logger.error(f"Failed to create patient in Cliniko: {e}")
                        raise Exception("Failed to create patient record")
                
                # Step 7: Create appointment in Cliniko
                try:
                    appointment = await cliniko.create_individual_appointment(
                        patient_id=patient_id,
                        practitioner_id=practitioner_id,
                        business_id=request.locationId or request.business_id,
                        appointment_type_id=appointment_type_id,
                        start_time=start_datetime
                    )
                    
                    appointment_id = str(appointment['id'])
                except Exception as e:
                    logger.error(f"Cliniko appointment creation failed: {e}")
                    
                    # Check if it's because slot was taken
                    if "not available" in str(e).lower():
                        # Invalidate cache for this day
                        await conn.execute("""
                            UPDATE availability_cache 
                            SET is_stale = true 
                            WHERE practitioner_id = $1 
                                AND business_id = $2 
                                AND date = $3
                        """, practitioner_id, request.locationId or request.business_id, appointment_date)
                        
                        return {
                            "success": False,
                            "error": "time_just_taken",
                            "message": "Someone just booked that time. Please choose another time.",
                            "sessionId": request.sessionId
                        }
                    raise
                
                # Step 8: Save to local database
                await conn.execute("""
                    INSERT INTO appointments (
                        appointment_id, clinic_id, patient_id, practitioner_id,
                        appointment_type_id, business_id, starts_at, ends_at,
                        status, notes, created_at
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, NOW())
                """, appointment_id, clinic.clinic_id, patient_id, practitioner_id,
                    appointment_type_id, request.locationId or request.business_id,
                    start_datetime, end_datetime, 'booked', request.notes)
                
                # Step 9: Log the booking
                await conn.execute("""
                    INSERT INTO voice_bookings (
                        appointment_id, clinic_id, session_id, caller_phone,
                        action, status, booking_details, created_at
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, NOW())
                """, appointment_id, clinic.clinic_id, request.sessionId,
                    request.callerPhone, 'book', 'completed',
                    {
                        'practitioner': practitioner_name,
                        'service': service_name,
                        'datetime': start_datetime.isoformat()
                    })
                
                # Step 10: Invalidate cache for this slot
                await conn.execute("""
                    UPDATE availability_cache 
                    SET is_stale = true 
                    WHERE practitioner_id = $1 
                        AND business_id = $2 
                        AND date = $3
                """, practitioner_id, request.locationId or request.business_id, appointment_date)
                
                # Step 11: Get business name for response
                business = await conn.fetchrow("""
                    SELECT business_name 
                    FROM businesses 
                    WHERE business_id = $1
                """, request.locationId or request.business_id)
                
                # Success! Build response
                display_time = format_time_for_voice(start_datetime)
                display_date = appointment_date.strftime("%A, %B %d, %Y")
                
                return {
                    "success": True,
                    "sessionId": request.sessionId,
                    "message": f"Perfect! I've successfully booked your {service_name} appointment with {practitioner_name} for {display_date} at {display_time}.",
                    "appointmentDetails": {
                        "appointmentId": appointment_id,
                        "practitioner": practitioner_name,
                        "service": service_name,
                        "duration": f"{duration_minutes} minutes",
                        "date": display_date,
                        "time": display_time,
                        "location": business['business_name'] if business else "our clinic",
                        "patient": f"{patient_result['first_name']} {patient_result['last_name']}"
                    }
                }
                
    except asyncpg.PostgresError as e:
        logger.error(f"Database error in appointment handler: {str(e)}", exc_info=True)
        return {
            "success": False,
            "error": "database_error",
            "message": "I'm having trouble accessing the booking system. Please try again.",
            "sessionId": request.sessionId
        }
    except Exception as e:
        logger.error(f"Appointment handler failed: {str(e)}", exc_info=True)
        return {
            "success": False,
            "error": "internal_error",
            "message": "I encountered an error while booking your appointment. Please try again.",
            "sessionId": request.sessionId
        }