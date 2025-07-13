"""
Enhanced Parallel Cliniko API Manager

This module provides a robust parallel processing system for Cliniko API calls with:
- Advanced rate limiting (59 calls per 60 seconds)
- Intelligent concurrency management (10 concurrent calls max)
- Comprehensive error handling with exponential backoff
- Performance monitoring and metrics
- Graceful degradation and fallback strategies
"""

import asyncio
import logging
import time
from typing import Dict, Any, List, Optional, Tuple, Callable, TypeVar, Awaitable
from datetime import datetime, timedelta, date
from dataclasses import dataclass, field
from asyncio import Semaphore, Lock
import asyncpg
from collections import defaultdict
from functools import partial

from cache_manager import CacheManager
from cliniko import ClinikoAPI
from models import ClinicData
from tools.timezone_utils import get_clinic_timezone, format_time_for_voice

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)  # Ensure debug logs are output
logger.debug("DEBUG LOGGING ENABLED in EnhancedParallelManager")

# Configuration constants
MAX_CONCURRENT_API_CALLS = 8  # Controlled parallelism for safety
API_CALL_DELAY = 0.1  # 100ms delay between API calls
API_TIMEOUT = 30.0  # Increased timeout for Cliniko API calls
MAX_RETRIES = 3  # Retry failed calls
RATE_LIMIT_CALLS_PER_MINUTE = 199  # Updated for Cliniko's 200/minute limit (1-call safety margin)
RATE_LIMIT_WINDOW = 60.0  # 60 seconds

# Progressive timeout strategy for parallel execution
PROGRESSIVE_TIMEOUTS = {
    'early_days': 8.0,    # Days 1-3: faster timeouts
    'mid_days': 12.0,     # Days 4-7: moderate timeouts  
    'late_days': 15.0     # Days 8+: longer timeouts for complex queries
}

T = TypeVar('T')

@dataclass
class APICallResult:
    """Container for API call results with metadata"""
    success: bool
    data: Any = None
    error: Optional[str] = None
    duration: float = 0.0
    retries: int = 0
    cached: bool = False

@dataclass
class PerformanceMetrics:
    """Container for performance metrics"""
    total_calls: int = 0
    successful_calls: int = 0
    failed_calls: int = 0
    cache_hits: int = 0
    total_duration: float = 0.0
    average_duration: float = 0.0
    rate_limit_delays: int = 0
    total_delay_time: float = 0.0
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None

class EnhancedRateLimiter:
    """Enhanced rate limiter with sliding window and intelligent delays"""
    
    def __init__(self, max_calls_per_minute: int = RATE_LIMIT_CALLS_PER_MINUTE):
        self.max_calls_per_minute = max_calls_per_minute
        self.call_times: List[float] = []
        self.lock = Lock()
        self.delay_count = 0
        self.total_delay_time = 0.0
    
    async def acquire(self) -> float:
        """Acquire permission to make an API call with rate limiting"""
        async with self.lock:
            now = time.monotonic()
            
            # Remove calls older than 60 seconds
            self.call_times = [t for t in self.call_times if now - t < RATE_LIMIT_WINDOW]
            
            if len(self.call_times) >= self.max_calls_per_minute:
                # Calculate wait time until oldest call expires
                oldest_call = self.call_times[0]
                wait_time = RATE_LIMIT_WINDOW - (now - oldest_call)
                
                if wait_time > 0:
                    self.delay_count += 1
                    self.total_delay_time += wait_time
                    logger.debug(f"Rate limit hit, waiting {wait_time:.2f}s")
                    await asyncio.sleep(wait_time)
                    now = time.monotonic()
                    # Clean up again after waiting
                    self.call_times = [t for t in self.call_times if now - t < RATE_LIMIT_WINDOW]
            
            self.call_times.append(now)
            return now

class EnhancedParallelManager:
    """Enhanced parallel manager for Cliniko API calls"""
    
    def __init__(self, pool: asyncpg.Pool, cache: CacheManager, clinic: ClinicData):
        self.pool = pool
        self.cache = cache
        self.clinic = clinic
        self.rate_limiter = EnhancedRateLimiter()
        self.semaphore = Semaphore(MAX_CONCURRENT_API_CALLS)
        self.metrics = PerformanceMetrics()
        self._cliniko_api: Optional[ClinikoAPI] = None
    
    @property
    def cliniko_api(self) -> ClinikoAPI:
        """Lazy initialization of Cliniko API"""
        if self._cliniko_api is None:
            self._cliniko_api = ClinikoAPI(
                self.clinic.cliniko_api_key,
                self.clinic.cliniko_shard,
                "VoiceBookingSystem/1.0"
            )
        return self._cliniko_api
    
    async def execute_parallel_calls(
        self,
        tasks: List[Callable[[], Awaitable[T]]],
        timeout: Optional[float] = None
    ) -> List[APICallResult]:
        """
        Execute multiple API calls in parallel with rate limiting and error handling
        
        Args:
            tasks: List of async functions to execute
            timeout: Optional timeout for the entire batch
            
        Returns:
            List of APICallResult objects
        """
        self.metrics.start_time = datetime.now()
        self.metrics.total_calls = len(tasks)
        
        logger.info(f"Starting parallel execution of {len(tasks)} tasks")
        
        async def execute_with_rate_limiting(task: Callable) -> APICallResult:
            """Execute a single task with rate limiting and error handling"""
            start_time = time.time()
            retries = 0
            
            for attempt in range(MAX_RETRIES + 1):
                try:
                    # Acquire rate limiter permission
                    await self.rate_limiter.acquire()
                    
                    # Acquire semaphore for concurrency control
                    async with self.semaphore:
                        # Execute the task with timeout (partial functions are called without args)
                        result = await asyncio.wait_for(task(), timeout=API_TIMEOUT)
                        
                        duration = time.time() - start_time
                        self.metrics.successful_calls += 1
                        self.metrics.total_duration += duration
                        
                        return APICallResult(
                            success=True,
                            data=result,
                            duration=duration,
                            retries=retries
                        )
                        
                except asyncio.TimeoutError:
                    retries += 1
                    logger.warning(f"API call timeout (attempt {attempt + 1}/{MAX_RETRIES + 1})")
                    if attempt == MAX_RETRIES:
                        duration = time.time() - start_time
                        self.metrics.failed_calls += 1
                        logger.error(f"Task failed after {MAX_RETRIES + 1} attempts due to timeout")
                        return APICallResult(
                            success=False,
                            error="Timeout",
                            duration=duration,
                            retries=retries
                        )
                    await asyncio.sleep(2 ** attempt)  # Exponential backoff
                    
                except Exception as e:
                    retries += 1
                    logger.error(f"API call error (attempt {attempt + 1}/{MAX_RETRIES + 1}): {str(e)}")
                    if attempt == MAX_RETRIES:
                        duration = time.time() - start_time
                        self.metrics.failed_calls += 1
                        logger.error(f"Task failed after {MAX_RETRIES + 1} attempts due to error: {str(e)}")
                        return APICallResult(
                            success=False,
                            error=str(e),
                            duration=duration,
                            retries=retries
                        )
                    await asyncio.sleep(2 ** attempt)  # Exponential backoff
        
        try:
            # Execute all tasks in parallel
            if timeout:
                results = await asyncio.wait_for(
                    asyncio.gather(*[execute_with_rate_limiting(task) for task in tasks], return_exceptions=True),
                    timeout=timeout
                )
            else:
                results = await asyncio.gather(*[execute_with_rate_limiting(task) for task in tasks], return_exceptions=True)
            
            # Process results
            processed_results = []
            for result in results:
                if isinstance(result, Exception):
                    processed_results.append(APICallResult(
                        success=False,
                        error=str(result),
                        duration=0.0
                    ))
                    self.metrics.failed_calls += 1
                else:
                    processed_results.append(result)
            
            self.metrics.end_time = datetime.now()
            self._update_metrics()
            self._log_performance_summary()
            
            return processed_results
            
        except asyncio.TimeoutError:
            logger.error(f"Batch timeout after {timeout} seconds")
            self.metrics.end_time = datetime.now()
            return [APICallResult(success=False, error="Batch timeout", duration=timeout or 0.0)]
    
    async def check_availability_parallel(
        self,
        search_criteria: List[Dict[str, Any]],
        max_days: int = 14,
        session_id: str = ""
    ) -> Dict[str, Any]:
        """
        Check availability in parallel for multiple criteria and dates
        """
        logger.info(f"Starting parallel availability check for {len(search_criteria)} criteria over {max_days} days")
        tasks = []
        # If criteria already have check_date, use it directly (enhanced endpoint)
        if search_criteria and 'check_date' in search_criteria[0]:
            for criteria in search_criteria:
                task = partial(self._check_single_availability, criteria, criteria['check_date'])
                tasks.append(task)
        else:
            # Legacy: generate for all days
            search_start = datetime.now().date()
            for days_ahead in range(max_days):
                check_date = search_start + timedelta(days=days_ahead)
                for criteria in search_criteria:
                    task = partial(self._check_single_availability, criteria, check_date)
                    tasks.append(task)
        logger.info(f"Created {len(tasks)} availability check tasks")
        results = await self.execute_parallel_calls(tasks, timeout=90.0)
        return self._process_availability_results(results, search_criteria, max_days, session_id)
    
    async def _check_single_availability(
        self, 
        criteria: Dict[str, Any], 
        check_date: date
    ) -> Optional[Dict[str, Any]]:
        """Check availability for a single criteria on a single date"""
        cache_key = (criteria['practitioner_id'], criteria['business_id'], check_date)
        logger.info(f"[DEBUG] Checking cache for key: {cache_key}")
        # Try cache first
        cached_slots = await self.cache.get_availability(
            criteria['practitioner_id'],
            criteria['business_id'],
            check_date
        )
        logger.info(f"[DEBUG] Cache value for key {cache_key}: {cached_slots}")
        
        if cached_slots is not None:
            self.metrics.cache_hits += 1
            logger.info(f"[DEBUG] Task: Cache hit for criteria={criteria}, check_date={check_date}, slots={cached_slots}")
            if cached_slots:
                return {
                    'criteria': criteria,
                    'check_date': check_date,
                    'slots': cached_slots,
                    'source': 'cache'
                }
            return None
        
        # Cache miss - call API
        try:
            from_date = check_date.isoformat()
            to_date = check_date.isoformat()
            logger.info(f"[DEBUG] Calling Cliniko API for key: {cache_key}")
            slots = await self.cliniko_api.get_available_times(
                criteria['business_id'],
                criteria['practitioner_id'],
                criteria['appointment_type_id'],
                from_date,
                to_date
            )
            logger.info(f"[DEBUG] Raw API response for key {cache_key}: {slots}")
            # Cache the results (even if empty)
            await self.cache.set_availability(
                criteria['practitioner_id'],
                criteria['business_id'],
                check_date,
                self.clinic.clinic_id,
                slots
            )
            
            if slots and len(slots) > 0:
                return {
                    'criteria': criteria,
                    'check_date': check_date,
                    'slots': slots,
                    'source': 'api'
                }
            
            # Return None to indicate no slots found (this is a successful result)
            return None
            
        except Exception as e:
            logger.error(f"Error checking availability for {criteria.get('practitioner_name', 'Unknown')}: {str(e)}")
            raise
    
    def _process_availability_results(
        self,
        results: List[APICallResult],
        search_criteria: List[Dict[str, Any]],
        max_days: int,
        session_id: str
    ) -> Dict[str, Any]:
        """Process availability results and find the best slots (up to 2)"""
        
        # Extract successful results (including those that returned None for no availability)
        all_slots = []
        for result in results:
            if result.success and result.data:
                for slot in result.data['slots']:
                    slot_datetime = datetime.fromisoformat(slot['appointment_start'].replace('Z', '+00:00'))
                    all_slots.append((slot_datetime, slot, result.data['criteria'], result.data['check_date'], result.data['source']))
        print(f"[DEBUG] Aggregation: Found {len(all_slots)} total slots across all results.")
        print(f"[DEBUG] all_slots: {all_slots}")
        # Deduplicate slots by (appointment_start, practitioner_id, business_id)
        unique_slot_keys = set()
        deduped_slots = []
        for slot_tuple in all_slots:
            slot_dt, slot, criteria, check_date, source = slot_tuple
            key = (slot['appointment_start'], criteria['practitioner_id'], criteria['business_id'])
            if key not in unique_slot_keys:
                unique_slot_keys.add(key)
                deduped_slots.append(slot_tuple)
        print(f"[DEBUG] Deduplication: Reduced to {len(deduped_slots)} unique slots.")
        print(f"[DEBUG] deduped_slots: {deduped_slots}")

        # Always include all_slots in the result for endpoint aggregation
        result_dict = {
            'all_slots': all_slots
        }

        if not deduped_slots:
            print(f"[DEBUG] No slots found after deduplication. Returning error response.")
            result_dict.update(self._create_no_availability_response(max_days, session_id))
            return result_dict
        
        # Sort all slots by datetime and pick up to 2 earliest
        deduped_slots.sort(key=lambda tup: tup[0])
        selected_slots = deduped_slots[:2]
        print(f"[DEBUG] selected_slots: {selected_slots}")
        
        # Format up to 2 slots for the response
        slot_msgs = []
        for slot_dt, slot, criteria, check_date, source in selected_slots:
            slot_utc = slot_dt
            clinic_tz = get_clinic_timezone(self.clinic)
            slot_local = slot_utc.astimezone(clinic_tz)
            date_str = slot_local.strftime('%A, %B %d')
            time_str = format_time_for_voice(slot_local)  # Use format_time_for_voice to match sequential endpoint
            slot_msgs.append(f"{date_str} at {time_str} at {criteria['business_name']}")
        print(f"[DEBUG] slot_msgs: {slot_msgs}")
        # Compose message
        practitioner = selected_slots[0][2]['practitioner_name']
        treatment = selected_slots[0][2].get('service_name', 'appointment')
        if len(slot_msgs) == 2:
            message = f"{practitioner}'s next availability for {treatment} is {slot_msgs[0]} and {slot_msgs[1]}."
        else:
            message = f"{practitioner}'s next availability for {treatment} is {slot_msgs[0]}."
        
        # Build response
        print(f"[DEBUG] Returning success response with slots: {slot_msgs}")
        result_dict.update({
            "success": True,
            "found": True,
            "message": message,
            "sessionId": session_id,
            "slots": slot_msgs,
            "available_times": slot_msgs,
            "practitioner": {
                "id": selected_slots[0][2]['practitioner_id'],
                "name": selected_slots[0][2]['practitioner_name']
            },
            "service": selected_slots[0][2].get('service_name', 'appointment'),
            "date": slot_msgs[0].split(' at ')[0],
            "time": slot_msgs[0].split(' at ')[1] if ' at ' in slot_msgs[0] else '',
            "location": {
                "id": selected_slots[0][2]['business_id'],
                "name": selected_slots[0][2]['business_name']
            }
        })
        return result_dict
    
    def _create_availability_response(self, slot_data: Dict[str, Any], session_id: str) -> Dict[str, Any]:
        """Create response for found availability - match sequential endpoint format"""
        
        slot = slot_data['slot']
        criteria = slot_data['criteria']
        
        # Convert to local time
        slot_utc = datetime.fromisoformat(slot['appointment_start'].replace('Z', '+00:00'))
        clinic_tz = get_clinic_timezone(self.clinic)
        slot_local = slot_utc.astimezone(clinic_tz)
        
        date_str = slot_local.strftime('%A, %B %d')
        time_str = format_time_for_voice(slot_local)  # Use format_time_for_voice to match sequential endpoint
        
        # Format message to match sequential endpoint
        message = f"{criteria['practitioner_name']}'s next availability for {criteria.get('service_name', 'appointment')} is {date_str} at {time_str} at {criteria['business_name']}."
        
        return {
            "success": True,
            "found": True,
            "message": message,
            "sessionId": session_id,
            "slots": [f"{date_str} at {time_str} at {criteria['business_name']}"],
            "available_times": [f"{date_str} at {time_str} at {criteria['business_name']}"],
            "practitioner": {
                "id": criteria['practitioner_id'],
                "name": criteria['practitioner_name']
            },
            "service": criteria.get('service_name', 'appointment'),
            "date": date_str,
            "time": time_str,
            "location": {
                "id": criteria['business_id'],
                "name": criteria['business_name']
            }
        }
    
    def _create_no_availability_response(self, max_days: int, session_id: str) -> Dict[str, Any]:
        """Create response when no availability is found - match sequential endpoint format"""
        
        return {
            "success": False,
            "found": False,
            "message": f"I couldn't find any available appointments in the next {max_days} days.",
            "sessionId": session_id,
            "available_times": []
        }
    
    def _update_metrics(self):
        """Update performance metrics"""
        if self.metrics.total_calls > 0:
            self.metrics.average_duration = self.metrics.total_duration / self.metrics.total_calls
        
        self.metrics.rate_limit_delays = self.rate_limiter.delay_count
        self.metrics.total_delay_time = self.rate_limiter.total_delay_time
    
    def _log_performance_summary(self):
        """Log performance summary"""
        if self.metrics.start_time and self.metrics.end_time:
            total_time = (self.metrics.end_time - self.metrics.start_time).total_seconds()
            
            logger.info(f"Parallel execution completed in {total_time:.2f}s")
            logger.info(f"  Total calls: {self.metrics.total_calls}")
            logger.info(f"  Successful: {self.metrics.successful_calls}")
            logger.info(f"  Failed: {self.metrics.failed_calls}")
            logger.info(f"  Cache hits: {self.metrics.cache_hits}")
            logger.info(f"  Average duration: {self.metrics.average_duration:.3f}s")
            logger.info(f"  Rate limit delays: {self.metrics.rate_limit_delays}")
            logger.info(f"  Total delay time: {self.metrics.total_delay_time:.2f}s")
            
            success_rate = (self.metrics.successful_calls / self.metrics.total_calls) * 100 if self.metrics.total_calls > 0 else 0
            logger.info(f"  Success rate: {success_rate:.1f}%")
    
    def get_metrics(self) -> PerformanceMetrics:
        """Get current performance metrics"""
        return self.metrics 