"""
Robust parallel implementation for availability checking with rate limiting and error handling.
This module provides a faster alternative to the sequential availability checking.
"""

import asyncio
import logging
from typing import Dict, Any, List, Optional, Tuple, Set
from datetime import datetime, timedelta, date
from dataclasses import dataclass
from asyncio import Semaphore
import asyncpg

from cache_manager import CacheManager
from cliniko import ClinikoAPI
from models import ClinicData, NextAvailableResponse, TimeSlotData, PractitionerData, LocationData
from tools.timezone_utils import get_clinic_timezone, format_time_for_voice

logger = logging.getLogger(__name__)

# Configuration constants
MAX_CONCURRENT_API_CALLS = 25  # Optimized based on concurrency testing
API_CALL_DELAY = 0.1  # Reduced from 0.2 to 0.1 for faster processing
API_TIMEOUT = 10.0  # Balanced timeout: consistent with enhanced manager
PROGRESSIVE_SEARCH_DAYS = 7  # Search first 7 days, then expand if needed
MAX_RETRIES = 3  # Increased from 2 to 3 for better reliability

@dataclass
class SearchResult:
    """Container for search results with metadata"""
    criteria: Dict[str, Any]
    check_date: date
    slots: List[Dict[str, Any]]
    source: str  # 'cache' or 'api'
    response_time: float

class ParallelAvailabilityChecker:
    """Robust parallel availability checker with rate limiting and error handling"""
    
    def __init__(self, pool: asyncpg.Pool, cache: CacheManager, clinic: ClinicData):
        self.pool = pool
        self.cache = cache
        self.clinic = clinic
        self.api_semaphore = Semaphore(MAX_CONCURRENT_API_CALLS)
        self._api_call_count = 0
        self._cache_hit_count = 0
        self._start_time = None
    
    async def find_next_available_parallel(
        self,
        search_criteria: List[Dict[str, Any]],
        max_days: int,
        session_id: str,
        practitioner_name: Optional[str] = None,
        service_name: Optional[str] = None,
        location_name: Optional[str] = None,
        business_id: Optional[str] = None  # <-- add this param
    ) -> Dict[str, Any]:
        """
        Parallel implementation of find_next_available with robust error handling.
        """
        self._start_time = datetime.now()
        logger.info(f"Starting parallel search with {len(search_criteria)} criteria for {max_days} days")
        
        try:
            # Progressive search: start with fewer days, expand if needed
            search_days = min(PROGRESSIVE_SEARCH_DAYS, max_days)
            
            for attempt in range(2):  # Try progressive search, then full search
                if attempt == 1:
                    search_days = max_days
                    logger.info(f"Progressive search failed, expanding to {max_days} days")
                
                result = await self._search_days_parallel(
                    search_criteria, search_days, session_id,
                    practitioner_name, service_name, location_name, business_id  # <-- pass business_id
                )
                
                if result.get('found', False):
                    return result
            
            # No slots found in any search
            return self._create_no_slots_response(
                max_days, session_id, practitioner_name, service_name, location_name
            )
            
        except Exception as e:
            logger.error(f"Error in parallel availability search: {str(e)}")
            return {
                "success": False,
                "message": "I encountered an error while checking availability. Please try again.",
                "sessionId": session_id
            }
        finally:
            self._log_performance_metrics()
    
    async def _search_days_parallel(
        self,
        search_criteria: List[Dict[str, Any]],
        max_days: int,
        session_id: str,
        practitioner_name: Optional[str] = None,
        service_name: Optional[str] = None,
        location_name: Optional[str] = None,
        business_id: Optional[str] = None  # <-- add this param
    ) -> Dict[str, Any]:
        """Search for availability across multiple days in parallel"""
        
        search_start = datetime.now().date()
        
        # Check each day, but parallelize within each day
        for days_ahead in range(max_days):
            check_date = search_start + timedelta(days=days_ahead)
            logger.debug(f"Checking date: {check_date}")
            
            # Create tasks for all criteria on this date
            tasks = [
                self._check_criteria_date(criteria, check_date)
                for criteria in search_criteria
            ]
            
            # Execute in parallel with error handling
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Process results
            valid_results = []
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    logger.error(f"Task failed for criteria {i}: {str(result)}")
                    continue
                if result is not None:
                    valid_results.append(result)
            
            # If we found any slots, return the best one
            if valid_results:
                return self._select_best_result(valid_results, session_id, practitioner_name, business_id)  # <-- pass business_id
        
        # No slots found
        return {"found": False}
    
    async def _check_criteria_date(
        self, 
        criteria: Dict[str, Any], 
        check_date: date
    ) -> Optional[SearchResult]:
        """Check availability for one criteria on one date with retries and caching"""
        
        start_time = datetime.now()
        
        for attempt in range(MAX_RETRIES + 1):
            try:
                # Try cache first
                cached_slots = await self.cache.get_availability(
                    criteria['practitioner_id'],
                    criteria['business_id'],
                    check_date
                )
                
                if cached_slots is not None:
                    self._cache_hit_count += 1
                    if cached_slots:  # Only return if slots exist
                        return SearchResult(
                            criteria=criteria,
                            check_date=check_date,
                            slots=cached_slots,
                            source='cache',
                            response_time=(datetime.now() - start_time).total_seconds()
                        )
                    return None  # No slots in cache
                
                # Cache miss - need to call API
                async with self.api_semaphore:
                    self._api_call_count += 1
                    await asyncio.sleep(API_CALL_DELAY)  # Rate limiting
                    
                    slots = await asyncio.wait_for(
                        self._call_cliniko_api(criteria, check_date),
                        timeout=API_TIMEOUT
                    )
                    
                    # Cache the results (even if empty)
                    await self.cache.set_availability(
                        criteria['practitioner_id'],
                        criteria['business_id'],
                        check_date,
                        self.clinic.clinic_id,
                        slots
                    )
                    
                    if slots:
                        return SearchResult(
                            criteria=criteria,
                            check_date=check_date,
                            slots=slots,
                            source='api',
                            response_time=(datetime.now() - start_time).total_seconds()
                        )
                    
                    return None  # No slots available
                    
            except asyncio.TimeoutError:
                logger.warning(f"API timeout for {criteria['practitioner_name']} on {check_date} (attempt {attempt + 1})")
                if attempt == MAX_RETRIES:
                    return None
                await asyncio.sleep(1)  # Wait before retry
                
            except Exception as e:
                logger.error(f"Error checking availability for {criteria['practitioner_name']}: {str(e)}")
                if attempt == MAX_RETRIES:
                    return None
                await asyncio.sleep(1)  # Wait before retry
        
        return None
    
    async def _call_cliniko_api(self, criteria: Dict[str, Any], check_date: date) -> List[Dict[str, Any]]:
        """Make API call to Cliniko with proper error handling"""
        
        cliniko = ClinikoAPI(
            self.clinic.cliniko_api_key,
            self.clinic.cliniko_shard,
            "VoiceBookingSystem/1.0"
        )
        
        from_date = check_date.isoformat()
        to_date = check_date.isoformat()
        
        slots = await cliniko.get_available_times(
            criteria['business_id'],
            criteria['practitioner_id'],
            criteria['appointment_type_id'],
            from_date,
            to_date
        )
        
        # Filter out recently failed slots
        if slots:
            slots = await self._filter_failed_slots(criteria, check_date, slots)
        
        return slots
    
    async def _filter_failed_slots(
        self, 
        criteria: Dict[str, Any], 
        check_date: date, 
        slots: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Filter out slots that have recently failed booking attempts"""
        
        try:
            async with self.pool.acquire() as conn:
                failed_slots = await conn.fetch("""
                    SELECT appointment_time::text as time
                    FROM failed_booking_attempts
                    WHERE practitioner_id = $1
                      AND business_id = $2
                      AND appointment_date = $3
                      AND created_at > NOW() - INTERVAL '2 hours'
                """, criteria['practitioner_id'], criteria['business_id'], check_date)
                
                failed_times = {row['time'] for row in failed_slots}
                filtered_slots = [
                    slot for slot in slots 
                    if slot.get('appointment_start', '').split('T')[1][:5] not in failed_times
                ]
                
                if len(filtered_slots) != len(slots):
                    logger.info(f"Filtered out {len(slots) - len(filtered_slots)} failed slots")
                
                return filtered_slots
                
        except Exception as e:
            logger.error(f"Error filtering failed slots: {str(e)}")
            return slots  # Return original slots if filtering fails
    
    def _select_best_result(
        self, 
        results: List[SearchResult], 
        session_id: str, 
        practitioner_name: Optional[str] = None,
        business_id: Optional[str] = None  # <-- add this param
    ) -> Dict[str, Any]:
        """Select the best result from multiple available options"""
        
        # If business_id is specified, filter results to only that location
        if business_id:
            filtered_results = [r for r in results if r.criteria.get('business_id') == business_id]
            if filtered_results:
                results = filtered_results
        
        # Sort by number of slots available (prefer locations with more options)
        results.sort(key=lambda x: len(x.slots), reverse=True)
        
        # Build a map of (business_id, first_name) -> count to detect ambiguity
        from collections import Counter
        first_name_counts = Counter(
            (c['business_id'], c['practitioner_name'].split()[0])
            for c in [r.criteria for r in results]
        )
        
        best_result = results[0]
        criteria = best_result.criteria
        full_name = criteria['practitioner_name']
        first_name = full_name.split()[0] if full_name else "Unknown"
        # If ambiguous at this location, use full name as firstName
        if first_name_counts[(criteria['business_id'], first_name)] > 1:
            first_name_to_use = full_name
        else:
            first_name_to_use = first_name
        
        # Convert to local time
        earliest_slot = best_result.slots[0]  # Get the first (earliest) slot
        slot_utc = datetime.fromisoformat(earliest_slot['appointment_start'].replace('Z', '+00:00'))
        clinic_tz = get_clinic_timezone(self.clinic)
        slot_local = slot_utc.astimezone(clinic_tz)
        
        # Format the response message
        date_str = slot_local.strftime('%A, %B %d')
        time_str = format_time_for_voice(slot_local)
        
        if practitioner_name:
            message = f"{criteria['practitioner_name']}'s next availability for {criteria.get('service_name', 'appointment')} is {date_str} at {time_str} at {criteria['business_name']}."
        else:
            message = f"The next available {criteria.get('service_name', 'appointment')} is {date_str} at {time_str} with {criteria['practitioner_name']} at {criteria['business_name']}."
        
        # Add additional slots to message if available
        if len(best_result.slots) > 1:
            additional_slots = []
            for slot in best_result.slots[1:3]:  # Show up to 3 slots
                slot_time = datetime.fromisoformat(slot['appointment_start'].replace('Z', '+00:00'))
                slot_local = slot_time.astimezone(clinic_tz)
                additional_slots.append(slot_local.strftime('%I:%M %p'))
            
            if additional_slots:
                message += f" Also available at {', '.join(additional_slots)}."
        
        # Log performance info
        logger.info(f"Found slots via {best_result.source} in {best_result.response_time:.2f}s")
        
        response = NextAvailableResponse(
            success=True,
            sessionId=session_id,
            message=message,
            found=True,
            slot=TimeSlotData(
                date=date_str,
                time=time_str,
                displayTime=time_str
            ),
            practitioner=PractitionerData(
                id=criteria['practitioner_id'],
                name=full_name,
                firstName=first_name_to_use
            ),
            service=None,
            location=LocationData(
                id=criteria['business_id'],
                name=criteria['business_name']
            )
        )
        
        return response.dict()
    
    def _create_no_slots_response(
        self,
        max_days: int,
        session_id: str,
        practitioner_name: Optional[str] = None,
        service_name: Optional[str] = None,
        location_name: Optional[str] = None
    ) -> Dict[str, Any]:
        """Create response when no slots are found"""
        
        if practitioner_name:
            message = f"I couldn't find any available appointments with {practitioner_name} in the next {max_days} days."
        elif location_name:
            message = f"I couldn't find any available {service_name} appointments at {location_name} in the next {max_days} days."
        else:
            message = f"I couldn't find any available {service_name} appointments in the next {max_days} days."
        
        return {
            "success": True,
            "found": False,
            "message": message,
            "sessionId": session_id
        }
    
    def _log_performance_metrics(self):
        """Log performance metrics for monitoring"""
        if self._start_time:
            total_time = (datetime.now() - self._start_time).total_seconds()
            logger.info(f"Parallel search completed in {total_time:.2f}s - "
                       f"API calls: {self._api_call_count}, "
                       f"Cache hits: {self._cache_hit_count}") 


if __name__ == "__main__":
    # Simulate ambiguous practitioners at the same location
    class DummyClinic:
        cliniko_api_key = "dummy"
        cliniko_shard = "dummy"
        contact_email = "dummy@example.com"
        clinic_id = "clinic1"
        clinic_name = "Test Clinic"
        timezone = "Australia/Sydney"
    
    dummy_clinic = DummyClinic()
    dummy_cache = None
    dummy_pool = None
    checker = ParallelAvailabilityChecker(dummy_pool, dummy_cache, dummy_clinic)

    # Simulate two practitioners named Alex at the same location, and one at another location
    search_criteria = [
        {'practitioner_id': 'p1', 'practitioner_name': 'Alex Smith', 'business_id': 'b1', 'business_name': 'Main Clinic', 'appointment_type_id': 'a1', 'service_name': 'Physio'},
        {'practitioner_id': 'p2', 'practitioner_name': 'Alex Johnson', 'business_id': 'b1', 'business_name': 'Main Clinic', 'appointment_type_id': 'a1', 'service_name': 'Physio'},
        {'practitioner_id': 'p3', 'practitioner_name': 'Alex Brown', 'business_id': 'b2', 'business_name': 'Branch Clinic', 'appointment_type_id': 'a1', 'service_name': 'Physio'},
    ]
    # Simulate slots for each
    slots = [{'appointment_start': '2025-07-17T09:00:00Z'}]
    results = [
        SearchResult(criteria=search_criteria[0], check_date=date(2025, 7, 17), slots=slots, source='cache', response_time=0.1),
        SearchResult(criteria=search_criteria[1], check_date=date(2025, 7, 17), slots=slots, source='cache', response_time=0.1),
        SearchResult(criteria=search_criteria[2], check_date=date(2025, 7, 17), slots=slots, source='cache', response_time=0.1),
    ]
    # Patch timezone utility for test
    import types
    checker.clinic = dummy_clinic
    from tools import timezone_utils
    checker._select_best_result.__globals__['get_clinic_timezone'] = lambda clinic: timezone_utils.DEFAULT_TZ
    checker._select_best_result.__globals__['format_time_for_voice'] = lambda dt: dt.strftime('%I:%M %p')
    # Run test
    print("\n=== Ambiguous Practitioner Name Test ===")
    for r in results:
        output = checker._select_best_result([r], session_id="test-session", practitioner_name=None)
        print(f"Practitioner: {r.criteria['practitioner_name']}, business: {r.criteria['business_name']}, firstName in response: {output['practitioner']['firstName']}")
    # Test both ambiguous at same location
    output = checker._select_best_result(results[:2], session_id="test-session", practitioner_name=None)
    print(f"Ambiguous at same location: {output['practitioner']['firstName']}")
    # Test non-ambiguous at different location
    output = checker._select_best_result([results[2]], session_id="test-session", practitioner_name=None)
    print(f"Non-ambiguous at different location: {output['practitioner']['firstName']}") 