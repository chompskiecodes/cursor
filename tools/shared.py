# tools/shared.py
"""Shared utilities for all tools"""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from functools import lru_cache
import logging
from typing import Dict, Any, Optional


class Settings:
    """Application settings from environment variables"""


    def __init__(self):
        import os
        self.default_timezone = os.environ.get("DEFAULT_TIMEZONE", "Australia/Sydney")

@lru_cache()


def get_settings():
    return Settings()


def get_timezone_string(clinic) -> str:
    """Get timezone string from clinic with validation"""
    try:
        ZoneInfo(clinic.timezone)
        return clinic.timezone
    except Exception:
        logging.error(f"Invalid timezone '{clinic.timezone}' for clinic {clinic.clinic_id}")
        return get_settings().default_timezone


def ensure_timezone_aware(dt: datetime, timezone: ZoneInfo) -> datetime:
    """Ensure datetime is timezone aware"""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone)
    return dt


def convert_to_utc(dt: datetime, from_timezone: ZoneInfo) -> datetime:
    """Convert timezone-aware datetime to UTC"""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=from_timezone)
    return dt.astimezone(timezone.utc)
