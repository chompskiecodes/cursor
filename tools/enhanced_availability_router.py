"""
Enhanced Availability Router with Parallel Processing

This router provides enhanced availability checking endpoints using the new parallel manager
for improved performance and reliability.
"""

import asyncio
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta, date
from fastapi import APIRouter, Request, Depends, BackgroundTasks
import asyncpg

from tools.enhanced_parallel_manager import EnhancedParallelManager
from tools.dependencies import verify_api_key, get_db, get_cache
from database import get_clinic_by_dialed_number
from utils import parse_date_request
from tools.timezone_utils import get_clinic_timezone
from models import ClinicData
from tools.shared import get_scheduled_working_days

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/enhanced", tags=["Enhanced Availability"])

@router.post("/find-next-available")
async def enhanced_find_next_available(
    request: Request,
    authenticated: bool = Depends(verify_api_key)
) -> Dict[str, Any]:
    """
    Enhanced find-next-available endpoint using parallel processing
    
    This endpoint provides the same functionality as the original find-next-available
    but with improved performance through parallel processing and enhanced error handling.
    """
    
    logger.info("=== ENHANCED FIND NEXT AVAILABLE START ===")
    
    try:
        start_time = datetime.now()
        body = await request.json()
        logger.info(f"Request body: {body}")
        
        # Extract parameters
        service_name = body.get('service') or body.get('appointmentType')
        practitioner_name = body.get('practitioner')
        business_id = body.get('business_id')
        business_name = body.get('businessName')
        max_days = body.get('maxDays', 14)
        dialed_number = body.get('dialedNumber', '')
        session_id = body.get('sessionId', '')
        
        logger.info(f"Parsed inputs - service: {service_name}, practitioner: {practitioner_name}, dialed_number: {dialed_number}")
        
        # Get database pool and cache
        pool = await get_db()
        cache = await get_cache()
        
        # Get clinic
        clinic = await get_clinic_by_dialed_number(dialed_number, pool)
        if not clinic:
            logger.error(f"Clinic not found for dialed number: {dialed_number}")
            return {
                "success": False,
                "message": "I couldn't find the clinic information.",
                "sessionId": session_id
            }
        
        logger.info(f"Found clinic: {clinic.clinic_name}")
        
        # Build search criteria
        search_criteria = await build_search_criteria(
            service_name, practitioner_name, business_id, clinic, pool
        )
        
        if not search_criteria:
            return {
                "success": False,
                "message": "I couldn't find any matching practitioners or services.",
                "sessionId": session_id
            }
        
        logger.info(f"Built {len(search_criteria)} search criteria")
        
        # Create enhanced parallel manager
        parallel_manager = EnhancedParallelManager(pool, cache, clinic)
        
        # Use clinic's timezone for search start
        clinic_tz = get_clinic_timezone(clinic)
        search_start = datetime.now(clinic_tz).date()
        date_range = [search_start + timedelta(days=i) for i in range(max_days)]
        print('Date range for scheduled working days:', date_range)
        async with pool.acquire() as conn:
            filtered_criteria = []
            for crit in search_criteria:
                scheduled_dates = await get_scheduled_working_days(
                    conn,
                    crit['practitioner_id'],
                    crit['business_id'],
                    date_range
                )
                for d in scheduled_dates:
                    crit_copy = crit.copy()
                    crit_copy['check_date'] = d
                    filtered_criteria.append(crit_copy)
        print('Filtered criteria for parallel check:')
        for crit in filtered_criteria:
            print(crit)
        # Pass filtered_criteria directly to parallel_manager (no extra day loop)
        result = await parallel_manager.check_availability_parallel(
            search_criteria=filtered_criteria,
            max_days=1,  # Each criteria already has a specific date
            session_id=session_id
        )
        execution_time = (datetime.now() - start_time).total_seconds()
        
        # Add performance metrics to response
        metrics = parallel_manager.get_metrics()
        result['performance_metrics'] = {
            'execution_time': execution_time,
            'total_calls': metrics.total_calls,
            'successful_calls': metrics.successful_calls,
            'failed_calls': metrics.failed_calls,
            'cache_hits': metrics.cache_hits,
            'average_duration': metrics.average_duration,
            'rate_limit_delays': metrics.rate_limit_delays,
            'success_rate': (metrics.successful_calls / metrics.total_calls) * 100 if metrics.total_calls > 0 else 0
        }
        
        logger.info(f"=== ENHANCED FIND NEXT AVAILABLE COMPLETE in {execution_time:.2f}s ===")
        
        return result
        
    except Exception as e:
        logger.error(f"Error in enhanced find-next-available: {str(e)}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        print(traceback.format_exc())
        return {
            "success": False,
            "message": "I encountered an error while checking availability. Please try again.",
            "sessionId": session_id
        }

@router.post("/get-available-practitioners")
async def enhanced_get_available_practitioners(
    request: Request,
    authenticated: bool = Depends(verify_api_key)
) -> Dict[str, Any]:
    """
    Enhanced get-available-practitioners endpoint using parallel processing
    
    This endpoint provides the same functionality as the original get-available-practitioners
    but with improved performance through parallel processing.
    """
    print("=== ENTERED ENHANCED GET AVAILABLE PRACTITIONERS ENDPOINT ===")
    logger.info("=== ENHANCED GET AVAILABLE PRACTITIONERS START ===")
    
    try:
        print("[DEBUG] Step 1: Parsing request body")
        body = await request.json()
        logger.info(f"Request body: {body}")
        
        business_id = body.get('business_id', '')
        business_name = body.get('businessName', '')
        date_str = body.get('date', 'today')
        dialed_number = body.get('dialedNumber', '')
        session_id = body.get('sessionId', '')
        
        print("[DEBUG] Step 2: Getting DB and cache")
        pool = await get_db()
        cache = await get_cache()
        
        print("[DEBUG] Step 3: Getting clinic")
        clinic = await get_clinic_by_dialed_number(dialed_number, pool)
        if not clinic:
            print("[DEBUG] No clinic found, returning error")
            logger.error(f"Clinic not found for dialed number: {dialed_number}")
            return {
                "success": False,
                "message": "I couldn't find the clinic information.",
                "sessionId": session_id
            }
        logger.info(f"Found clinic: {clinic.clinic_name}")
        
        print("[DEBUG] Step 4: Parsing date")
        clinic_tz = get_clinic_timezone(clinic)
        check_date = parse_date_request(date_str, clinic_tz)
        from_date = check_date.isoformat()
        to_date = check_date.isoformat()
        logger.info(f"Checking availability for date: {from_date}")
        
        print("[DEBUG] Step 5: Fetching practitioners at business")
        practitioners_data = await get_practitioners_at_business(business_id, clinic.clinic_id, pool)
        print(f"[DEBUG] Practitioners data: {practitioners_data}")
        
        if not practitioners_data:
            print("[DEBUG] No practitioners found, returning error")
            return {
                "success": False,
                "message": f"No practitioners found at {business_name}.",
                "sessionId": session_id
            }
        logger.info(f"Found {len(practitioners_data)} practitioners at {business_name}")
        logger.info(f"Practitioners being checked:")
        for prac_id, prac_data in practitioners_data.items():
            logger.info(f"  Practitioner ID: {prac_id}, Name: {prac_data['name']}")
        
        print("[DEBUG] Step 6: Filtering by scheduled working days")
        # Build a full week date range (Monday to Sunday) containing check_date
        week_start = check_date - timedelta(days=check_date.weekday())  # Monday
        week_dates = [week_start + timedelta(days=i) for i in range(7)]
        async with pool.acquire() as conn:
            filtered_practitioners = {}
            practitioner_allowed_dates = {}
            for prac_id, prac_data in practitioners_data.items():
                allowed_dates = await get_scheduled_working_days(
                    conn,
                    prac_id,
                    business_id,
                    week_dates
                )
                print(f"[DEBUG] Practitioner {prac_data['name']} (ID: {prac_id}) scheduled working days for business {business_name} ({business_id}): {allowed_dates}")
                if allowed_dates:
                    filtered_practitioners[prac_id] = prac_data
                    practitioner_allowed_dates[prac_id] = allowed_dates
        print(f"[DEBUG] Filtered practitioners: {filtered_practitioners}")
        print(f"[DEBUG] Practitioner allowed dates: {practitioner_allowed_dates}")
        print("[DEBUG] Step 7: Building search criteria")
        search_criteria = []
        for prac_id, prac_data in filtered_practitioners.items():
            allowed_dates = practitioner_allowed_dates[prac_id]
            for allowed_date in allowed_dates:
            for service in prac_data['services']:
                search_criteria.append({
                    'practitioner_id': prac_id,
                    'practitioner_name': prac_data['name'],
                    'appointment_type_id': service['appointment_type_id'],
                    'service_name': service['name'],
                    'business_id': business_id,
                        'business_name': business_name,
                        'date': allowed_date
                })
        print(f"[DEBUG] Search criteria: {search_criteria}")
        logger.info(f"Created {len(search_criteria)} search criteria")
        
        print("[DEBUG] Step 8: Running parallel manager")
        start_time = datetime.now()
        parallel_manager = EnhancedParallelManager(pool, cache, clinic)
        result = await parallel_manager.check_availability_parallel(
            search_criteria=search_criteria,
            max_days=1,  # Only check the specified date
            session_id=session_id
        )
        execution_time = (datetime.now() - start_time).total_seconds()
        print(f"[DEBUG] Raw result from parallel_manager: {result}")
        logger.info(f"Raw result from parallel_manager.check_availability_parallel:")
        logger.info(result)
        
        print("[DEBUG] Step 9: Processing results")
        # Aggregate available practitioners directly from all_slots
        available_practitioners = []
        prac_map = {}
        all_slots = result.get('all_slots') if result else None
        if all_slots:
            for slot_tuple in all_slots:
                # slot_tuple: (dt, slot_dict, criteria_dict, date, 'cache' or 'api')
                slot_info = slot_tuple[2] if len(slot_tuple) > 2 else None
                if not slot_info:
                    continue
                prac_id = slot_info.get('practitioner_id')
                prac_name = slot_info.get('practitioner_name')
                service_name = slot_info.get('service_name')
                if not prac_id or not prac_name or not service_name:
                    continue
                if prac_id not in prac_map:
                    prac_map[prac_id] = {
                        'id': prac_id,
                        'name': prac_name,
                        'available_services': set()
                    }
                prac_map[prac_id]['available_services'].add(service_name)
            for prac in prac_map.values():
                prac['available_services'] = list(prac['available_services'])
                available_practitioners.append(prac)
        print(f"[DEBUG] Available practitioners: {available_practitioners}")
        
        print("[DEBUG] Step 10: Formatting response")
        response = {
            "success": True,
            "message": format_available_practitioners_message(available_practitioners, check_date, business_name),
            "sessionId": session_id,
            "available_practitioners": available_practitioners,
            "date": check_date.strftime("%A, %B %d, %Y"),
            "location": business_name,
            "performance_metrics": {
                'execution_time': execution_time,
                'total_calls': parallel_manager.get_metrics().total_calls,
                'successful_calls': parallel_manager.get_metrics().successful_calls,
                'cache_hits': parallel_manager.get_metrics().cache_hits,
                'success_rate': (parallel_manager.get_metrics().successful_calls / parallel_manager.get_metrics().total_calls) * 100 if parallel_manager.get_metrics().total_calls > 0 else 0
            }
        }
        print(f"[DEBUG] Final response: {response}")
        logger.info(f"=== ENHANCED GET AVAILABLE PRACTITIONERS COMPLETE in {execution_time:.2f}s ===")
        return response
        
    except Exception as e:
        print("[DEBUG] Exception occurred in enhanced_get_available_practitioners")
        import traceback
        print(traceback.format_exc())
        logger.error(f"Error in enhanced get-available-practitioners: {str(e)}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        return {
            "success": False,
            "message": "I encountered an error while checking practitioner availability. Please try again.",
            "sessionId": session_id
        }

async def build_search_criteria(
    service_name: Optional[str],
    practitioner_name: Optional[str],
    business_id: Optional[str],
    clinic: ClinicData,
    pool: asyncpg.Pool
) -> List[Dict[str, Any]]:
    """Build search criteria for availability checking"""
    
    logger.info(f"=== BUILD SEARCH CRITERIA DEBUG ===")
    logger.info(f"Input parameters:")
    logger.info(f"  service_name: {service_name}")
    logger.info(f"  practitioner_name: {practitioner_name}")
    logger.info(f"  business_id: {business_id}")
    logger.info(f"  clinic_id: {clinic.clinic_id}")
    logger.info(f"  clinic_name: {clinic.clinic_name}")
    
    search_criteria = []
    
    # Use the same matching logic as the sequential endpoint
    if practitioner_name:
        from database import match_practitioner
        practitioner_match = await match_practitioner(clinic.clinic_id, practitioner_name, pool)
        
        if not practitioner_match or not practitioner_match.get('matches'):
            logger.warning(f"No practitioner matches found for: {practitioner_name}")
            return []
        
        # Get the first/best match
        practitioner = practitioner_match['matches'][0]
        logger.info(f"Found practitioner: {practitioner['full_name']}")
        
        # Get all services for this practitioner
        from database import get_practitioner_services
        services = await get_practitioner_services(clinic.clinic_id, pool)
        practitioner_services = [s for s in services if s['practitioner_id'] == practitioner['practitioner_id']]
        
        # Filter by service if specified
        if service_name:
            from database import match_service
            matched_service = await match_service(clinic.clinic_id, practitioner['practitioner_id'], service_name, pool)
            if matched_service:
                practitioner_services = [matched_service]
            else:
                logger.warning(f"No service match found for: {service_name}")
                return []
        
        # Build search criteria for each service
        for service in practitioner_services:
            # Get all locations where this practitioner works
            query = """
                SELECT DISTINCT pb.business_id, b.business_name
                FROM practitioner_businesses pb
                JOIN businesses b ON pb.business_id = b.business_id
                WHERE pb.practitioner_id = $1 AND b.clinic_id = $2
            """
            
            async with pool.acquire() as conn:
                location_rows = await conn.fetch(query, practitioner['practitioner_id'], clinic.clinic_id)
            
            # Filter by business if specified
            if business_id:
                location_rows = [row for row in location_rows if row['business_id'] == business_id]
                if not location_rows:
                    logger.warning(f"Practitioner {practitioner['full_name']} not found at business {business_id}")
                    return []
            
            for location_row in location_rows:
                search_criteria.append({
                    'practitioner_id': practitioner['practitioner_id'],
                    'practitioner_name': practitioner['full_name'],
                    'appointment_type_id': service['appointment_type_id'],
                    'service_name': service['service_name'],
                    'business_id': location_row['business_id'],
                    'business_name': location_row['business_name']
                })
    
    else:
        # No practitioner specified - get all practitioners and services
        from database import get_practitioner_services
        services = await get_practitioner_services(clinic.clinic_id, pool)
        
        # Filter by service if specified
        if service_name:
            services = [s for s in services if service_name.lower() in s['service_name'].lower()]
        
        # Group by practitioner and location
        for service in services:
            # Get all locations where this practitioner works
            query = """
                SELECT DISTINCT pb.business_id, b.business_name
                FROM practitioner_businesses pb
                JOIN businesses b ON pb.business_id = b.business_id
                WHERE pb.practitioner_id = $1 AND b.clinic_id = $2
            """
            
            async with pool.acquire() as conn:
                location_rows = await conn.fetch(query, service['practitioner_id'], clinic.clinic_id)
            
            # Filter by business if specified
            if business_id:
                location_rows = [row for row in location_rows if row['business_id'] == business_id]
            
            for location_row in location_rows:
                search_criteria.append({
                    'practitioner_id': service['practitioner_id'],
                    'practitioner_name': service['practitioner_name'],
                    'appointment_type_id': service['appointment_type_id'],
                    'service_name': service['service_name'],
                    'business_id': location_row['business_id'],
                    'business_name': location_row['business_name']
                })
    
    logger.info(f"=== END BUILD SEARCH CRITERIA DEBUG ===")
    logger.info(f"Created {len(search_criteria)} search criteria")
    
    return search_criteria

async def get_practitioners_at_business(
    business_id: str,
    clinic_id: str,
    pool: asyncpg.Pool
) -> Dict[str, Dict[str, Any]]:
    """Get all practitioners and their services at a specific business"""
    
    query = """
        SELECT DISTINCT
            p.practitioner_id,
            CASE 
                WHEN p.title IS NOT NULL AND p.title != '' 
                THEN CONCAT(p.title, ' ', p.first_name, ' ', p.last_name)
                ELSE CONCAT(p.first_name, ' ', p.last_name)
            END as practitioner_name,
            pat.appointment_type_id,
            at.name as service_name,
            p.first_name,
            p.last_name
        FROM practitioners p
        JOIN practitioner_businesses pb ON p.practitioner_id = pb.practitioner_id
        JOIN practitioner_appointment_types pat ON p.practitioner_id = pat.practitioner_id
        JOIN appointment_types at ON pat.appointment_type_id = at.appointment_type_id
        WHERE pb.business_id = $1
          AND p.active = true
          AND p.clinic_id = $2
        ORDER BY p.first_name, p.last_name, at.name
    """
    
    async with pool.acquire() as conn:
        rows = await conn.fetch(query, business_id, clinic_id)
    
    practitioners_data = {}
    for row in rows:
        prac_id = row['practitioner_id']
        if prac_id not in practitioners_data:
            practitioners_data[prac_id] = {
                'name': row['practitioner_name'],
                'services': []
            }
        
        practitioners_data[prac_id]['services'].append({
            'appointment_type_id': row['appointment_type_id'],
            'name': row['service_name']
        })
    
    return practitioners_data

def process_available_practitioners_result(
    result: Dict[str, Any],
    practitioners_data: Dict[str, Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """Process the parallel availability result to extract available practitioners"""
    
    available_practitioners = []
    
    if result.get('found') and result.get('slot'):
        # Extract practitioner from the found slot
        slot_data = result.get('slot', {})
        practitioner_info = result.get('practitioner', {})
        
        available_practitioners.append({
            'practitioner_id': practitioner_info.get('id'),
            'name': practitioner_info.get('name'),
            'firstName': practitioner_info.get('firstName'),
            'services': [result.get('service', 'Unknown')],
            'earliest_time': slot_data.get('time')
        })
    
    return available_practitioners

def format_available_practitioners_message(
    available_practitioners: List[Dict[str, Any]],
    check_date: date,
    business_name: str
) -> str:
    """Format message for available practitioners"""
    
    if not available_practitioners:
        return f"No practitioners are available at {business_name} on {check_date.strftime('%A, %B %d, %Y')}."
    
    practitioner_names = [p['name'] for p in available_practitioners]
    practitioner_list = ', '.join(practitioner_names)
    
    return f"The following practitioners are available at {business_name} on {check_date.strftime('%A, %B %d, %Y')}: {practitioner_list}." 