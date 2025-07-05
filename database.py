# database.py
import asyncpg
import logging
from typing import Optional, Dict, Any, List
from datetime import date, datetime, timedelta
from models import ClinicData
from utils import normalize_phone, normalize_for_matching, fuzzy_match, mask_phone, parse_date_request, parse_time_request

logger = logging.getLogger(__name__)

# === Database Functions ===
async def get_clinic_by_dialed_number(dialed_number: str, pool: asyncpg.Pool) -> Optional[ClinicData]:
    """Get clinic information by the dialed number"""
    normalized = normalize_phone(dialed_number)
    
    # Simpler query - fetch clinic and businesses separately
    clinic_query = """
        SELECT c.*, c.timezone
        FROM phone_lookup pl
        JOIN clinics c ON pl.clinic_id = c.clinic_id
        WHERE pl.phone_normalized = $1 AND c.active = true
        LIMIT 1
    """
    
    businesses_query = """
        SELECT business_id, business_name, is_primary
        FROM businesses
        WHERE clinic_id = $1
        ORDER BY is_primary DESC, business_name
    """
    
    async with pool.acquire() as conn:
        # Get clinic
        clinic_row = await conn.fetchrow(clinic_query, normalized)
        if not clinic_row:
            return None
            
        # Get businesses
        business_rows = await conn.fetch(businesses_query, clinic_row['clinic_id'])
        
        # Convert businesses to list of dicts
        businesses = []
        for biz in business_rows:
            businesses.append({
                'business_id': str(biz['business_id']),
                'business_name': biz['business_name'],
                'is_primary': biz['is_primary']
            })
        
        return ClinicData(
            clinic_id=str(clinic_row['clinic_id']),
            clinic_name=clinic_row['clinic_name'],
            cliniko_api_key=clinic_row['cliniko_api_key'],
            cliniko_shard=clinic_row['cliniko_shard'],
            contact_email=clinic_row.get('contact_email', 'noreply@clinic.com'),
            businesses=businesses,
            timezone=clinic_row.get('timezone', 'Australia/Sydney')
        )    
    
async def find_patient_by_phone(clinic_id: str, phone: str, pool: asyncpg.Pool) -> Optional[Dict[str, Any]]:
    """Find patient in database by phone number"""
    normalized = normalize_phone(phone)
    
    query = """
        SELECT patient_id, first_name, last_name, email, phone_number
        FROM patients
        WHERE clinic_id = $1 AND phone_number = $2
    """
    
    async with pool.acquire() as conn:
        row = await conn.fetchrow(query, clinic_id, normalized)
        if row:
            return dict(row)
    return None

async def get_practitioner_services(clinic_id: str, pool: asyncpg.Pool) -> List[Dict[str, Any]]:
    """Get all available services with practitioners from the view"""
    query = """
        SELECT DISTINCT
            practitioner_name,
            practitioner_first_name,
            practitioner_last_name,
            service_name,
            duration_minutes,
            price,
            practitioner_id,
            appointment_type_id,
            business_name,
            business_id
        FROM v_comprehensive_services
        WHERE clinic_id = $1
        ORDER BY practitioner_name, service_name
    """
    
    async with pool.acquire() as conn:
        rows = await conn.fetch(query, clinic_id)
        return [dict(row) for row in rows]

async def match_practitioner(clinic_id: str, requested_name: str, pool: asyncpg.Pool) -> Dict[str, Any]:
    """
    Fuzzy match practitioner by name with comprehensive normalization and clarification support.
    
    Returns:
        {
            "matches": [practitioner_dict, ...],  # all matches above threshold
            "needs_clarification": bool,
            "clarification_options": [str, ...],  # e.g., ["Brendan Smith", "Brendan Jones"]
            "message": str  # clarification message if needed
        }
    """
    services = await get_practitioner_services(clinic_id, pool)
    practitioners = {}
    
    # Build unique practitioner list
    for service in services:
        pid = service['practitioner_id']
        if pid not in practitioners:
            practitioners[pid] = {
                'practitioner_id': pid,
                'full_name': service['practitioner_name'],
                'first_name': service['practitioner_first_name'],
                'last_name': service['practitioner_last_name']
            }
    
    # Parse requested name for prefix, first name, and last name
    requested_parts = parse_practitioner_name(requested_name)
    requested_normalized = normalize_for_matching(requested_name)
    
    # Find all matches above threshold
    matches = []
    best_score = 0
    
    for practitioner in practitioners.values():
        # Normalize ALL fields for comparison
        full_normalized = normalize_for_matching(practitioner['full_name'])
        first_normalized = normalize_for_matching(practitioner['first_name'])
        last_normalized = normalize_for_matching(practitioner['last_name'])
        
        # Calculate match score based on parsed name parts
        score = calculate_practitioner_match_score(
            requested_parts, requested_normalized,
            practitioner, full_normalized, first_normalized, last_normalized
        )
        
        if score > 0.6:  # 60% threshold
            matches.append({
                'practitioner': practitioner,
                'score': score
            })
            if score > best_score:
                best_score = score
    
    # Sort matches by score (highest first)
    matches.sort(key=lambda x: x['score'], reverse=True)
    
    # Extract just the practitioner data
    practitioner_matches = [m['practitioner'] for m in matches]
    
    # Determine if clarification is needed
    if len(practitioner_matches) == 0:
        return {
            "matches": [],
            "needs_clarification": False,
            "clarification_options": [],
            "message": f"I couldn't find a practitioner named \"{requested_name}\".",
            "best_match": None
        }
    
    elif len(practitioner_matches) == 1:
        # Single match - no clarification needed
        return {
            "matches": practitioner_matches,
            "needs_clarification": False,
            "clarification_options": [],
            "message": "",
            "best_match": practitioner_matches[0]
        }
    
    else:
        # Multiple matches - need clarification
        clarification_options = [p['full_name'] for p in practitioner_matches]
        
        # Create a helpful clarification message
        if len(clarification_options) == 2:
            message = f"There are two practitioners with similar names. Do you mean {clarification_options[0]} or {clarification_options[1]}?"
        else:
            options_text = ", ".join(clarification_options[:-1]) + f", or {clarification_options[-1]}"
            message = f"There are {len(clarification_options)} practitioners with similar names. Do you mean {options_text}?"
        
        return {
            "matches": practitioner_matches,
            "needs_clarification": True,
            "clarification_options": clarification_options,
            "message": message,
            "best_match": practitioner_matches[0]  # Return best match for backward compatibility
        }

async def match_service(clinic_id: str, practitioner_id: str, requested_service: str, pool: asyncpg.Pool) -> Optional[Dict[str, Any]]:
    """Match service for a specific practitioner - EXACT matches only for voice"""
    services = await get_practitioner_services(clinic_id, pool)
    practitioner_services = [s for s in services if s['practitioner_id'] == practitioner_id]
    
    requested_normalized = normalize_for_matching(requested_service)
    
    # Look for exact matches after normalization
    for service in practitioner_services:
        service_normalized = normalize_for_matching(service['service_name'])
        
        # Exact match or clear substring match
        if (requested_normalized == service_normalized or 
            requested_normalized in service_normalized or
            service_normalized in requested_normalized):
            return service
    
    # No match found - this is correct for voice agents
    return None

async def match_business(clinic_id: str, location_request: str, pool: asyncpg.Pool) -> Optional[Dict[str, Any]]:
    """Match business/location by name"""
    query = "SELECT * FROM find_business_by_name_dynamic($1, $2) LIMIT 1"
    
    async with pool.acquire() as conn:
        rows = await conn.fetch(query, clinic_id, location_request or '')
        if rows:
            return dict(rows[0])  # Return highest scoring match
    return None

async def log_voice_booking(booking_data: Dict[str, Any], pool: asyncpg.Pool) -> None:
    """Log voice booking attempt - optimized for speed without FK checks"""
    query = """
        INSERT INTO voice_bookings 
        (appointment_id, clinic_id, session_id, caller_phone, action, status, error_message)
        VALUES ($1, $2, $3, $4, $5, $6, $7)
    """
    
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                query,
                booking_data.get('appointment_id'),
                booking_data['clinic_id'],
                booking_data['session_id'],
                mask_phone(booking_data['caller_phone']),
                booking_data['action'],
                booking_data['status'],
                booking_data.get('error_message')
            )
    except Exception as e:
        logger.error(f"Failed to log voice booking: {str(e)}")
        # Don't raise - logging failures shouldn't break bookings

async def invalidate_practitioner_availability(practitioner_id: str, business_id: str, date: date, pool: asyncpg.Pool) -> None:
    """Invalidate availability cache for a specific practitioner/date"""
    query = """
        UPDATE availability_cache 
        SET is_stale = true 
        WHERE practitioner_id = $1 
          AND business_id = $2 
          AND date = $3
    """
    try:
        async with pool.acquire() as conn:
            await conn.execute(query, practitioner_id, business_id, date)
    except Exception as e:
        logger.error(f"Failed to invalidate cache: {str(e)}")
        # Non-critical - don't raise

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

async def get_location_by_name(
    clinic_id: str,
    location_name: str,
    pool: asyncpg.Pool
) -> Optional[Dict[str, Any]]:
    """Get location details by name - case insensitive"""
    query = """
        SELECT business_id, business_name, is_primary
        FROM businesses
        WHERE clinic_id = $1 AND LOWER(business_name) = LOWER($2)
        LIMIT 1
    """
    
    async with pool.acquire() as conn:
        row = await conn.fetchrow(query, clinic_id, location_name)
        return dict(row) if row else None

async def call_find_business_by_name_dynamic(clinic_id: str, business_name: str, pool: asyncpg.Pool) -> Optional[Dict[str, Any]]:
    """Call the find_business_by_name_dynamic database function"""
    query = "SELECT * FROM find_business_by_name_dynamic($1, $2) LIMIT 1"
    async with pool.acquire() as conn:
        row = await conn.fetchrow(query, clinic_id, business_name)
        return dict(row) if row else None

async def update_voice_bookings_constraint(pool: asyncpg.Pool) -> None:
    """Update the voice_bookings table constraint to include 'reschedule' action"""
    try:
        async with pool.acquire() as conn:
            # Drop the existing constraint
            await conn.execute("""
                ALTER TABLE voice_bookings 
                DROP CONSTRAINT IF EXISTS voice_bookings_action_check
            """)
            
            # Add the new constraint with 'reschedule' included
            await conn.execute("""
                ALTER TABLE voice_bookings 
                ADD CONSTRAINT voice_bookings_action_check 
                CHECK (action IN ('book', 'check', 'modify', 'cancel', 'reschedule'))
            """)
            
            logger.info("✓ Updated voice_bookings action constraint to include 'reschedule'")
    except Exception as e:
        logger.error(f"Failed to update voice_bookings constraint: {e}")
        raise

def parse_practitioner_name(name: str) -> Dict[str, str]:
    """
    Parse practitioner name into prefix, first name, and last name.
    
    Examples:
    - "Dr. Smith" -> {"prefix": "Dr", "first_name": "", "last_name": "Smith"}
    - "Brendan" -> {"prefix": "", "first_name": "Brendan", "last_name": ""}
    - "Brendan Smith" -> {"prefix": "", "first_name": "Brendan", "last_name": "Smith"}
    - "Dr. John Smith" -> {"prefix": "Dr", "first_name": "John", "last_name": "Smith"}
    """
    name = name.strip()
    parts = name.split()
    
    result = {
        "prefix": "",
        "first_name": "",
        "last_name": "",
        "original": name
    }
    
    if not parts:
        return result
    
    # Check for common prefixes
    prefixes = ["Dr", "Dr.", "Mr", "Mr.", "Ms", "Ms.", "Mrs", "Mrs.", "Prof", "Prof."]
    
    if parts[0] in prefixes:
        result["prefix"] = parts[0]
        parts = parts[1:]  # Remove prefix
    
    if len(parts) == 1:
        # Single name - could be first or last name
        result["first_name"] = parts[0]
    elif len(parts) == 2:
        # Two names - assume first and last
        result["first_name"] = parts[0]
        result["last_name"] = parts[1]
    elif len(parts) > 2:
        # Multiple names - first is first name, last is last name, middle names ignored
        result["first_name"] = parts[0]
        result["last_name"] = parts[-1]
    
    return result

def calculate_practitioner_match_score(
    requested_parts: Dict[str, str],
    requested_normalized: str,
    practitioner: Dict[str, str],
    full_normalized: str,
    first_normalized: str,
    last_normalized: str
) -> float:
    """
    Calculate match score between requested name and practitioner.
    Higher scores indicate better matches.
    """
    scores = []
    
    # Exact matches get highest scores
    if requested_normalized == full_normalized:
        scores.append(1.0)
    if requested_normalized == first_normalized:
        scores.append(0.95)
    if requested_normalized == last_normalized:
        scores.append(0.9)
    
    # Prefix + last name match (e.g., "Dr. Smith")
    if requested_parts["prefix"] and requested_parts["last_name"]:
        if (normalize_for_matching(requested_parts["prefix"]) in normalize_for_matching(practitioner.get("prefix", "")) and
            normalize_for_matching(requested_parts["last_name"]) == last_normalized):
            scores.append(0.95)
    
    # First name + last name match
    if requested_parts["first_name"] and requested_parts["last_name"]:
        if (normalize_for_matching(requested_parts["first_name"]) == first_normalized and
            normalize_for_matching(requested_parts["last_name"]) == last_normalized):
            scores.append(0.98)
    
    # Fuzzy matches
    scores.append(fuzzy_match(requested_normalized, full_normalized))
    scores.append(fuzzy_match(requested_normalized, last_normalized))
    scores.append(fuzzy_match(requested_normalized, first_normalized))
    
    # Substring matches
    if last_normalized and (last_normalized in requested_normalized or requested_normalized in last_normalized):
        scores.append(0.8)
    if first_normalized and (first_normalized in requested_normalized or requested_normalized in first_normalized):
        scores.append(0.8)
    
    # Return the highest score
    return max(scores) if scores else 0.0