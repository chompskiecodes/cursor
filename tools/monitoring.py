# tools/monitoring.py
"""Monitoring utilities for timezone and cache issues"""

import asyncio
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional
import logging

logger = logging.getLogger(__name__)


class BookingMonitor:
    """Monitor booking failures and cache issues"""
    
    def __init__(self, pool, cache_manager):
        self.pool = pool
        self.cache = cache_manager
        self.failure_threshold = 3  # Alert after 3 failures
        self.time_window = timedelta(minutes=5)
    
    async def log_booking_attempt(
        self,
        session_id: str,
        practitioner_id: str,
        requested_time: datetime,
        found_slot: bool,
        error_type: Optional[str] = None
    ):
        """Log booking attempt for monitoring"""
        query = """
            INSERT INTO booking_monitoring (
                session_id, practitioner_id, requested_time_utc,
                found_slot, error_type, created_at
            ) VALUES ($1, $2, $3, $4, $5, NOW() AT TIME ZONE 'UTC')
        """
        
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(
                    query,
                    session_id,
                    practitioner_id,
                    requested_time.astimezone(timezone.utc),
                    found_slot,
                    error_type
                )
                
            # Check for pattern of failures
            if not found_slot:
                await self._check_failure_pattern(practitioner_id, error_type)
                
        except Exception as e:
            logger.error(f"Failed to log booking attempt: {e}")
    
    async def _check_failure_pattern(
        self, 
        practitioner_id: str,
        error_type: str
    ):
        """Check if we have a pattern of failures"""
        query = """
            SELECT COUNT(*) as failure_count
            FROM booking_monitoring
            WHERE practitioner_id = $1
              AND error_type = $2
              AND NOT found_slot
              AND created_at > NOW() AT TIME ZONE 'UTC' - $3
        """
        
        async with self.pool.acquire() as conn:
            result = await conn.fetchrow(
                query,
                practitioner_id,
                error_type,
                self.time_window
            )
            
            if result['failure_count'] >= self.failure_threshold:
                logger.error(
                    f"ALERT: {result['failure_count']} booking failures "
                    f"for practitioner {practitioner_id} with error '{error_type}' "
                    f"in the last {self.time_window.total_seconds()/60} minutes"
                )
                
                # Invalidate cache for this practitioner
                await self._invalidate_practitioner_cache(practitioner_id)
    
    async def _invalidate_practitioner_cache(self, practitioner_id: str):
        """Invalidate all cache entries for a practitioner"""
        query = """
            UPDATE availability_cache
            SET is_stale = true
            WHERE practitioner_id = $1
              AND date >= CURRENT_DATE
        """
        
        async with self.pool.acquire() as conn:
            result = await conn.execute(query, practitioner_id)
            logger.info(f"Invalidated cache for practitioner {practitioner_id}")


# Add the monitoring table
MONITORING_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS booking_monitoring (
    id SERIAL PRIMARY KEY,
    session_id VARCHAR(100) NOT NULL,
    practitioner_id VARCHAR(50) NOT NULL,
    requested_time_utc TIMESTAMPTZ NOT NULL,
    found_slot BOOLEAN NOT NULL,
    error_type VARCHAR(50),
    created_at TIMESTAMPTZ DEFAULT (NOW() AT TIME ZONE 'UTC'),
    
    INDEX idx_monitoring_practitioner (practitioner_id, created_at DESC),
    INDEX idx_monitoring_errors (error_type, created_at DESC) WHERE NOT found_slot
);

-- Cleanup old monitoring data automatically
CREATE OR REPLACE FUNCTION cleanup_old_monitoring()
RETURNS void AS $$
BEGIN
    DELETE FROM booking_monitoring
    WHERE created_at < NOW() AT TIME ZONE 'UTC' - INTERVAL '7 days';
END;
$$ LANGUAGE plpgsql;
"""