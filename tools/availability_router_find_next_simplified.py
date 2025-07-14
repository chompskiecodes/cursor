# tools/availability_router_find_next_simplified.py
"""Simplified find-next-available using window functions"""

from fastapi import APIRouter, Depends
from typing import Dict, Any
from datetime import datetime, date, timedelta
import logging
from pydantic import BaseModel
from .dependencies import verify_api_key, get_db
from database import get_clinic_by_dialed_number
from payload_logger import payload_logger
from tools.timezone_utils import get_clinic_timezone, format_time_for_voice, format_date_for_display

logger = logging.getLogger(__name__)
router = APIRouter(tags=["availability"])

class FindNextAvailableRequest(BaseModel):
    practitioner: str
    sessionId: str
    dialedNumber: str
    appointmentType: str = None
    callerPhone: str = None
    maxDaysAhead: int = 30

@router.post("/find-next-available")
async def find_next_available(
    request: FindNextAvailableRequest,
    authenticated: bool = Depends(verify_api_key)
) -> Dict[str, Any]:
    """Find next available appointment using window functions for efficiency"""
    
    payload_logger.log_payload("/find-next-available", request.dict())
    
    try:
        logger.info(f"=== FIND NEXT AVAILABLE START ===")
        logger.info(f"Session: {request.sessionId}")
        logger.info(f"Practitioner: '{request.practitioner}'")
        logger.info(f"Service: '{request.appointmentType}'")
        
        # Get database pool
        pool = await get_db()
        
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
        today = datetime.now(clinic_tz).date()
        max_date = today + timedelta(days=request.maxDaysAhead)
        
        # Single query to find next available slot using window functions
        next_available_query = """
        WITH matched_practitioner AS (
            -- Fuzzy match practitioner
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
            WHERE p.clinic_id = $1
                AND p.active = true
                AND (
                    LOWER(p.first_name) = LOWER($2)
                    OR LOWER(p.last_name) = LOWER($2)
                    OR LOWER(p.first_name || ' ' || p.last_name) = LOWER($2)
                    OR similarity(
                        LOWER(COALESCE(p.title || ' ', '') || p.first_name || ' ' || p.last_name),
                        LOWER($2)
                    ) > 0.3
                )
            ORDER BY match_score DESC
            LIMIT 1
        ),
        practitioner_services AS (
            -- Get services for practitioner
            SELECT DISTINCT
                mp.practitioner_id,
                mp.full_name,
                at.appointment_type_id,
                at.name as service_name,
                at.duration_minutes
            FROM matched_practitioner mp
            JOIN practitioner_appointment_types pat ON mp.practitioner_id = pat.practitioner_id
            JOIN appointment_types at ON pat.appointment_type_id = at.appointment_type_id
            WHERE at.active = true
                AND ($3::text IS NULL OR at.name ILIKE '%' || $3 || '%')
        ),
        available_slots AS (
            -- Get all available slots within date range
            SELECT 
                ac.practitioner_id,
                ac.business_id,
                b.business_name,
                ps.full_name as practitioner_name,
                ps.service_name,
                ac.date,
                (slot_data->>'appointment_start')::timestamptz as slot_time,
                slot_data->>'service_name' as slot_service,
                (slot_data->>'duration_minutes')::int as duration,
                -- Window function to find first slot per location
                ROW_NUMBER() OVER (
                    PARTITION BY ac.business_id 
                    ORDER BY ac.date, (slot_data->>'appointment_start')::timestamptz
                ) as slot_rank,
                -- Overall rank across all locations
                ROW_NUMBER() OVER (
                    ORDER BY ac.date, (slot_data->>'appointment_start')::timestamptz
                ) as overall_rank
            FROM practitioner_services ps
            JOIN availability_cache ac ON ac.practitioner_id = ps.practitioner_id
            JOIN businesses b ON ac.business_id = b.business_id
            CROSS JOIN LATERAL jsonb_array_elements(ac.available_slots) slot_data
            WHERE ac.clinic_id = $1
                AND ac.date >= $4::date
                AND ac.date <= $5::date
                AND NOT ac.is_stale
                AND ac.expires_at > NOW()
                AND ($3::text IS NULL OR slot_data->>'service_name' ILIKE '%' || $3 || '%')
        ),
        next_slots AS (
            -- Get the next available slot and a few alternatives
            SELECT 
                practitioner_id,
                practitioner_name,
                business_id,
                business_name,
                date,
                slot_time,
                slot_service,
                duration,
                overall_rank
            FROM available_slots
            WHERE overall_rank <= 5  -- Get first 5 slots
            ORDER BY overall_rank
        ),
        slot_summary AS (
            -- Summarize availability across all days
            SELECT 
                COUNT(DISTINCT date) as days_with_availability,
                COUNT(*) as total_slots,
                MIN(date) as first_available_date,
                array_agg(DISTINCT date ORDER BY date) as available_dates
            FROM available_slots
        )
        SELECT 
            json_build_object(
                'practitioner', CASE 
                    WHEN mp.practitioner_id IS NOT NULL THEN json_build_object(
                        'id', mp.practitioner_id,
                        'name', mp.full_name
                    )
                    ELSE NULL
                END,
                'next_slot', (
                    SELECT json_build_object(
                        'date', date,
                        'time', to_char(slot_time AT TIME ZONE $6, 'HH24:MI'),
                        'display_time', to_char(slot_time AT TIME ZONE $6, 'HH:MI AM'),
                        'service', slot_service,
                        'duration', duration,
                        'location_id', business_id,
                        'location', business_name,
                        'datetime', slot_time
                    )
                    FROM next_slots
                    WHERE overall_rank = 1
                ),
                'alternatives', (
                    SELECT json_agg(
                        json_build_object(
                            'date', date,
                            'time', to_char(slot_time AT TIME ZONE $6, 'HH24:MI'),
                            'display_time', to_char(slot_time AT TIME ZONE $6, 'HH:MI AM'),
                            'service', slot_service,
                            'location', business_name
                        ) ORDER BY overall_rank
                    )
                    FROM next_slots
                    WHERE overall_rank > 1
                ),
                'summary', (
                    SELECT row_to_json(s) FROM slot_summary s
                ),
                'services', CASE 
                    WHEN mp.practitioner_id IS NOT NULL THEN (
                        SELECT json_agg(DISTINCT service_name)
                        FROM practitioner_services
                    )
                    ELSE NULL
                END
            ) as result
        FROM matched_practitioner mp
        """
        
        async with pool.acquire() as conn:
            result = await conn.fetchval(
                next_available_query,
                clinic.clinic_id,          # $1
                request.practitioner,      # $2
                request.appointmentType,   # $3
                today,                     # $4
                max_date,                  # $5
                clinic.timezone           # $6
            )
            
            data = result if isinstance(result, dict) else {}
        
        # Check if practitioner was found
        if not data.get('practitioner'):
            return {
                "success": False,
                "error": "practitioner_not_found",
                "message": f"I couldn't find a practitioner named '{request.practitioner}'.",
                "sessionId": request.sessionId
            }
        
        practitioner_name = data['practitioner']['name']
        next_slot = data.get('next_slot')
        
        # Check if service was specified but not found
        if request.appointmentType and not data.get('services'):
            services = data.get('services', [])
            return {
                "success": False,
                "error": "service_not_found",
                "message": f"{practitioner_name} doesn't offer {request.appointmentType}.",
                "suggestions": services[:3] if services else [],
                "sessionId": request.sessionId
            }
        
        if not next_slot:
            # No availability found
            summary = data.get('summary', {})
            return {
                "success": False,
                "error": "no_availability",
                "message": f"{practitioner_name} doesn't have any available appointments in the next {request.maxDaysAhead} days.",
                "practitioner": practitioner_name,
                "sessionId": request.sessionId
            }
        
        # Format the response
        slot_date = datetime.fromisoformat(str(next_slot['date']))
        slot_datetime = datetime.fromisoformat(str(next_slot['datetime']))
        
        # Calculate relative date description
        days_ahead = (slot_date.date() - today).days
        if days_ahead == 0:
            date_desc = "today"
        elif days_ahead == 1:
            date_desc = "tomorrow"
        elif days_ahead < 7:
            date_desc = f"this {slot_date.strftime('%A')}"
        elif days_ahead < 14:
            date_desc = f"next {slot_date.strftime('%A')}"
        else:
            date_desc = slot_date.strftime('%A, %B %d')
        
        # Build message
        message = f"The next available appointment with {practitioner_name} is {date_desc} at {next_slot['display_time']}"
        
        if next_slot.get('location'):
            message += f" at our {next_slot['location']} location"
        
        message += "."
        
        # Add alternatives if available
        alternatives = data.get('alternatives', [])
        if alternatives:
            message += " I also have openings "
            alt_times = []
            for alt in alternatives[:2]:  # Show max 2 alternatives
                alt_date = datetime.fromisoformat(str(alt['date']))
                if alt_date.date() == slot_date.date():
                    alt_times.append(f"at {alt['display_time']}")
                else:
                    alt_desc = alt_date.strftime('%A') if (alt_date.date() - today).days < 7 else alt_date.strftime('%B %d')
                    alt_times.append(f"on {alt_desc} at {alt['display_time']}")
            message += " and ".join(alt_times) + "."
        
        return {
            "success": True,
            "sessionId": request.sessionId,
            "practitioner": practitioner_name,
            "practitionerId": data['practitioner']['id'],
            "date": next_slot['date'],
            "time": next_slot['time'],
            "displayTime": next_slot['display_time'],
            "service": next_slot.get('service', request.appointmentType),
            "duration": next_slot.get('duration', 60),
            "locationId": next_slot['location_id'],
            "location": next_slot['location'],
            "message": message,
            "alternatives": alternatives,
            "availability_summary": {
                "days_with_slots": data['summary'].get('days_with_availability', 0),
                "total_slots": data['summary'].get('total_slots', 0),
                "next_available": date_desc
            }
        }
        
    except Exception as e:
        logger.error(f"Find next available failed: {str(e)}", exc_info=True)
        
        return {
            "success": False,
            "error": "internal_error", 
            "message": "I'm having trouble finding available appointments right now. Please try again.",
            "sessionId": request.sessionId
        }