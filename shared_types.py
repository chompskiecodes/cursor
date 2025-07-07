"""Shared type definitions to avoid circular imports"""
from typing import Protocol, Any, Optional, List, Dict
from datetime import date
import asyncpg


class CacheManagerProtocol(Protocol):
    """Protocol for CacheManager to avoid circular imports"""
    pool: asyncpg.Pool

    async def get_availability(
        self, practitioner_id: str, business_id: str, check_date: date
    ) -> Optional[List[Dict[str, Any]]]: ...

    async def set_availability(
        self, practitioner_id: str, business_id: str, check_date: date,
        clinic_id: str, slots: List[Dict[str, Any]]
    ) -> bool: ...

    async def invalidate_availability(
        self, practitioner_id: str, business_id: str, check_date: date
    ) -> bool: ...

    async def get_patient(
        self, phone_normalized: str, clinic_id: str
    ) -> Optional[Dict[str, Any]]: ...

    async def set_patient(
        self, phone_normalized: str, clinic_id: str, patient_id: str,
        patient_data: Dict[str, Any]
    ) -> bool: ...

    async def get_service_matches(
        self, clinic_id: str, search_term: str
    ) -> Optional[List[Dict[str, Any]]]: ...

    async def set_service_matches(
        self, clinic_id: str, search_term: str, matches: List[Dict[str, Any]]
    ) -> bool: ...

    async def get_booking_context(
        self, phone_normalized: str
    ) -> Optional[Dict[str, Any]]: ...

    async def set_booking_context(
        self, phone_normalized: str, clinic_id: str, context_data: Dict[str, Any]
    ) -> bool: ...
