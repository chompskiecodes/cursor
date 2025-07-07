# tools/practitioner_tools.py
"""Practitioner-related endpoints for the Voice Booking System"""

from fastapi import APIRouter, Request, Depends
from typing import Dict, Any
import logging
import json

# Local imports
from .dependencies import verify_api_key, get_db
from database import (
    get_clinic_by_dialed_number, match_practitioner
)
from models import (
    PractitionerData,
    LocationData,
    PractitionerInfoResponse,
    ServiceData,
    create_error_response
)

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Create router
router = APIRouter(tags=["practitioner"])

@router.post("/get-practitioner-services")
async def get_practitioner_services_for_voice(
    request: Request,
    authenticated: bool = Depends(verify_api_key)
) -> Dict[str, Any]:
    """Get available services for a practitioner - optionally filtered by business/location"""

    body = await request.json()
    business_id = body.get('business_id', '')  # Optional business filter
    practitioner_name = body.get('practitioner', '')
    session_id = body.get('sessionId', '')

    # Get database pool
    pool = await get_db()

    # Get clinic
    clinic = await get_clinic_by_dialed_number(body.get('dialedNumber', ''), pool)
    if not clinic:
        return create_error_response(
            error_code="clinic_not_found",
            message="I couldn't find the clinic information.",
            session_id=session_id
        )

    # Match practitioner with new clarification support
    practitioner_result = await match_practitioner(clinic.clinic_id, practitioner_name, pool)

    # Handle clarification if needed
    if practitioner_result.get("needs_clarification"):
        return {
            "success": True,
            "needs_clarification": True,
            "message": practitioner_result["message"],
            "options": practitioner_result["clarification_options"],
            "sessionId": session_id
        }

    # Handle no matches
    if not practitioner_result.get("matches"):
        return create_error_response(
            error_code="practitioner_not_found",
            message=practitioner_result.get("message", "I couldn't find a practitioner named \"{practitioner_name}\"."),
            session_id=session_id
        )

    # Get the single practitioner (should be only one at this point)
    practitioner = practitioner_result["matches"][0]
    
    # Ensure full_name is available
    if 'full_name' not in practitioner and 'first_name' in practitioner and 'last_name' in practitioner:
        practitioner['full_name'] = f"{practitioner['first_name']} {practitioner['last_name']}"

    # Get services with business filtering if provided
    if business_id:
        # Get services at specific business only
        query = """
            SELECT DISTINCT
                at.appointment_type_id,
                at.name as service_name,
                at.duration_minutes
            FROM practitioner_appointment_types pat
            JOIN appointment_types at ON pat.appointment_type_id = at.appointment_type_id
            JOIN practitioner_businesses pb ON pat.practitioner_id = pb.practitioner_id
            WHERE pat.practitioner_id = $1
              AND pb.business_id = $2
              AND at.active = true
            ORDER BY at.name
        """
        async with pool.acquire() as conn:
            rows = await conn.fetch(query, practitioner['practitioner_id'], business_id)
    else:
        # Get all unique services across all businesses
        query = """
            SELECT DISTINCT
                at.appointment_type_id,
                at.name as service_name,
                at.duration_minutes
            FROM practitioner_appointment_types pat
            JOIN appointment_types at ON pat.appointment_type_id = at.appointment_type_id
            WHERE pat.practitioner_id = $1
              AND at.active = true
            ORDER BY at.name
        """
        async with pool.acquire() as conn:
            rows = await conn.fetch(query, practitioner['practitioner_id'])

    services = [dict(row) for row in rows]

    if not services:
        return create_error_response(
            error_code="no_services",
            message = \
                f"{practitioner['full_name']} doesn't have any services configured{' at this business' if business_id else ''}.",
            session_id=session_id
        )

    # Format response
    service_names = [s['service_name'] for s in services]

    if len(service_names) == 1:
        return create_error_response(
            error_code="single_service",
            message = \
                f"{practitioner['full_name']} offers {service_names[0]}{' at this business' if business_id else ''}.",
            session_id=session_id,
            businessFiltered=bool(business_id)
        )

    # Multiple services
    if len(service_names) == 2:
        message = f"{practitioner['full_name']} offers {service_names[0]} and {service_names[1]}"
    else:
        last = service_names[-1]
        others = service_names[:-1]
        message = f"{practitioner['full_name']} offers {', '.join(others)}, and {last}"

    message += f"{' at this business' if business_id else ''}."

    return {
        "success": True,
        "message": message,
        "practitioner": practitioner['full_name'],
        "services": services,
        "businessFiltered": bool(business_id)
    }

@router.post("/get-practitioner-info")
async def get_practitioner_info(
    request: Request,
    authenticated: bool = Depends(verify_api_key)
) -> Dict[str, Any]:
    """Get comprehensive practitioner info including services and locations"""

    body = await request.json()
    practitioner_name = body.get('practitioner', '')
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

    # Match practitioner with new clarification support
    practitioner_result = await match_practitioner(clinic.clinic_id, practitioner_name, pool)

    # Handle clarification if needed
    if practitioner_result.get("needs_clarification"):
        return {
            "success": True,
            "needs_clarification": True,
            "message": practitioner_result["message"],
            "options": practitioner_result["clarification_options"],
            "sessionId": session_id
        }

    # Handle no matches
    if not practitioner_result.get("matches"):
        return {
            "success": False,
            "message": practitioner_result.get("message", "I couldn't find {practitioner_name}."),
            "sessionId": session_id
        }

    # Get the single practitioner (should be only one at this point)
    practitioner = practitioner_result["matches"][0]
    
    # Ensure full_name is available
    if 'full_name' not in practitioner and 'first_name' in practitioner and 'last_name' in practitioner:
        practitioner['full_name'] = f"{practitioner['first_name']} {practitioner['last_name']}"

    # Get their services and locations
    query = """
        SELECT
            -- Services
            (SELECT array_agg(name) FROM (
                SELECT DISTINCT at.name
                FROM practitioners p
                JOIN practitioner_appointment_types pat ON p.practitioner_id = pat.practitioner_id
                JOIN appointment_types at ON pat.appointment_type_id = at.appointment_type_id
                WHERE p.practitioner_id = $1 AND at.active = true
                ORDER BY at.name
            ) s) as services,
            (SELECT array_agg(jsonb_build_object(
                'id', at.appointment_type_id,
                'name', at.name,
                'duration', at.duration_minutes
            )) FROM (
                SELECT DISTINCT at.appointment_type_id, at.name, at.duration_minutes
                FROM practitioners p
                JOIN practitioner_appointment_types pat ON p.practitioner_id = pat.practitioner_id
                JOIN appointment_types at ON pat.appointment_type_id = at.appointment_type_id
                WHERE p.practitioner_id = $1 AND at.active = true
                ORDER BY at.name
            ) at) as service_details,
            -- Locations
            (SELECT array_agg(business_name) FROM (
                SELECT DISTINCT b.business_name
                FROM practitioners p
                JOIN practitioner_businesses pb ON p.practitioner_id = pb.practitioner_id
                JOIN businesses b ON pb.business_id = b.business_id
                WHERE p.practitioner_id = $1
                ORDER BY b.business_name
            ) l) as locations,
            (SELECT array_agg(jsonb_build_object(
                'id', b.business_id,
                'name', b.business_name
            )) FROM (
                SELECT DISTINCT b.business_id, b.business_name
                FROM practitioners p
                JOIN practitioner_businesses pb ON p.practitioner_id = pb.practitioner_id
                JOIN businesses b ON pb.business_id = b.business_id
                WHERE p.practitioner_id = $1
                ORDER BY b.business_name
            ) b) as location_details
    """

    async with pool.acquire() as conn:
        row = await conn.fetchrow(query, practitioner['practitioner_id'])

    if not row or not row['services']:
        return {
            "success": True,
            "practitioner": practitioner['full_name'],
            "message": f"{practitioner['full_name']} doesn't have any services configured.",
            "sessionId": session_id
        }

    # Parse the JSON arrays from the query
    services = row['services'] or []
    service_details = row['service_details'] or []
    locations = row['locations'] or []
    location_details = row['location_details'] or []

    # Defensive logging
    logger.info(f"[get-practitioner-info] service_details: {service_details} (type: {type(service_details)})")
    for i, s in enumerate(service_details):
        logger.info(f"[get-practitioner-info] service_details[{i}]: {s} (type: {type(s)})")
    logger.info(f"[get-practitioner-info] location_details: {location_details} (type: {type(location_details)})")
    for i, l in enumerate(location_details):
        logger.info(f"[get-practitioner-info] location_details[{i}]: {l} (type: {type(l)})")

    # Parse JSON strings to dicts if needed
    service_details = [json.loads(s) if isinstance(s, str) else s for s in service_details]
    location_details = [json.loads(l) if isinstance(l, str) else l for l in location_details]

    try:
        # Build comprehensive message
        messages = []

        # Services part
        if len(services) == 1:
            service_msg = f"{practitioner['full_name']} offers {services[0]}"
        elif len(services) == 2:
            service_msg = f"{practitioner['full_name']} offers {services[0]} and {services[1]}"
        else:
            last = services[-1]
            others = services[:-1]
            service_msg = f"{practitioner['full_name']} offers {', '.join(others)}, and {last}"

        # Locations part
        if len(locations) == 1:
            location_msg = f"at our {locations[0]}"
        elif len(locations) == 2:
            location_msg = f"at our {locations[0]} and {locations[1]} locations"
        else:
            location_msg = "at multiple locations"

        full_message = f"{service_msg} {location_msg}."

        # Create standardized response
        response = PractitionerInfoResponse(
            success=True,
            sessionId=session_id,
            message=full_message,
            practitioner=PractitionerData(
                id=practitioner['practitioner_id'],
                name=practitioner['full_name'],
                firstName=practitioner.get('first_name', practitioner['full_name'].split()[0] if practitioner['full_name'] else ""),
                servicesCount=len(services)
            ),
            services=[ServiceData(
                id=service['id'],
                name=service['name'],
                duration=service['duration']
            ) for service in service_details if isinstance(service, dict)],
            locations=[LocationData(
                id=location['id'],
                name=location['name']
            ) for location in location_details if isinstance(location, dict)]
        )
        return response.dict()
    except Exception as e:
        logger.error(f"[get-practitioner-info] Exception constructing response: {e}", exc_info=True)
        return {
            "success": False,
            "message": f"Internal error constructing practitioner info: {str(e)}",
            "sessionId": session_id,
            "error": "internal_error"
        }

@router.post("/get-location-practitioners")
async def get_location_practitioners(
    request: Request,
    authenticated: bool = Depends(verify_api_key)
) -> Dict[str, Any]:
    """Get practitioners available at a specific business/location"""
    body = await request.json()
    logger.info(f"/get-location-practitioners payload: {body}")
    print(f"/get-location-practitioners payload: {body}")
    # Handle both field names for compatibility
    business_id = body.get('business_id') or body.get('locationId', '')
    logger.info(f"Resolved business_id: {business_id}")
    print(f"Resolved business_id: {business_id}")
    session_id = body.get('sessionId', '')
    
    # Get database pool
    pool = await get_db()
    
    # Get business name
    query = "SELECT business_name FROM businesses WHERE business_id = $1"
    async with pool.acquire() as conn:
        row = await conn.fetchrow(query, business_id)
    if not row:
        return create_error_response(
            error_code="location_not_found",
            message="I couldn't find the location you're looking for.",
            session_id=session_id
        )
    business_name = row['business_name']
    
    # Get practitioners at this business
    query = """
        SELECT
            p.practitioner_id,
            p.first_name || ' ' || p.last_name AS full_name,
            p.first_name,
            p.last_name,
            (SELECT COUNT(DISTINCT at.appointment_type_id) FROM (
                SELECT DISTINCT at.appointment_type_id
                FROM practitioner_appointment_types pat
                JOIN appointment_types at ON pat.appointment_type_id = at.appointment_type_id
                WHERE pat.practitioner_id = p.practitioner_id AND at.active = true
            ) s) as service_count
        FROM practitioners p
        JOIN practitioner_businesses pb ON p.practitioner_id = pb.practitioner_id
        WHERE pb.business_id = $1
        ORDER BY full_name
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(query, business_id)
    logger.info(f"Practitioner query returned {len(rows)} rows for business_id {business_id}")
    print(f"Practitioner query returned {len(rows)} rows for business_id {business_id}")
    practitioners = [row for row in rows]
    if not practitioners:
        logger.warning(f"No practitioners found for business_id {business_id} (business_name: {business_name})")
        print(f"No practitioners found for business_id {business_id} (business_name: {business_name})")
        return create_error_response(
            error_code="no_practitioners_found",
            message="I couldn't find any practitioners at that location.",
            session_id=session_id
        )
    
    # Create standardized response
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
                name=p['full_name'],
                firstName=p.get('first_name', p['full_name'].split()[0]),
                servicesCount=p.get('service_count', 0)
            )
            for p in practitioners
        ]
    )
    return response.dict()
