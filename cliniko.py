# cliniko.py
import httpx
import base64
import logging
from typing import Dict, Any, List, Optional
from datetime import timedelta
import asyncio
import time

logger = logging.getLogger(__name__)

# === Cliniko API Functions ===
class ClinikoAPI:
    # Shared leaky bucket limiter: 199 calls per 60 seconds
    _rate_limiter_lock = asyncio.Lock()
    _rate_limiter_calls = []  # timestamps of last 199 calls
    _rate_limiter_max_calls = 199
    _rate_limiter_period = 60.0

    @classmethod
    async def _leaky_bucket_acquire(cls):
        async with cls._rate_limiter_lock:
            now = time.monotonic()
            # Remove calls older than 60 seconds
            cls._rate_limiter_calls = [t for t in cls._rate_limiter_calls if now - t < cls._rate_limiter_period]
            if len(cls._rate_limiter_calls) >= cls._rate_limiter_max_calls:
                oldest_call = cls._rate_limiter_calls[0]
                wait_time = cls._rate_limiter_period - (now - oldest_call)
                if wait_time > 0:
                    await asyncio.sleep(wait_time)
                    now = time.monotonic()
                    cls._rate_limiter_calls = [t for t in cls._rate_limiter_calls if now - t < cls._rate_limiter_period]
            cls._rate_limiter_calls.append(now)

    def __init__(self, api_key: str, shard: str, user_agent: str):
        self.base_url = f"https://api.{shard}.cliniko.com/v1"
        
        # Cliniko expects "Basic {base64(api_key:)}" - note the colon at the end
        # The API key itself is the username, password is empty
        auth_string = f"{api_key}:"
        auth_bytes = auth_string.encode('ascii')
        auth_b64 = base64.b64encode(auth_bytes).decode('ascii')
        
        self.headers = {
            "Authorization": f"Basic {auth_b64}",
            "Accept": "application/json",
            "User-Agent": f"VoiceBookingSystem ({user_agent})",
            "Content-Type": "application/json"
        }
        self.timeout = httpx.Timeout(30.0, connect=5.0)
    
    async def find_patient(self, phone: str) -> Optional[Dict[str, Any]]:
        await self._leaky_bucket_acquire()
        """Find patient by phone number with EXACT matching"""
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                response = await client.get(
                    f"{self.base_url}/patients",
                    headers=self.headers,
                    params={"phone": phone}
                )
                if response.status_code == 200:
                    patients = response.json().get('patients', [])
                    
                    # CRITICAL: Filter for EXACT phone match
                    # Cliniko might return partial matches, we need exact
                    exact_matches = []
                    for patient in patients:
                        phone_numbers = patient.get('phone_numbers', [])
                        for phone_obj in phone_numbers:
                            if phone_obj.get('number') == phone:
                                logger.info(f"Found exact phone match for patient {patient['id']}")
                                return patient
                    
                    # Log summary instead of individual patients
                    if patients:
                        # Only log summary at DEBUG level - not WARNING
                        logger.debug(f"Cliniko returned {len(patients)} patients for phone '{phone}' but none matched exactly")
                        # Log first 3 patients only if debug logging is enabled
                        if logger.isEnabledFor(logging.DEBUG):
                            for i, p in enumerate(patients[:3]):
                                phones = [ph.get('number', 'N/A') for ph in p.get('phone_numbers', [])]
                                logger.debug(f"  Sample patient {i+1}: {p.get('first_name')} {p.get('last_name')}, phones: {phones}")
                            if len(patients) > 3:
                                logger.debug(f"  ... and {len(patients) - 3} more patients")
                    
                    return None  # No exact match found
                    
            except httpx.RequestError as e:
                logger.error(f"Cliniko API error finding patient: {str(e)}")
            return None
    
    async def create_patient(self, patient_data: Dict[str, Any]) -> Dict[str, Any]:
        await self._leaky_bucket_acquire()
        """Create new patient"""
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.base_url}/patients",
                headers=self.headers,
                json=patient_data
            )
            response.raise_for_status()
            return response.json()
    
    async def get_available_times(self, business_id: str, practitioner_id: str, 
                                  appointment_type_id: str, from_date: str, to_date: str) -> List[Dict[str, Any]]:
        await self._leaky_bucket_acquire()
        """Get available appointment times"""
        url = f"{self.base_url}/businesses/{business_id}/practitioners/{practitioner_id}/appointment_types/{appointment_type_id}/available_times"
        params = {"from": from_date, "to": to_date}
        logger.info(f"[ClinikoAPI] GET {url}")
        logger.info(f"[ClinikoAPI] Headers: {self.headers}")
        logger.info(f"[ClinikoAPI] Params: {params}")
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(
                url,
                headers=self.headers,
                params=params
            )
            logger.info(f"[ClinikoAPI] Response: {response.text}")
            response.raise_for_status()
            return response.json().get('available_times', [])
    
    async def create_appointment(self, appointment_data: Dict[str, Any]) -> Dict[str, Any]:
        await self._leaky_bucket_acquire()
        """Create appointment"""
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.base_url}/appointments",
                headers=self.headers,
                json=appointment_data
            )
            response.raise_for_status()
            return response.json()
    
    async def get_appointment(self, appointment_id: str) -> Optional[Dict[str, Any]]:
        await self._leaky_bucket_acquire()
        """Get appointment details"""
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                response = await client.get(
                    f"{self.base_url}/appointments/{appointment_id}",
                    headers=self.headers
                )
                if response.status_code == 200:
                    return response.json()
            except httpx.RequestError as e:
                logger.error(f"Cliniko API error getting appointment: {str(e)}")
            return None
    
    async def cancel_appointment(self, appointment_id: str) -> bool:
        await self._leaky_bucket_acquire()
        """Cancel appointment"""
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                response = await client.delete(
                    f"{self.base_url}/appointments/{appointment_id}",
                    headers=self.headers
                )
                return response.status_code == 204
            except httpx.RequestError as e:
                logger.error(f"Cliniko API error cancelling appointment: {str(e)}")
                return False
    
    async def get_all_pages(self, endpoint: str, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        await self._leaky_bucket_acquire()
        """
        Get all pages of results from an endpoint
        
        Args:
            endpoint: The API endpoint (e.g., 'appointments', 'practitioners')
            params: Optional query parameters (e.g., {'q[]': 'updated_at:>2024-01-01T00:00:00Z'})
        
        Returns:
            List of all items from all pages
        """
        all_items = []
        url = f"{self.base_url}/{endpoint}"
        
        # Convert params to proper format if provided
        query_params = {}
        if params:
            for key, value in params.items():
                if key == 'q[]' and isinstance(value, str):
                    # Handle q[] parameter specially - it can be repeated
                    query_params[key] = value
                else:
                    query_params[key] = value
        
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            while url:
                try:
                    # Include query params only on first request
                    # (pagination URLs already include necessary params)
                    if url == f"{self.base_url}/{endpoint}" and query_params:
                        response = await client.get(
                            url, 
                            headers=self.headers,
                            params=query_params
                        )
                    else:
                        response = await client.get(url, headers=self.headers)
                    
                    response.raise_for_status()
                    data = response.json()
                    
                    # Log for debugging
                    if params and 'q[]' in params:
                        logger.debug(f"Filtered {endpoint} query returned {len(data.get(endpoint, []))} items")
                    
                    # Extract items based on endpoint
                    items_key = endpoint  # Most endpoints return data under their own name
                    if endpoint in data:
                        all_items.extend(data[endpoint])
                    else:
                        # Some endpoints might return data differently
                        logger.warning(f"No '{endpoint}' key in response. Keys: {list(data.keys())}")
                        # Try to extract data from the response
                        for key, value in data.items():
                            if isinstance(value, list) and key != 'links':
                                all_items.extend(value)
                                break
                    
                    # Check for next page
                    links = data.get('links', {})
                    url = links.get('next')
                    
                    # Rate limit protection
                    await asyncio.sleep(0.1)
                    
                except httpx.HTTPStatusError as e:
                    logger.error(f"HTTP error fetching {endpoint}: {e.response.status_code} - {e.response.text}")
                    raise
                except Exception as e:
                    logger.error(f"Error fetching {endpoint}: {str(e)}")
                    raise
        
        return all_items