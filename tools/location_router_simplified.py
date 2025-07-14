# tools/location_router_simplified.py
"""Simplified location resolver using PostgreSQL fuzzy matching"""

from fastapi import APIRouter, Depends
from typing import Dict, Any, List, Optional
import logging
from models import LocationResolverRequest
from .dependencies import verify_api_key, get_db, get_cache
from database import get_clinic_by_dialed_number
from payload_logger import payload_logger
from utils import normalize_phone, mask_phone

logger = logging.getLogger(__name__)
router = APIRouter(tags=["location"])

@router.post("/location-resolver")
async def resolve_location(
    request: LocationResolverRequest,
    authenticated: bool = Depends(verify_api_key)
) -> Dict[str, Any]:
    """Resolve location using PostgreSQL's similarity functions"""
    
    payload_logger.log_payload("/location-resolver", request.dict())
    
    try:
        logger.info(f"=== LOCATION RESOLUTION START ===")
        logger.info(f"Session: {request.sessionId}")
        logger.info(f"Query: '{request.locationQuery}'")
        logger.info(f"Caller: {mask_phone(request.callerPhone) if request.callerPhone else 'Unknown'}")
        
        # Get database pool
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
        
        # Single query for location resolution with fuzzy matching
        location_query = """
        WITH caller_history AS (
            -- Get caller's previous booking locations
            SELECT 
                a.business_id,
                b.business_name,
                COUNT(*) as visit_count,
                MAX(a.created_at) as last_visit
            FROM appointments a
            JOIN businesses b ON a.business_id = b.business_id
            JOIN patients p ON a.patient_id = p.patient_id
            WHERE p.phone_number = $3
                AND a.clinic_id = $1
                AND a.status NOT IN ('cancelled', 'no_show')
            GROUP BY a.business_id, b.business_name
        ),
        location_matches AS (
            SELECT 
                b.business_id,
                b.business_name,
                b.is_primary,
                COALESCE(ch.visit_count, 0) as visit_count,
                ch.last_visit,
                -- Calculate match scores
                GREATEST(
                    -- Direct similarity to business name
                    similarity(LOWER(b.business_name), LOWER($2)),
                    -- Match against aliases
                    COALESCE((
                        SELECT MAX(similarity(LOWER(la.alias), LOWER($2)))
                        FROM location_aliases la
                        WHERE la.business_id = b.business_id
                    ), 0),
                    -- Special keywords
                    CASE 
                        WHEN b.is_primary AND LOWER($2) IN ('main', 'primary', 'main clinic', 'your clinic') THEN 0.9
                        WHEN LOWER($2) IN ('my usual', 'usual place', 'normal place') AND ch.visit_count > 0 THEN 0.95
                        ELSE 0
                    END
                ) as match_score,
                -- Matching details for debugging
                json_build_object(
                    'name_similarity', similarity(LOWER(b.business_name), LOWER($2)),
                    'is_primary', b.is_primary,
                    'visit_count', COALESCE(ch.visit_count, 0),
                    'matched_alias', (
                        SELECT alias 
                        FROM location_aliases la 
                        WHERE la.business_id = b.business_id 
                            AND similarity(LOWER(la.alias), LOWER($2)) > 0.3
                        ORDER BY similarity(LOWER(la.alias), LOWER($2)) DESC
                        LIMIT 1
                    )
                ) as match_details
            FROM businesses b
            LEFT JOIN caller_history ch ON b.business_id = ch.business_id
            WHERE b.clinic_id = $1
                AND (
                    -- Include all for generic queries
                    LOWER($2) IN ('', 'location', 'clinic', 'office', 'any', 'anywhere')
                    -- Similarity matching
                    OR similarity(LOWER(b.business_name), LOWER($2)) > 0.2
                    -- Alias matching
                    OR EXISTS (
                        SELECT 1 FROM location_aliases la 
                        WHERE la.business_id = b.business_id 
                            AND similarity(LOWER(la.alias), LOWER($2)) > 0.2
                    )
                    -- Special keywords
                    OR (b.is_primary AND LOWER($2) IN ('main', 'primary', 'main clinic'))
                    OR (ch.visit_count > 0 AND LOWER($2) IN ('my usual', 'usual place'))
                )
        ),
        result_summary AS (
            SELECT 
                COUNT(*) as total_matches,
                MAX(match_score) as best_score,
                COUNT(*) FILTER (WHERE match_score >= 0.8) as high_confidence_matches,
                COUNT(*) FILTER (WHERE match_score >= 0.5 AND match_score < 0.8) as medium_confidence_matches
            FROM location_matches
        )
        SELECT json_build_object(
            'matches', COALESCE(
                json_agg(
                    json_build_object(
                        'business_id', business_id,
                        'business_name', business_name,
                        'is_primary', is_primary,
                        'match_score', match_score,
                        'visit_count', visit_count,
                        'match_details', match_details
                    ) ORDER BY match_score DESC, visit_count DESC, is_primary DESC
                ),
                '[]'::json
            ),
            'summary', (SELECT row_to_json(rs) FROM result_summary rs),
            'all_locations', (
                SELECT json_agg(
                    json_build_object(
                        'business_id', business_id,
                        'business_name', business_name,
                        'is_primary', is_primary
                    ) ORDER BY is_primary DESC, business_name
                )
                FROM businesses
                WHERE clinic_id = $1
            )
        ) as result
        FROM location_matches
        WHERE match_score > 0
        """
        
        # Normalize caller phone for history lookup
        caller_phone = normalize_phone(request.callerPhone) if request.callerPhone else None
        
        async with pool.acquire() as conn:
            result = await conn.fetchval(
                location_query,
                clinic.clinic_id,           # $1
                request.locationQuery,      # $2
                caller_phone               # $3
            )
            
            data = result if isinstance(result, dict) else {'matches': [], 'summary': {}, 'all_locations': []}
        
        matches = data.get('matches', [])
        summary = data.get('summary', {})
        all_locations = data.get('all_locations', [])
        
        # No matches at all - provide all options
        if not matches:
            location_names = [loc['business_name'] for loc in all_locations]
            
            if len(location_names) == 0:
                message = "I couldn't find any locations for this clinic."
            elif len(location_names) == 1:
                # Single location clinic
                return {
                    "success": True,
                    "sessionId": request.sessionId,
                    "action_completed": True,
                    "needs_clarification": False,
                    "message": f"I'll book you at our {location_names[0]} location.",
                    "business_id": all_locations[0]['business_id'],
                    "business_name": location_names[0],
                    "confidence": 1.0
                }
            else:
                message = f"I couldn't understand which location you meant. We have: {', '.join(location_names)}. Which would you prefer?"
            
            return {
                "success": True,
                "sessionId": request.sessionId,
                "action_completed": False,
                "needs_clarification": True,
                "message": message,
                "options": location_names,
                "confidence": 0.0
            }
        
        # Get best match
        best_match = matches[0]
        best_score = best_match['match_score']
        
        # High confidence match (>= 0.8)
        if best_score >= 0.8:
            # Check if caller has history at this location
            visit_count = best_match.get('visit_count', 0)
            if visit_count > 0:
                message = f"I'll book you at {best_match['business_name']}, where you've been before."
            else:
                message = f"I'll book you at our {best_match['business_name']} location."
            
            # Update caller's booking context
            if caller_phone:
                context = await cache.get_booking_context(caller_phone) or {}
                context['preferred_location'] = {
                    'business_id': best_match['business_id'],
                    'business_name': best_match['business_name']
                }
                await cache.set_booking_context(caller_phone, clinic.clinic_id, context)
            
            return {
                "success": True,
                "sessionId": request.sessionId,
                "action_completed": True,
                "needs_clarification": False,
                "message": message,
                "business_id": best_match['business_id'],
                "business_name": best_match['business_name'],
                "confidence": best_score
            }
        
        # Medium confidence (0.5 - 0.8) - confirm
        elif best_score >= 0.5:
            return {
                "success": True,
                "sessionId": request.sessionId,
                "action_completed": False,
                "needs_clarification": True,
                "message": f"Did you mean our {best_match['business_name']} location?",
                "options": [best_match['business_name']],
                "confidence": best_score
            }
        
        # Low confidence - multiple options
        else:
            # Get top 3 matches or all if less than 3
            top_matches = matches[:3]
            options = [m['business_name'] for m in top_matches]
            
            if len(options) == 1:
                message = f"Did you mean {options[0]}?"
            elif len(options) == 2:
                message = f"Did you mean {options[0]} or {options[1]}?"
            else:
                message = f"We have several locations. Did you mean: {', '.join(options)}?"
            
            return {
                "success": True,
                "sessionId": request.sessionId,
                "action_completed": False,
                "needs_clarification": True,
                "message": message,
                "options": options,
                "confidence": best_score
            }
        
    except Exception as e:
        logger.error(f"Location resolution failed: {str(e)}", exc_info=True)
        
        return {
            "success": False,
            "error": "internal_error",
            "message": "I'm having trouble finding our locations right now. Please try again.",
            "sessionId": request.sessionId
        }