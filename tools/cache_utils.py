"""Shared cache utility functions to avoid circular imports"""
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone
import asyncpg
import logging

logger = logging.getLogger(__name__)

async def check_and_trigger_sync(
    clinic_id: str,
    pool: asyncpg.Pool,
    cache: Any,  # Avoid importing CacheManager
    cliniko_api_key: str,
    cliniko_shard: str
):
    """Check if sync needed and trigger if so"""
    try:
        # Check last sync time
        async with pool.acquire() as conn:
            last_sync = await conn.fetchval("""
                SELECT MAX(cached_at)
                FROM availability_cache
                WHERE clinic_id = $1
            """, clinic_id)
        
        # Use timezone-aware current time
        current_time = datetime.now(timezone.utc)
        
        # If no sync or older than 5 minutes, trigger sync
        if not last_sync:
            should_sync = True
        else:
            # Ensure last_sync is timezone-aware
            if last_sync.tzinfo is None:
                # Assume database times are UTC
                last_sync = last_sync.replace(tzinfo=timezone.utc)
            
            time_diff = (current_time - last_sync).total_seconds()
            should_sync = time_diff > 300
        
        if should_sync:
            # Import here to avoid circular import
            from cache_manager import IncrementalCacheSync
            from cliniko import ClinikoAPI
            
            cliniko = ClinikoAPI(
                cliniko_api_key, 
                cliniko_shard,
                user_agent="VoiceBookingSystem/1.0"  # Add this parameter
            )
            sync = IncrementalCacheSync(cache, pool)
            await sync.sync_appointments_incremental(clinic_id, cliniko)
    except Exception as e:
        logger.warning(f"Sync check failed: {e}")

async def get_cached_practitioner_services(
    clinic_id: str,
    pool: asyncpg.Pool,
    cache: Any
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
    cache: Any,
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