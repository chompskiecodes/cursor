# cache_manager.py
"""
Cache management system for the Voice Booking System.
Provides fast lookups and reduces Cliniko API calls.
"""

import asyncpg
import json
import logging
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, timedelta, date, timezone as tz
from contextlib import asynccontextmanager
import asyncio
from functools import wraps
import time
from decimal import Decimal
from zoneinfo import ZoneInfo
import os

logger = logging.getLogger(__name__)

def get_default_timezone():
    """Get default timezone from settings"""
    return ZoneInfo(os.environ.get("DEFAULT_TIMEZONE", "Australia/Sydney"))

class DecimalEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, Decimal):
            return float(obj)
        return super().default(obj)

class CacheManager:
    """Centralized cache management for all cache types"""
    
    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool
        # Store timezone for consistent handling
        self.default_tz = get_default_timezone()
        self._cache_ttls = {
            'availability': timedelta(minutes=15),
            'patient': timedelta(hours=24),
            'service_match': timedelta(days=7),
            'booking_context': timedelta(hours=1)
        }
    
    def _ensure_timezone_aware(self, dt: datetime) -> datetime:
        """Ensure datetime is timezone aware in UTC"""
        if dt.tzinfo is None:
            # Assume naive datetimes are in default timezone
            return dt.replace(tzinfo=self.default_tz).astimezone(tz.utc)
        return dt.astimezone(tz.utc)
    
    # === Timing Decorator (Static Method Inside Class) ===
    @staticmethod
    def _track_timing(cache_type: str):
        """Decorator to track cache operation timing"""
        def decorator(func):
            @wraps(func)
            async def wrapper(self, *args, **kwargs):
                start_time = time.time()
                try:
                    result = await func(self, *args, **kwargs)
                    response_time_ms = (time.time() - start_time) * 1000
                    
                    # Record timing in statistics
                    await self._record_stat(
                        cache_type=cache_type,
                        is_hit=result is not None,
                        response_time_ms=response_time_ms
                    )
                    
                    return result
                except Exception as e:
                    logger.error(f"Cache error in {cache_type}: {str(e)}")
                    return None
            return wrapper
        return decorator
    
    # === Core Cache Operations ===
    
    async def _record_stat(self, cache_type: str, is_hit: bool, response_time_ms: float = None, clinic_id: str = None):
        """Record cache statistics"""
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(
                    "SELECT record_cache_stat($1, $2, $3, $4)",
                    cache_type, is_hit, response_time_ms, clinic_id
                )
        except Exception as e:
            logger.error(f"Failed to record cache stat: {e}")
    
    # === Availability Cache ===
    
    @_track_timing('availability')
    async def get_availability(
        self, 
        practitioner_id: str, 
        business_id: str, 
        check_date: date
    ) -> Optional[List[Dict[str, Any]]]:
        """Get cached availability for a practitioner"""
        query = """
            SELECT available_slots
            FROM availability_cache
            WHERE practitioner_id = $1
              AND business_id = $2
              AND date = $3
              AND expires_at > NOW()
              AND NOT is_stale
        """
        
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(query, practitioner_id, business_id, check_date)
            if row and row['available_slots']:
                return json.loads(row['available_slots'])
            return None
    
    async def set_availability(
        self,
        practitioner_id: str,
        business_id: str,
        check_date: date,
        clinic_id: str,
        slots: List[Dict[str, Any]]
    ) -> bool:
        """Cache availability data with proper timezone handling"""
        
        # Ensure all slot times are properly formatted
        normalized_slots = []
        for slot in slots:
            normalized_slot = slot.copy()
            
            # Normalize the appointment_start time
            start_time = slot.get('appointment_start', slot.get('start'))
            if start_time:
                if isinstance(start_time, str):
                    if start_time.endswith('Z'):
                        dt = datetime.fromisoformat(start_time.replace('Z', '+00:00'))
                    else:
                        dt = datetime.fromisoformat(start_time)
                    
                    # Ensure UTC
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=tz.utc)
                    
                    normalized_slot['appointment_start'] = dt.isoformat()
                    normalized_slot['_utc_timestamp'] = dt.timestamp()  # Add for easy comparison
            
            normalized_slots.append(normalized_slot)
        
        query = """
            INSERT INTO availability_cache 
            (clinic_id, practitioner_id, business_id, date, available_slots, expires_at)
            VALUES ($1, $2, $3, $4, $5, (NOW() AT TIME ZONE 'UTC') + $6)
            ON CONFLICT (practitioner_id, business_id, date) 
            DO UPDATE SET
                available_slots = EXCLUDED.available_slots,
                cached_at = NOW() AT TIME ZONE 'UTC',
                expires_at = (NOW() AT TIME ZONE 'UTC') + $6,
                is_stale = false
        """
        
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(
                    query,
                    clinic_id,
                    practitioner_id,
                    business_id,
                    check_date,
                    json.dumps(normalized_slots, cls=DecimalEncoder),
                    self._cache_ttls['availability']
                )
            return True
        except Exception as e:
            logger.error(f"Failed to cache availability: {e}")
            return False
    
    async def invalidate_availability(
        self,
        practitioner_id: str,
        business_id: str,
        check_date: date
    ) -> bool:
        """Invalidate availability cache when appointment is made"""
        query = """
            UPDATE availability_cache
            SET is_stale = true
            WHERE practitioner_id = $1
              AND business_id = $2
              AND date = $3
        """
        
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(query, practitioner_id, business_id, check_date)
            return True
        except Exception as e:
            logger.error(f"Failed to invalidate availability: {e}")
            return False
    
    # === Patient Cache ===
    
    @_track_timing('patient')
    async def get_patient(self, phone_normalized: str, clinic_id: str) -> Optional[Dict[str, Any]]:
        """Get cached patient data by phone"""
        query = """
            SELECT patient_data
            FROM patient_cache
            WHERE phone_normalized = $1
              AND clinic_id = $2
              AND expires_at > NOW()
        """
        
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(query, phone_normalized, clinic_id)
            if row and row['patient_data']:
                return json.loads(row['patient_data'])
            return None
    
    async def set_patient(
        self,
        phone_normalized: str,
        clinic_id: str,
        patient_id: str,
        patient_data: Dict[str, Any]
    ) -> bool:
        """Cache patient data"""
        query = """
            INSERT INTO patient_cache 
            (phone_normalized, clinic_id, patient_id, patient_data, expires_at)
            VALUES ($1, $2, $3, $4, NOW() + $5)
            ON CONFLICT (phone_normalized, clinic_id) 
            DO UPDATE SET
                patient_id = EXCLUDED.patient_id,
                patient_data = EXCLUDED.patient_data,
                cached_at = NOW(),
                expires_at = NOW() + $5
        """
        
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(
                    query,
                    phone_normalized,
                    clinic_id,
                    patient_id,
                    json.dumps(patient_data, cls=DecimalEncoder),
                    self._cache_ttls['patient']
                )
            return True
        except Exception as e:
            logger.error(f"Failed to cache patient: {e}")
            return False
    
    # === Service Match Cache ===
    
    @_track_timing('service_match')
    async def get_service_matches(
        self,
        clinic_id: str,
        search_term: str
    ) -> Optional[List[Dict[str, Any]]]:
        """Get cached service matching results"""
        cache_key = f"{clinic_id}:{search_term.lower()}"
        
        query = """
            SELECT matches
            FROM service_match_cache
            WHERE cache_key = $1
              AND expires_at > NOW()
        """
        
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(query, cache_key)
            if row and row['matches']:
                # Update usage count
                await conn.execute(
                    "UPDATE service_match_cache SET usage_count = usage_count + 1 WHERE cache_key = $1",
                    cache_key
                )
                return json.loads(row['matches'])
            return None
    
    async def set_service_matches(
        self,
        clinic_id: str,
        search_term: str,
        matches: List[Dict[str, Any]]
    ) -> bool:
        """Cache service matching results"""
        cache_key = f"{clinic_id}:{search_term.lower()}"
        
        query = """
            INSERT INTO service_match_cache 
            (cache_key, clinic_id, search_term, matches, expires_at)
            VALUES ($1, $2, $3, $4, NOW() + $5)
            ON CONFLICT (cache_key) 
            DO UPDATE SET
                matches = EXCLUDED.matches,
                usage_count = service_match_cache.usage_count + 1,
                cached_at = NOW(),
                expires_at = NOW() + $5
        """
        
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(
                    query,
                    cache_key,
                    clinic_id,
                    search_term,
                    json.dumps(matches, cls=DecimalEncoder),
                    self._cache_ttls['service_match']
                )
            return True
        except Exception as e:
            logger.error(f"Failed to cache service matches: {e}")
            return False
    
    # === Booking Context Cache ===
    
    @_track_timing('booking_context')
    async def get_booking_context(self, phone_normalized: str) -> Optional[Dict[str, Any]]:
        """Get cached booking context for a caller"""
        query = """
            SELECT context_data
            FROM booking_context_cache
            WHERE phone_normalized = $1
              AND expires_at > NOW()
        """
        
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(query, phone_normalized)
            if row and row['context_data']:
                # Update last accessed
                await conn.execute(
                    """UPDATE booking_context_cache 
                       SET hit_count = hit_count + 1, last_accessed = NOW() 
                       WHERE phone_normalized = $1""",
                    phone_normalized
                )
                return json.loads(row['context_data'])
            return None
    
    async def set_booking_context(
        self,
        phone_normalized: str,
        clinic_id: str,
        context_data: Dict[str, Any]
    ) -> bool:
        """Cache booking context for a caller"""
        query = """
            INSERT INTO booking_context_cache 
            (phone_normalized, clinic_id, context_data, expires_at)
            VALUES ($1, $2, $3, NOW() + $4)
            ON CONFLICT (phone_normalized) 
            DO UPDATE SET
                clinic_id = EXCLUDED.clinic_id,
                context_data = EXCLUDED.context_data,
                cached_at = NOW(),
                expires_at = NOW() + $4,
                hit_count = booking_context_cache.hit_count + 1,
                last_accessed = NOW()
        """
        
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(
                    query,
                    phone_normalized,
                    clinic_id,
                    json.dumps(context_data, cls=DecimalEncoder),
                    self._cache_ttls['booking_context']
                )
            return True
        except Exception as e:
            logger.error(f"Failed to cache booking context: {e}")
            return False
    
    # === Batch Operations ===
    
    async def warm_availability_cache(
        self,
        clinic_id: str,
        days_ahead: int = 7
    ) -> Dict[str, int]:
        """Pre-warm availability cache for next N days"""
        stats = {'cached': 0, 'failed': 0}
        
        # Get all active practitioner-business combinations
        query = """
            SELECT DISTINCT
                p.practitioner_id,
                pb.business_id,
                p.first_name || ' ' || p.last_name as practitioner_name
            FROM practitioners p
            JOIN practitioner_businesses pb ON p.practitioner_id = pb.practitioner_id
            WHERE p.clinic_id = $1 AND p.active = true
        """
        
        async with self.pool.acquire() as conn:
            practitioners = await conn.fetch(query, clinic_id)
        
        # Note: Actual availability fetching from Cliniko would happen here
        # This is a placeholder showing the caching pattern
        logger.info(f"Would warm cache for {len(practitioners)} practitioners over {days_ahead} days")
        
        return stats
    
    # === Cache Maintenance ===
    
    async def cleanup_expired(self) -> int:
        """Clean up expired cache entries"""
        try:
            async with self.pool.acquire() as conn:
                result = await conn.fetchval("SELECT cleanup_expired_cache()")
                return result or 0
        except Exception as e:
            logger.error(f"Failed to cleanup cache: {e}")
            return 0
    
    async def get_cache_stats(self) -> Dict[str, Any]:
        """Get current cache statistics"""
        query = """
            SELECT * FROM v_cache_status
            UNION ALL
            SELECT 
                'summary' as cache_type,
                SUM(total_entries) as total_entries,
                SUM(valid_entries) as valid_entries,
                SUM(stale_entries) as stale_entries,
                MIN(oldest_entry) as oldest_entry,
                MAX(newest_entry) as newest_entry
            FROM v_cache_status
        """
        
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(query)
            return {row['cache_type']: dict(row) for row in rows}
    
    async def get_hit_rates(self, hours: int = 24) -> Dict[str, float]:
        """Get cache hit rates for the past N hours"""
        query = """
            SELECT 
                cache_type,
                ROUND(SUM(hit_count)::numeric / 
                      NULLIF(SUM(hit_count) + SUM(miss_count), 0) * 100, 2) as hit_rate
            FROM cache_statistics
            WHERE stat_date >= CURRENT_DATE - make_interval(hours => $1)
            GROUP BY cache_type
        """
        
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(query, hours)
            return {row['cache_type']: row['hit_rate'] or 0.0 for row in rows}


class IncrementalCacheSync:
    """Sync cache with Cliniko using incremental updates"""
    
    def __init__(self, cache_manager: CacheManager, pool: asyncpg.Pool):
        self.cache = cache_manager
        self.pool = pool
    
    async def sync_appointments_incremental(
        self,
        clinic_id: str,
        cliniko_api,  # ClinikoAPI instance
        force_full_sync: bool = False
    ) -> Dict[str, int]:
        """Sync only changed appointments since last sync"""
        stats = {'updated': 0, 'deleted': 0, 'errors': 0}
        
        try:
            # Get last sync time
            async with self.pool.acquire() as conn:
                last_sync = await conn.fetchval("""
                    SELECT MAX(cached_at) 
                    FROM availability_cache 
                    WHERE clinic_id = $1
                """, clinic_id)
            
            if force_full_sync or not last_sync:
                # First sync or forced full sync - go back 7 days
                sync_from = datetime.now(tz.utc) - timedelta(days=7)
                logger.info(f"Full sync for clinic {clinic_id} from {sync_from}")
            else:
                # Add small overlap
                sync_from = last_sync - timedelta(minutes=5)
                logger.info(f"Incremental sync for clinic {clinic_id} since {sync_from}")
            
            # Format timestamp for Cliniko API
            sync_from_str = sync_from.strftime('%Y-%m-%dT%H:%M:%SZ')
            
            # Fetch updated appointments
            params = {
                'q[]': f'updated_at:>{sync_from_str}',
                'per_page': 100
            }
            
            updated_appointments = await cliniko_api.get_all_pages('appointments', params=params)
            
            logger.info(f"Found {len(updated_appointments)} updated appointments")
            
            # Process each updated appointment
            for appointment in updated_appointments:
                try:
                    await self._process_appointment_update(
                        clinic_id,
                        appointment,
                        cliniko_api
                    )
                    stats['updated'] += 1
                except Exception as e:
                    logger.error(f"Error processing appointment {appointment.get('id')}: {e}")
                    stats['errors'] += 1
            
            logger.info(f"Sync complete for {clinic_id}: {stats}")
            
        except Exception as e:
            logger.error(f"Sync failed for clinic {clinic_id}: {e}")
            stats['errors'] += 1
        
        return stats
    
    async def _process_appointment_update(
        self,
        clinic_id: str,
        appointment: Dict,
        cliniko_api
    ):
        """Process a single appointment update"""
        # Extract data
        practitioner_id = str(appointment.get('practitioner', {}).get('links', {}).get('self', '').split('/')[-1])
        business_id = str(appointment.get('business', {}).get('links', {}).get('self', '').split('/')[-1])
        
        if not practitioner_id or not business_id:
            logger.warning(f"Missing practitioner/business ID in appointment {appointment.get('id')}")
            return
        
        # Parse appointment date
        appointment_start = appointment.get('appointment_start', '')
        if not appointment_start:
            return
            
        appointment_date = datetime.fromisoformat(
            appointment_start.replace('Z', '+00:00')
        ).date()
        
        if appointment.get('cancelled_at') or appointment.get('deleted_at'):
            # Invalidate cache for that day
            await self._invalidate_availability_cache(
                practitioner_id,
                business_id,
                appointment_date
            )
        else:
            # Refresh cache for that day
            await self._refresh_availability_cache(
                clinic_id,
                practitioner_id,
                business_id,
                appointment_date,
                cliniko_api
            )
    
    async def _invalidate_availability_cache(
        self,
        practitioner_id: str,
        business_id: str,
        date: date
    ):
        """Mark cache entries as stale"""
        query = """
            UPDATE availability_cache
            SET is_stale = true
            WHERE practitioner_id = $1
              AND business_id = $2
              AND date = $3
        """
        async with self.pool.acquire() as conn:
            await conn.execute(query, practitioner_id, business_id, date)
            logger.debug(f"Invalidated cache for {practitioner_id} at {business_id} on {date}")
    
    async def _refresh_availability_cache(
        self,
        clinic_id: str,
        practitioner_id: str,
        business_id: str,
        check_date: date,
        cliniko_api
    ):
        """Refresh cache for a specific practitioner/date"""
        try:
            # Get appointment type
            async with self.pool.acquire() as conn:
                appointment_type_id = await conn.fetchval("""
                    SELECT appointment_type_id FROM practitioner_appointment_types 
                    WHERE practitioner_id = $1 LIMIT 1
                """, practitioner_id)
            
            if not appointment_type_id:
                logger.warning(f"No appointment type for practitioner {practitioner_id}")
                return
            
            # Fetch fresh availability
            from_date = check_date.isoformat()
            to_date = check_date.isoformat()  # Same day query
            
            slots = await cliniko_api.get_available_times(
                business_id,
                practitioner_id,
                appointment_type_id,
                from_date,
                to_date
            )
            
            # Update cache
            await self.cache.set_availability(
                practitioner_id,
                business_id,
                check_date,
                clinic_id,
                slots
            )
            
            logger.debug(f"Refreshed cache for {practitioner_id} at {business_id} on {check_date}: {len(slots)} slots")
            
        except Exception as e:
            logger.error(f"Failed to refresh cache: {e}")


# === Cache-Aware Database Functions ===

async def get_cached_practitioner_services(
    clinic_id: str,
    pool: asyncpg.Pool,
    cache: CacheManager
) -> List[Dict[str, Any]]:
    """Get practitioner services with caching"""
    # Try cache first
    cached = await cache.get_service_matches(clinic_id, "_all_services")
    if cached:
        return cached
    
    # Fetch from database
    from database import get_practitioner_services
    services = await get_practitioner_services(clinic_id, pool)
    
    # Cache the results
    await cache.set_service_matches(clinic_id, "_all_services", services)
    
    return services


async def find_patient_with_cache(
    clinic_id: str,
    phone: str,
    pool: asyncpg.Pool,
    cache: CacheManager,
    cliniko_api = None
) -> Optional[Dict[str, Any]]:
    """Find patient with caching layer"""
    from utils import normalize_phone
    phone_normalized = normalize_phone(phone)
    
    # Try cache first
    cached = await cache.get_patient(phone_normalized, clinic_id)
    if cached:
        logger.info(f"Patient cache hit for {phone_normalized[:3]}***")
        return cached
    
    # Try database
    from database import find_patient_by_phone
    patient = await find_patient_by_phone(clinic_id, phone, pool)
    
    if patient:
        # Cache the result
        await cache.set_patient(phone_normalized, clinic_id, patient['patient_id'], patient)
        return patient
    
    # If not in DB and we have Cliniko API, check there
    if cliniko_api:
        cliniko_patient = await cliniko_api.find_patient(phone)
        if cliniko_patient:
            # Transform to our format
            patient_data = {
                "patient_id": str(cliniko_patient['id']),
                "first_name": cliniko_patient['first_name'],
                "last_name": cliniko_patient['last_name'],
                "phone_number": phone,
                "email": cliniko_patient.get('email')
            }
            
            # Cache it
            await cache.set_patient(
                phone_normalized,
                clinic_id,
                patient_data['patient_id'],
                patient_data
            )
            
            return patient_data
    
    return None


# === Background Tasks ===

async def cache_maintenance_task(cache: CacheManager, interval_minutes: int = 60):
    """Background task for cache maintenance"""
    while True:
        try:
            # Cleanup expired entries
            deleted = await cache.cleanup_expired()
            logger.info(f"Cleaned up {deleted} expired cache entries")
            
            # Log cache stats
            stats = await cache.get_cache_stats()
            hit_rates = await cache.get_hit_rates()
            
            logger.info(f"Cache stats: {stats['summary']}")
            logger.info(f"Hit rates: {hit_rates}")
            
        except Exception as e:
            logger.error(f"Cache maintenance error: {e}")
        
        await asyncio.sleep(interval_minutes * 60)


# === Integration Example ===

async def check_availability_with_cache(
    practitioner_id: str,
    business_id: str,
    check_date: date,
    clinic_id: str,
    pool: asyncpg.Pool,
    cache: CacheManager,
    cliniko_api = None,
    appointment_type_id: str = None,
    clinic: Any = None
) -> List[Dict[str, Any]]:
    """Check availability with intelligent caching"""
    # Try cache first
    cached_slots = await cache.get_availability(practitioner_id, business_id, check_date)
    if cached_slots is not None:
        logger.info(f"Availability cache hit for {practitioner_id} on {check_date}")
        return cached_slots
    
    # Cache miss - need to fetch from Cliniko
    logger.info(f"Availability cache miss for {practitioner_id} on {check_date}")
    
    # Create Cliniko API if not provided
    if not cliniko_api:
        if not clinic:
            # Get clinic info from database
            query = "SELECT * FROM clinics WHERE clinic_id = $1"
            async with pool.acquire() as conn:
                clinic_row = await conn.fetchrow(query, clinic_id)
                if not clinic_row:
                    logger.error(f"Clinic {clinic_id} not found")
                    return []
            clinic = clinic_row
        from cliniko import ClinikoAPI
        cliniko_api = ClinikoAPI(
            clinic['cliniko_api_key'],
            clinic['cliniko_shard'],
            clinic['contact_email']
        )
    
    # Need appointment_type_id - get the first one for this practitioner if not provided
    if not appointment_type_id:
        query = """
            SELECT appointment_type_id 
            FROM practitioner_appointment_types 
            WHERE practitioner_id = $1 
            LIMIT 1
        """
        async with pool.acquire() as conn:
            row = await conn.fetchrow(query, practitioner_id)
            if row:
                appointment_type_id = row['appointment_type_id']
            else:
                logger.error(f"No appointment types found for practitioner {practitioner_id}")
                return []
    
    # Fetch from Cliniko API
    from_date = check_date.isoformat()
    to_date = check_date.isoformat()  # Same day query for accuracy
    
    slots = await cliniko_api.get_available_times(
        business_id,
        practitioner_id,
        appointment_type_id,
        from_date,
        to_date
    )
    
    # Cache the results
    await cache.set_availability(
        practitioner_id,
        business_id,
        check_date,
        clinic_id,
        slots
    )
    
    return slots