# tools/practitioner_router_simplified.py
"""Simplified practitioner services using direct SQL"""

from fastapi import APIRouter, Depends
from typing import Dict, Any, List
import logging
from pydantic import BaseModel
from .dependencies import verify_api_key, get_db
from database import get_clinic_by_dialed_number
from payload_logger import payload_logger

logger = logging.getLogger(__name__)
router = APIRouter(tags=["practitioner"])

class GetPractitionerServicesRequest(BaseModel):
    practitioner: str
    sessionId: str
    dialedNumber: str
    callerPhone: str = None

@router.post("/get-practitioner-services")
async def get_practitioner_services(
    request: GetPractitionerServicesRequest,
    authenticated: bool = Depends(verify_api_key)
) -> Dict[str, Any]:
    """Get practitioner services with single optimized query"""
    
    payload_logger.log_payload("/get-practitioner-services", request.dict())
    
    try:
        logger.info(f"=== GET PRACTITIONER SERVICES START ===")
        logger.info(f"Session: {request.sessionId}")
        logger.info(f"Practitioner: '{request.practitioner}'")
        
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
        
        # Single query to get practitioner and all their services
        services_query = """
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
                ) as match_score,
                p.active
            FROM practitioners p
            WHERE p.clinic_id = $1
                AND (
                    LOWER(p.first_name) = LOWER($2)
                    OR LOWER(p.last_name) = LOWER($2)
                    OR LOWER(p.first_name || ' ' || p.last_name) = LOWER($2)
                    OR similarity(
                        LOWER(COALESCE(p.title || ' ', '') || p.first_name || ' ' || p.last_name),
                        LOWER($2)
                    ) > 0.3
                )
            ORDER BY 
                p.active DESC,  -- Prefer active practitioners
                match_score DESC
            LIMIT 1
        ),
        practitioner_services AS (
            -- Get all services for the practitioner
            SELECT 
                mp.practitioner_id,
                mp.full_name,
                mp.first_name,
                mp.active,
                at.appointment_type_id,
                at.name as service_name,
                at.duration_minutes,
                bi.price,
                -- Group services by category
                CASE 
                    WHEN at.name ILIKE '%initial%' OR at.name ILIKE '%first%' OR at.name ILIKE '%new%' 
                        THEN 'New Patient'
                    WHEN at.name ILIKE '%follow%' OR at.name ILIKE '%return%' OR at.name ILIKE '%subsequent%'
                        THEN 'Follow Up'
                    WHEN at.name ILIKE '%massage%' THEN 'Massage'
                    WHEN at.name ILIKE '%acupuncture%' THEN 'Acupuncture'
                    WHEN at.name ILIKE '%consult%' THEN 'Consultation'
                    ELSE 'General'
                END as category,
                -- Common service keywords for voice
                array_remove(array[
                    CASE WHEN at.name ILIKE '%60%' OR at.duration_minutes = 60 THEN '60 minute' END,
                    CASE WHEN at.name ILIKE '%30%' OR at.duration_minutes = 30 THEN '30 minute' END,
                    CASE WHEN at.name ILIKE '%45%' OR at.duration_minutes = 45 THEN '45 minute' END,
                    CASE WHEN at.name ILIKE '%90%' OR at.duration_minutes = 90 THEN '90 minute' END,
                    CASE WHEN at.name ILIKE '%initial%' THEN 'initial' END,
                    CASE WHEN at.name ILIKE '%follow%' THEN 'follow up' END
                ], NULL) as keywords
            FROM matched_practitioner mp
            JOIN practitioner_appointment_types pat ON mp.practitioner_id = pat.practitioner_id
            JOIN appointment_types at ON pat.appointment_type_id = at.appointment_type_id
            LEFT JOIN billable_items bi ON at.billable_item_id = bi.item_id
            WHERE at.active = true
        ),
        service_summary AS (
            -- Summarize services for voice response
            SELECT 
                COUNT(*) as total_services,
                COUNT(DISTINCT category) as category_count,
                array_agg(DISTINCT category ORDER BY category) as categories,
                MIN(duration_minutes) as min_duration,
                MAX(duration_minutes) as max_duration,
                bool_or(category = 'New Patient') as has_new_patient,
                bool_or(category = 'Follow Up') as has_follow_up
            FROM practitioner_services
        ),
        suggested_practitioners AS (
            -- Get other practitioners if this one is inactive
            SELECT array_agg(
                COALESCE(title || ' ', '') || first_name || ' ' || last_name
                ORDER BY active DESC, last_name, first_name
            ) as other_practitioners
            FROM practitioners
            WHERE clinic_id = $1
                AND active = true
                AND practitioner_id != COALESCE((SELECT practitioner_id FROM matched_practitioner), '')
            LIMIT 3
        )
        SELECT json_build_object(
            'practitioner', (
                SELECT json_build_object(
                    'id', practitioner_id,
                    'name', full_name,
                    'first_name', first_name,
                    'active', active,
                    'match_score', match_score
                )
                FROM matched_practitioner
            ),
            'services', COALESCE(
                (
                    SELECT json_agg(
                        json_build_object(
                            'id', appointment_type_id,
                            'name', service_name,
                            'duration', duration_minutes,
                            'price', price,
                            'category', category,
                            'keywords', keywords
                        ) ORDER BY category, service_name
                    )
                    FROM practitioner_services
                ),
                '[]'::json
            ),
            'summary', (
                SELECT row_to_json(s) FROM service_summary s
            ),
            'suggestions', (
                SELECT other_practitioners FROM suggested_practitioners
            )
        ) as result
        """
        
        async with pool.acquire() as conn:
            result = await conn.fetchval(
                services_query,
                clinic.clinic_id,      # $1
                request.practitioner   # $2
            )
            
            data = result if isinstance(result, dict) else {}
        
        # Check if practitioner was found
        if not data.get('practitioner'):
            suggestions = data.get('suggestions', [])
            return {
                "success": False,
                "error": "practitioner_not_found",
                "message": f"I couldn't find a practitioner named '{request.practitioner}'.",
                "suggestions": suggestions[:3] if suggestions else [],
                "sessionId": request.sessionId
            }
        
        practitioner = data['practitioner']
        services = data.get('services', [])
        summary = data.get('summary', {})
        
        # Check if practitioner is inactive
        if not practitioner.get('active'):
            suggestions = data.get('suggestions', [])
            message = f"{practitioner['name']} is no longer taking appointments."
            if suggestions:
                message += f" You might want to see: {', '.join(suggestions[:2])}."
            
            return {
                "success": False,
                "error": "practitioner_inactive",
                "message": message,
                "suggestions": suggestions[:3],
                "sessionId": request.sessionId
            }
        
        # No services configured
        if not services:
            return {
                "success": True,
                "sessionId": request.sessionId,
                "practitioner": practitioner['name'],
                "practitionerId": practitioner['id'],
                "services": [],
                "message": f"{practitioner['name']} doesn't have any services configured.",
                "serviceNames": []
            }
        
        # Format service names for voice
        service_names = [s['name'] for s in services]
        
        # Build conversational message
        total = summary.get('total_services', 0)
        categories = summary.get('categories', [])
        
        if total == 1:
            message = f"{practitioner['name']} offers {service_names[0]}."
        elif total <= 3:
            # List all services
            if total == 2:
                message = f"{practitioner['name']} offers {service_names[0]} and {service_names[1]}."
            else:
                message = f"{practitioner['name']} offers {', '.join(service_names[:-1])}, and {service_names[-1]}."
        else:
            # Summarize by category
            if len(categories) == 1:
                message = f"{practitioner['name']} offers {total} {categories[0].lower()} services."
            else:
                message = f"{practitioner['name']} offers {total} services including {', '.join(categories[:-1]).lower()}, and {categories[-1].lower()}."
            
            # Add duration info if varied
            min_dur = summary.get('min_duration')
            max_dur = summary.get('max_duration')
            if min_dur and max_dur and min_dur != max_dur:
                message += f" Sessions range from {min_dur} to {max_dur} minutes."
        
        # Add special note for acupuncture
        if summary.get('has_new_patient') and summary.get('has_follow_up'):
            for service in services:
                if 'acupuncture' in service['name'].lower():
                    message += " For acupuncture, please specify if you're a new or returning patient."
                    break
        
        return {
            "success": True,
            "sessionId": request.sessionId,
            "practitioner": practitioner['name'],
            "practitionerId": practitioner['id'],
            "services": service_names,
            "serviceDetails": services,
            "message": message,
            "serviceNames": service_names,  # Backward compatibility
            "categories": categories,
            "summary": {
                "total": total,
                "hasNewPatient": summary.get('has_new_patient', False),
                "hasFollowUp": summary.get('has_follow_up', False),
                "durationRange": f"{min_dur}-{max_dur} minutes" if min_dur != max_dur else f"{min_dur} minutes"
            }
        }
        
    except Exception as e:
        logger.error(f"Get practitioner services failed: {str(e)}", exc_info=True)
        
        return {
            "success": False,
            "error": "internal_error",
            "message": "I'm having trouble retrieving service information right now. Please try again.",
            "sessionId": request.sessionId
        }