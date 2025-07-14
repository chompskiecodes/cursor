# tools/sync_router.py
"""Cache synchronization endpoint for the Voice Booking System"""

from fastapi import APIRouter, Request, Depends, HTTPException
from typing import Dict, Any, Optional, Set
from datetime import datetime, timedelta, timezone
import logging
import asyncio
import time
import asyncpg

# Local imports
from .dependencies import verify_api_key, get_db, get_cache
from models import BaseModel
from database import get_clinic_by_dialed_number
from cache_manager import IncrementalCacheSync
from cliniko import ClinikoAPI
from payload_logger import payload_logger

logger = logging.getLogger(__name__)

# Create router
router = APIRouter(tags=["sync"])

# Track active syncs to prevent concurrent execution
active_syncs: Set[str] = set()
sync_locks = {}  # clinic_id -> asyncio.Lock

class SyncCacheRequest(BaseModel):
    """Request model for cache synchronization"""
    sessionId: str
    dialedNumber: str
    callerPhone: Optional[str] = None
    forceFullSync: bool = False

class SyncCacheResponse(BaseModel):
    """Response model for cache synchronization"""
    success: bool
    sessionId: str
    message: str
    syncStats: Optional[Dict[str, int]] = None
    durationMs: Optional[int] = None
    lastSyncTime: Optional[str] = None
    syncType: str = "incremental"  # "incremental", "full", or "skipped"
    syncInProgress: bool = False

async def is_sync_running(clinic_id: str, pool: asyncpg.Pool) -> bool:
    """Check if a sync is currently running for this clinic"""
    # Check in-memory tracking
    if clinic_id in active_syncs:
        return True
    
    # Also check database for distributed systems
    async with pool.acquire() as conn:
        result = await conn.fetchrow("""
            SELECT COUNT(*) as active_count
            FROM cache_warmup_log
            WHERE clinic_id = $1
                AND created_at > NOW() - INTERVAL '5 minutes'
                AND success IS NULL  -- NULL means still running
        """, clinic_id)
        
        return result['active_count'] > 0 if result else False

async def mark_sync_started(clinic_id: str, pool: asyncpg.Pool, warmup_type: str = 'on_call') -> Optional[int]:
    """Mark sync as started in database and return the log ID"""
    try:
        async with pool.acquire() as conn:
            log_id = await conn.fetchval("""
                INSERT INTO cache_warmup_log (
                    clinic_id, warmup_type, created_at, success
                ) VALUES ($1, $2, NOW(), NULL)
                RETURNING id
            """, clinic_id, warmup_type)
            
        active_syncs.add(clinic_id)
        return log_id
    except Exception as e:
        logger.error(f"Failed to mark sync started: {e}")
        return None

async def mark_sync_completed(
    clinic_id: str, 
    pool: asyncpg.Pool, 
    log_id: int,
    stats: Dict[str, int],
    duration_ms: int,
    success: bool = True,
    error_message: Optional[str] = None
):
    """Mark sync as completed in database"""
    try:
        async with pool.acquire() as conn:
            await conn.execute("""
                UPDATE cache_warmup_log
                SET 
                    practitioners_warmed = $2,
                    total_slots_cached = $3,
                    duration_ms = $4,
                    success = $5,
                    error_message = $6
                WHERE id = $1
            """, 
                log_id,
                stats.get('practitioners', 0),
                stats.get('updated', 0),
                duration_ms,
                success,
                error_message
            )
    except Exception as e:
        logger.error(f"Failed to mark sync completed: {e}")
    finally:
        active_syncs.discard(clinic_id)

def get_clinic_lock(clinic_id: str) -> asyncio.Lock:
    """Get or create a lock for a specific clinic"""
    if clinic_id not in sync_locks:
        sync_locks[clinic_id] = asyncio.Lock()
    return sync_locks[clinic_id]

@router.post("/sync-cache", response_model=SyncCacheResponse)
async def sync_cache(
    request: SyncCacheRequest,
    authenticated: bool = Depends(verify_api_key)
) -> Dict[str, Any]:
    """
    Sync cache with Cliniko using updated_at filter.
    Called explicitly as the first tool in every voice call.
    """
    start_time = time.time()
    
    # Log the incoming request
    payload_logger.log_payload("/sync-cache", request.dict())
    
    log_id = None
    clinic = None
    
    try:
        logger.info(f"=== CACHE SYNC START ===")
        logger.info(f"Session: {request.sessionId}")
        logger.info(f"Force full sync: {request.forceFullSync}")
        
        # Get database pool and cache
        pool = await get_db()
        cache = await get_cache()
        
        # Get clinic information from database (not environment)
        clinic = await get_clinic_by_dialed_number(request.dialedNumber, pool)
        if not clinic:
            logger.error(f"Clinic not found for number: {request.dialedNumber}")
            return SyncCacheResponse(
                success=False,
                sessionId=request.sessionId,
                message="Unable to identify clinic",
                durationMs=int((time.time() - start_time) * 1000)
            )
        
        logger.info(f"✓ Found clinic: {clinic.clinic_name} (ID: {clinic.clinic_id})")
        
        # Check if sync is already running
        if await is_sync_running(clinic.clinic_id, pool):
            logger.info(f"Sync already in progress for clinic {clinic.clinic_id}")
            return SyncCacheResponse(
                success=True,
                sessionId=request.sessionId,
                message="Cache sync is already in progress",
                syncType="skipped",
                syncInProgress=True,
                durationMs=int((time.time() - start_time) * 1000)
            )
        
        # Get clinic-specific lock
        clinic_lock = get_clinic_lock(clinic.clinic_id)
        
        # Try to acquire lock with timeout
        try:
            async with asyncio.timeout(1.0):  # 1 second timeout
                await clinic_lock.acquire()
        except asyncio.TimeoutError:
            logger.info(f"Could not acquire sync lock for clinic {clinic.clinic_id}")
            return SyncCacheResponse(
                success=True,
                sessionId=request.sessionId,
                message="Another sync is in progress",
                syncType="skipped",
                syncInProgress=True,
                durationMs=int((time.time() - start_time) * 1000)
            )
        
        try:
            # Mark sync as started
            log_id = await mark_sync_started(clinic.clinic_id, pool)
            
            # Check last sync time from database
            async with pool.acquire() as conn:
                last_sync_row = await conn.fetchrow("""
                    SELECT 
                        MAX(cached_at) as last_sync,
                        COUNT(DISTINCT practitioner_id) as cached_practitioners,
                        COUNT(*) as total_slots
                    FROM availability_cache 
                    WHERE clinic_id = $1
                        AND NOT is_stale
                        AND expires_at > NOW()
                """, clinic.clinic_id)
            
            last_sync_time = last_sync_row['last_sync'] if last_sync_row else None
            
            # Determine if we need a full sync
            need_full_sync = (
                request.forceFullSync or 
                not last_sync_time or
                (datetime.now(timezone.utc) - last_sync_time.replace(tzinfo=timezone.utc)).total_seconds() > 3600  # 1 hour
            )
            
            sync_type = "full" if need_full_sync else "incremental"
            logger.info(f"Sync type: {sync_type} (last sync: {last_sync_time})")
            
            # Initialize Cliniko API with credentials from database
            cliniko = ClinikoAPI(
                api_key=clinic.cliniko_api_key,
                shard=clinic.cliniko_shard,
                user_agent=f"VoiceBookingSystem/2.0 (clinic:{clinic.clinic_id})"
            )
            
            # Create sync instance
            sync = IncrementalCacheSync(cache, pool)
            
            # Run the sync (this is synchronous - waits for completion)
            logger.info(f"Starting {sync_type} sync for clinic {clinic.clinic_id}")
            sync_stats = await sync.sync_appointments_incremental(
                clinic.clinic_id,
                cliniko,
                force_full_sync=need_full_sync
            )
            
            # Calculate duration
            duration_ms = int((time.time() - start_time) * 1000)
            
            # Update sync completion in database
            if log_id:
                await mark_sync_completed(
                    clinic.clinic_id,
                    pool,
                    log_id,
                    sync_stats,
                    duration_ms,
                    success=sync_stats.get('errors', 0) == 0
                )
            
            logger.info(f"=== CACHE SYNC COMPLETE ===")
            logger.info(f"Duration: {duration_ms}ms")
            logger.info(f"Stats: {sync_stats}")
            
            # Prepare response message
            if sync_stats.get('errors', 0) > 0:
                message = "Cache sync completed with some errors"
            elif sync_stats.get('updated', 0) == 0:
                message = "Cache is already up to date"
            else:
                message = f"Cache updated successfully ({sync_stats['updated']} appointments)"
            
            return SyncCacheResponse(
                success=True,
                sessionId=request.sessionId,
                message=message,
                syncStats=sync_stats,
                durationMs=duration_ms,
                lastSyncTime=datetime.now(timezone.utc).isoformat(),
                syncType=sync_type
            )
            
        finally:
            # Always release the lock
            clinic_lock.release()
        
    except Exception as e:
        logger.error(f"Sync failed: {str(e)}", exc_info=True)
        
        # Mark sync as failed if we have a log_id
        if log_id and clinic:
            await mark_sync_completed(
                clinic.clinic_id,
                pool,
                log_id,
                {'errors': 1},
                int((time.time() - start_time) * 1000),
                success=False,
                error_message=str(e)
            )
        
        return SyncCacheResponse(
            success=False,
            sessionId=request.sessionId,
            message="Cache sync encountered an error",
            durationMs=int((time.time() - start_time) * 1000)
        )

@router.get("/sync-status/{clinic_id}")
async def get_sync_status(
    clinic_id: str,
    authenticated: bool = Depends(verify_api_key)
) -> Dict[str, Any]:
    """Check current sync status for a clinic"""
    
    pool = await get_db()
    
    # Check if sync is running
    is_running = await is_sync_running(clinic_id, pool)
    
    # Get last successful sync
    async with pool.acquire() as conn:
        last_sync = await conn.fetchrow("""
            SELECT 
                created_at,
                duration_ms,
                total_slots_cached,
                warmup_type
            FROM cache_warmup_log
            WHERE clinic_id = $1
                AND success = true
            ORDER BY created_at DESC
            LIMIT 1
        """, clinic_id)
    
    if last_sync:
        time_since_sync = (datetime.now(timezone.utc) - last_sync['created_at'].replace(tzinfo=timezone.utc)).total_seconds()
        
        return {
            "syncInProgress": is_running,
            "lastSyncTime": last_sync['created_at'].isoformat(),
            "lastSyncDurationMs": last_sync['duration_ms'],
            "lastSyncSlots": last_sync['total_slots_cached'],
            "lastSyncType": last_sync['warmup_type'],
            "secondsSinceSync": int(time_since_sync),
            "cacheStatus": "fresh" if time_since_sync < 3600 else "stale"
        }
    else:
        return {
            "syncInProgress": is_running,
            "lastSyncTime": None,
            "cacheStatus": "empty"
        }

# Include this router in main.py by adding:
# from tools.sync_router import router as sync_router
# app.include_router(sync_router)
