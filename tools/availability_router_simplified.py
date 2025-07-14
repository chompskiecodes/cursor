# tools/availability_router_simplified.py
"""Simplified availability checker using single SQL query"""

from fastapi import APIRouter, Depends
from typing import Dict, Any, List, Optional
from datetime import datetime, date, time, timedelta
import logging
from models import AvailabilityRequest
from .dependencies import verify_api_key, get_db, get_cache
from database import get_clinic_by_dialed_number
from payload_logger import payload_logger
from tools.timezone_utils import get_clinic_timezone, format_time_for_voice

logger = logging.getLogger(__name__)
router = APIRouter(tags=["availability"])

@router.post("/availability-checker")
async def check_availability(
    request: AvailabilityRequest,
    authenticated: bool = Depends(verify_api_key)
) -> Dict[str, Any]:
    """Check practitioner availability with single optimized query"""
    
    payload_logger.log_payload("/availability-checker", request.dict())
    
    try:
        logger.info(f"=== AVAILABILITY CHECK START ===")
        logger.info(f"Session: {request.sessionId}")
        logger.info(f"Practitioner: '{request.practitioner}'")
        logger.info(f"Date: {request.date}")
        
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
        
        # Parse date
        from utils import parse_date_request
        target_date = parse_date_request(request.date, clinic_tz)
        if not target_date:
            return {
                "success": False,
                "error": "invalid_date",
                "message": "I couldn't understand the date. Could you please specify a day like 'tomorrow' or 'next Monday'?",
                "sessionId": request.sessionId
            }
        
        # Single comprehensive query using CTEs
        availability_query = """
        WITH matched_practitioner AS (
            -- Fuzzy match practitioner by name
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
                    -- Exact match on various combinations
                    LOWER(p.first_name) = LOWER($2)
                    OR LOWER(p.last_name) = LOWER($2)
                    OR LOWER(p.first_name || ' ' || p.last_name) = LOWER($2)
                    OR LOWER(COALESCE(p.title, '') || ' ' || p.last_name) = LOWER($2)
                    -- Fuzzy match with threshold
                    OR similarity(
                        LOWER(COALESCE(p.title || ' ', '') || p.first_name || ' ' || p.last_name),
                        LOWER($2)
                    ) > 0.3
                )
            ORDER BY match_score DESC
            LIMIT 1
        ),
        practitioner_locations AS (
            -- Get all locations where practitioner works
            SELECT DISTINCT
                mp.practitioner_id,
                pb.business_id,
                b.business_name
            FROM matched_practitioner mp
            JOIN practitioner_businesses pb ON mp.practitioner_id = pb.practitioner_id
            JOIN businesses b ON pb.business_id = b.business_id
            WHERE b.clinic_id = $1
        ),
        matched_location AS (
            -- Match location if provided, otherwise get all
            SELECT 
                pl.*,
                CASE 
                    WHEN $4::text IS NULL OR $4 = '' THEN 1.0
                    ELSE similarity(LOWER(pl.business_name), LOWER($4))
                END as location_match_score
            FROM practitioner_locations pl
            WHERE $4::text IS NULL 
                OR $4 = ''
                OR pl.business_id = $4
                OR similarity(LOWER(pl.business_name), LOWER($4)) > 0.3
            ORDER BY location_match_score DESC
        ),
        available_slots AS (
            -- Get all available slots for the practitioner on the date
            SELECT 
                ac.practitioner_id,
                ac.business_id,
                ml.business_name,
                mp.full_name as practitioner_name,
                mp.match_score as practitioner_match_score,
                ml.location_match_score,
                ac.date,
                slot.slot_time,
                slot.service_name,
                slot.duration_minutes,
                slot.appointment_type_id
            FROM matched_location ml
            JOIN availability_cache ac ON 
                ac.practitioner_id = ml.practitioner_id 
                AND ac.business_id = ml.business_id
            JOIN matched_practitioner mp ON mp.practitioner_id = ac.practitioner_id
            CROSS JOIN LATERAL (
                SELECT 
                    (obj->>'appointment_start')::timestamptz as slot_time,
                    obj->>'service_name' as service_name,
                    (obj->>'duration_minutes')::int as duration_minutes,
                    obj->>'appointment_type_id' as appointment_type_id
                FROM jsonb_array_elements(ac.available_slots) obj
            ) slot
            WHERE ac.date = $3::date
                AND NOT ac.is_stale
                AND ac.expires_at > NOW()
                AND ($5::text IS NULL OR slot.service_name ILIKE '%' || $5 || '%')
            ORDER BY ml.location_match_score DESC, slot.slot_time
        ),
        summary AS (
            -- Group slots by time periods for conversational summary
            SELECT 
                COUNT(*) as total_slots,
                COUNT(DISTINCT business_id) as location_count,
                MIN(slot_time) as first_slot,
                MAX(slot_time) as last_slot,
                array_agg(DISTINCT business_name) as locations,
                CASE 
                    WHEN COUNT(*) = 0 THEN 'no availability'
                    WHEN COUNT(*) <= 3 THEN 'limited availability'
                    WHEN COUNT(*) <= 8 THEN 'good availability'
                    ELSE 'wide open'
                END as availability_level,
                -- Group by morning/afternoon/evening
                array_agg(
                    CASE 
                        WHEN EXTRACT(hour FROM slot_time AT TIME ZONE $6) < 12 THEN 'morning'
                        WHEN EXTRACT(hour FROM slot_time AT TIME ZONE $6) < 17 THEN 'afternoon'
                        ELSE 'evening'
                    END
                ) as time_periods
            FROM available_slots
        )
        SELECT 
            json_build_object(
                'practitioner', CASE 
                    WHEN mp.practitioner_id IS NOT NULL THEN json_build_object(
                        'id', mp.practitioner_id,
                        'name', mp.full_name,
                        'match_score', mp.match_score
                    )
                    ELSE NULL
                END,
                'slots', COALESCE(
                    json_agg(
                        json_build_object(
                            'time', to_char(slot_time AT TIME ZONE $6, 'HH24:MI'),
                            'display_time', to_char(slot_time AT TIME ZONE $6, 'HH:MI AM'),
                            'service', service_name,
                            'duration', duration_minutes,
                            'location_id', business_id,
                            'location', business_name
                        ) ORDER BY slot_time
                    ) FILTER (WHERE slot_time IS NOT NULL),
                    '[]'::json
                ),
                'summary', COALESCE(
                    (SELECT row_to_json(s) FROM summary s),
                    json_build_object('total_slots', 0, 'availability_level', 'no availability')
                ),
                'all_practitioners', (
                    -- Include suggestions if no match found
                    SELECT json_agg(
                        json_build_object(
                            'name', COALESCE(title || ' ', '') || first_name || ' ' || last_name,
                            'id', practitioner_id
                        )
                    )
                    FROM practitioners
                    WHERE clinic_id = $1 AND active = true
                )
            ) as result
        FROM matched_practitioner mp
        """
        
        async with pool.acquire() as conn:
            result = await conn.fetchval(
                availability_query,
                clinic.clinic_id,               # $1
                request.practitioner,           # $2
                target_date,                    # $3
                request.locationId or request.location,  # $4
                request.appointmentType,        # $5
                clinic.timezone                 # $6
            )
            
            data = result if isinstance(result, dict) else {}
            
        # Check if practitioner was found
        if not data.get('practitioner'):
            all_practitioners = data.get('all_practitioners', [])
            practitioner_names = [p['name'] for p in all_practitioners] if all_practitioners else []
            
            return {
                "success": False,
                "error": "practitioner_not_found",
                "message": f"I couldn't find a practitioner named '{request.practitioner}'.",
                "suggestions": practitioner_names[:3] if practitioner_names else [],
                "sessionId": request.sessionId
            }
        
        # Format response based on availability
        slots = data.get('slots', [])
        summary = data.get('summary', {})
        practitioner_name = data['practitioner']['name']
        
        if not slots:
            return {
                "success": True,
                "sessionId": request.sessionId,
                "practitioner": practitioner_name,
                "date": target_date.strftime("%Y-%m-%d"),
                "slots": [],
                "message": f"{practitioner_name} doesn't have any available appointments on {target_date.strftime('%A, %B %d')}.",
                "availability_level": "none"
            }
        
        # Create conversational summary
        total_slots = summary.get('total_slots', 0)
        availability_level = summary.get('availability_level', 'limited availability')
        
        # Build natural language message
        if total_slots <= 3:
            # Few slots - list specific times
            time_list = [slot['display_time'] for slot in slots[:3]]
            message = f"{practitioner_name} has {total_slots} appointment{'s' if total_slots > 1 else ''} available on {target_date.strftime('%A, %B %d')}: {', '.join(time_list)}."
        else:
            # Many slots - give summary
            periods = set(summary.get('time_periods', []))
            period_text = " and ".join(sorted(periods))
            message = f"{practitioner_name} has {availability_level} on {target_date.strftime('%A, %B %d')} with appointments in the {period_text}."
            
            # Add location info if multiple
            locations = summary.get('locations', [])
            if len(locations) > 1:
                message += f" Available at {' and '.join(locations)}."
        
        return {
            "success": True,
            "sessionId": request.sessionId,
            "practitioner": practitioner_name,
            "date": target_date.strftime("%Y-%m-%d"),
            "dateDisplay": target_date.strftime("%A, %B %d, %Y"),
            "slots": slots,
            "message": message,
            "availability_level": availability_level,
            "summary": {
                "total": total_slots,
                "first_available": format_time_for_voice(datetime.fromisoformat(str(summary['first_slot']))) if summary.get('first_slot') else None,
                "last_available": format_time_for_voice(datetime.fromisoformat(str(summary['last_slot']))) if summary.get('last_slot') else None,
                "locations": summary.get('locations', [])
            }
        }
        
    except Exception as e:
        logger.error(f"Availability check failed: {str(e)}", exc_info=True)
        
        return {
            "success": False,
            "error": "internal_error",
            "message": "I'm having trouble checking availability right now. Please try again.",
            "sessionId": request.sessionId
        }