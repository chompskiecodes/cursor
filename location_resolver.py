# location_resolver.py
"""
Simplified location resolver for ElevenLabs voice agent integration.
Provides clear, unambiguous responses for tool chaining.
"""

import asyncpg
import logging
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime
from difflib import SequenceMatcher
from utils import normalize_phone
from models import LocationResolverRequest, LocationResolverResponse, LocationData
from shared_types import CacheManagerProtocol

logger = logging.getLogger(__name__)

# === Helper Functions ===

def normalize_location_query(query: str) -> str:
    """Normalize location query for matching"""
    if not query:
        return ""
    
    # Common normalizations
    normalized = query.lower().strip()
    
    # Remove common filler words
    filler_words = ['the', 'at', 'in', 'clinic', 'location', 'branch', 'office', 'place']
    words = normalized.split()
    words = [w for w in words if w not in filler_words or len(words) == 1]
    normalized = ' '.join(words)
    
    return normalized

def calculate_location_score(query: str, business_name: str, aliases: List[str], is_primary: bool) -> Tuple[float, str]:
    """
    Calculate match score for a location
    Returns: (score, match_reason)
    """
    query_norm = normalize_location_query(query)
    business_norm = normalize_location_query(business_name)
    
    # Exact match
    if query_norm == business_norm:
        return (1.0, "exact_match")
    
    # Check aliases
    for alias in aliases:
        if query_norm == normalize_location_query(alias):
            return (0.95, f"alias_match:{alias}")
    
    # Common references to primary location
    primary_references = ['main', 'primary', 'first', 'default', 'usual', 'regular', 'normal', 'head']
    if is_primary and any(ref in query_norm for ref in primary_references):
        return (0.85, "primary_reference")
    
    # Partial matches
    if query_norm in business_norm:
        return (0.7, "partial_match")
    
    if business_norm in query_norm:
        return (0.6, "contains_name")
    
    # Fuzzy matching
    similarity = SequenceMatcher(None, query_norm, business_norm).ratio()
    if similarity > 0.6:
        return (similarity, "fuzzy_match")
    
    # Number-based matching (e.g., "location 1", "2nd clinic")
    import re
    query_numbers = re.findall(r'\d+', query_norm)
    business_numbers = re.findall(r'\d+', business_norm)
    
    if query_numbers and business_numbers:
        if query_numbers[0] == business_numbers[0]:
            return (0.8, "number_match")
    
    # Ordinal matching (first, second, third)
    ordinals = {
        'first': '1', 'second': '2', 'third': '3', 'fourth': '4', 'fifth': '5',
        '1st': '1', '2nd': '2', '3rd': '3', '4th': '4', '5th': '5'
    }
    
    for ordinal, number in ordinals.items():
        if ordinal in query_norm:
            if number in business_norm or (is_primary and ordinal in ['first', '1st']):
                return (0.75, f"ordinal_match:{ordinal}")
    
    return (0.0, "no_match")

# === Database Functions ===

async def get_clinic_locations_cached(
    clinic_id: str, 
    pool: asyncpg.Pool,
    cache: CacheManagerProtocol
) -> List[Dict[str, Any]]:
    """Get all locations for a clinic with caching"""
    
    # Try cache first
    cache_key = f"locations:{clinic_id}"
    cached = await cache.get_service_matches(clinic_id, cache_key)
    if cached:
        logger.info(f"Location cache hit for clinic {clinic_id}")
        return cached
    
    # Cache miss - fetch from database
    query = """
        SELECT 
            b.business_id,
            b.business_name,
            b.is_primary,
            COALESCE(
                ARRAY_AGG(DISTINCT la.alias) FILTER (WHERE la.alias IS NOT NULL),
                '{}'::text[]
            ) as aliases
        FROM businesses b
        LEFT JOIN location_aliases la ON b.business_id = la.business_id
        WHERE b.clinic_id = $1
        GROUP BY b.business_id, b.business_name, b.is_primary
        ORDER BY b.is_primary DESC, b.business_name
    """
    
    async with pool.acquire() as conn:
        rows = await conn.fetch(query, clinic_id)
        locations = [dict(row) for row in rows]
        
        # Cache the results
        await cache.set_service_matches(clinic_id, cache_key, locations)
        
        return locations

async def get_caller_history(
    phone: str, 
    clinic_id: str, 
    pool: asyncpg.Pool,
    cache: CacheManagerProtocol
) -> Optional[Dict[str, Any]]:
    """Get the most common location for a returning caller with caching"""
    
    # Check booking context cache first
    phone_normalized = normalize_phone(phone)
    context = await cache.get_booking_context(phone_normalized)
    
    if context and 'preferred_location' in context:
        logger.info(f"Found preferred location in context cache")
        return context['preferred_location']
    
    # Query database for history
    query = """
        SELECT 
            a.business_id,
            b.business_name,
            COUNT(*) as visit_count
        FROM appointments a
        JOIN businesses b ON a.business_id = b.business_id
        JOIN patients p ON a.patient_id = p.patient_id
        WHERE p.phone_number = $1 
          AND a.clinic_id = $2
          AND a.status IN ('booked', 'completed')
          AND a.starts_at > NOW() - INTERVAL '12 months'
        GROUP BY a.business_id, b.business_name
        ORDER BY visit_count DESC
        LIMIT 1
    """
    
    async with pool.acquire() as conn:
        row = await conn.fetchrow(query, phone_normalized, clinic_id)
        
        if row:
            result = dict(row)
            # Update booking context with preferred location
            context = context or {}
            context['preferred_location'] = result
            await cache.set_booking_context(phone_normalized, clinic_id, context)
            
            return result
    
    return None

async def get_location_by_name(
    clinic_id: str,
    location_name: str,
    pool: asyncpg.Pool
) -> Optional[Dict[str, Any]]:
    """Get location details by name"""
    query = """
        SELECT business_id, business_name, is_primary
        FROM businesses
        WHERE clinic_id = $1 AND business_name = $2
        LIMIT 1
    """
    
    async with pool.acquire() as conn:
        row = await conn.fetchrow(query, clinic_id, location_name)
        return dict(row) if row else None

# === Main Resolution Class ===

class LocationResolver:
    """Location resolver with caching support"""
    
    def __init__(self, pool: asyncpg.Pool, cache: CacheManagerProtocol):
        self.pool = pool
        self.cache = cache
    
    async def resolve_location(
        self,
        request: LocationResolverRequest,
        clinic_id: str
    ) -> LocationResolverResponse:
        """
        Resolve a location query to a specific business location
        Returns simplified response for ElevenLabs agent
        """
        
        start_time = datetime.now()
        
        # Get all locations for the clinic (cached)
        locations = await get_clinic_locations_cached(clinic_id, self.pool, self.cache)
        
        if not locations:
            return LocationResolverResponse(
                success=False,
                sessionId=request.sessionId,
                resolved=False,
                needs_clarification=False,
                message="I couldn't find any locations for this clinic. Please contact the clinic directly.",
                confidence=0.0
            )
        
        # Single location - easy case
        if len(locations) == 1:
            location = locations[0]
            return LocationResolverResponse(
                success=True,
                sessionId=request.sessionId,
                resolved=True,
                needs_clarification=False,
                message=f"I'll book you at {location['business_name']}",
                selected_location=LocationData(
                    id=location['business_id'],
                    name=location['business_name']
                ),
                confidence=1.0
            )
        
        # Score each location
        scored_locations = []
        for location in locations:
            score, reason = calculate_location_score(
                request.locationQuery,
                location['business_name'],
                location.get('aliases', []),
                location['is_primary']
            )
            
            scored_locations.append({
                'location': location,
                'score': score,
                'reason': reason
            })
        
        # Sort by score
        scored_locations.sort(key=lambda x: x['score'], reverse=True)
        best_match = scored_locations[0]
        second_best = scored_locations[1] if len(scored_locations) > 1 else None
        
        # Check caller history if low confidence
        if best_match['score'] < 0.7 and request.callerPhone:
            caller_history = await get_caller_history(
                request.callerPhone,
                clinic_id,
                self.pool,
                self.cache
            )
            
            if caller_history:
                # Check if their usual location matches any of our locations
                for scored in scored_locations:
                    if scored['location']['business_id'] == caller_history['business_id']:
                        # Boost score for their usual location
                        scored['score'] = min(scored['score'] + 0.3, 0.9)
                        scored['reason'] = f"{scored['reason']},usual_location"
                        break
                
                # Re-sort after boosting
                scored_locations.sort(key=lambda x: x['score'], reverse=True)
                best_match = scored_locations[0]
        
        # Log response time
        response_time = (datetime.now() - start_time).total_seconds() * 1000
        logger.info(f"Location resolution took {response_time:.2f}ms")
        
        # High confidence - single clear match
        if best_match['score'] >= 0.8:
            return LocationResolverResponse(
                success=True,
                sessionId=request.sessionId,
                resolved=True,
                needs_clarification=False,
                message=f"I'll book you at {best_match['location']['business_name']}",
                selected_location=LocationData(
                    id=best_match['location']['business_id'],
                    name=best_match['location']['business_name']
                ),
                confidence=best_match['score']
            )
        
        # Medium confidence - ask for confirmation with top options
        elif best_match['score'] >= 0.6:
            # Build options list with LocationData objects
            options = [
                LocationData(
                    id=best_match['location']['business_id'],
                    name=best_match['location']['business_name']
                )
            ]
            
            # Add second option if close
            if second_best and second_best['score'] >= best_match['score'] * 0.8:
                options.append(LocationData(
                    id=second_best['location']['business_id'],
                    name=second_best['location']['business_name']
                ))
                message = f"Did you mean our {options[0].name} or {options[1].name}?"
            else:
                message = f"Did you mean our {options[0].name}?"
            
            return LocationResolverResponse(
                success=True,
                sessionId=request.sessionId,
                resolved=False,
                needs_clarification=True,
                message=message,
                options=options,
                confidence=best_match['score']
            )
        
        # Low confidence - show ALL locations for clarification
        else:
            # Always show all available locations when confidence is low
            options = [
                LocationData(
                    id=loc['location']['business_id'],
                    name=loc['location']['business_name']
                )
                for loc in scored_locations  # Include ALL locations, not just top 3
            ]
            
            # Build natural message listing all locations
            if len(options) == 2:
                message = f"We have two locations: {options[0].name} and {options[1].name}. Which one would you prefer?"
            elif len(options) == 3:
                message = f"We have locations at {options[0].name}, {options[1].name}, and {options[2].name}. Which location would you prefer?"
            else:
                # For more than 3 locations, use a more general message
                location_names = [opt.name for opt in options]
                last = location_names.pop()
                message = f"We have locations at {', '.join(location_names)}, and {last}. Which location would you prefer?"
            
            return LocationResolverResponse(
                success=True,
                sessionId=request.sessionId,
                resolved=False,
                needs_clarification=True,
                message=message,
                options=options,
                confidence=0.0
            )