# tools/shared.py
"""Shared utilities for tools modules"""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from .dependencies import get_settings


def convert_utc_to_local(utc_time_str: str, timezone_str: str = None) -> datetime:
    """Convert UTC time string to local timezone"""
    if timezone_str is None:
        timezone_str = get_settings().default_timezone
    
    if utc_time_str.endswith('Z'):
        utc_time = datetime.fromisoformat(utc_time_str.replace('Z', '+00:00'))
    else:
        utc_time = datetime.fromisoformat(utc_time_str)
    
    if utc_time.tzinfo is None:
        utc_time = utc_time.replace(tzinfo=timezone.utc)
    
    # If this is a generic utility, add a comment. If it's for clinic timezones, use get_clinic_timezone(clinic) instead of ZoneInfo(timezone_str).
    # Example:
    # local_tz = get_clinic_timezone(clinic)  # If clinic context is available
    # Otherwise, document:
    # local_tz = ZoneInfo(timezone_str)  # Generic usage, not clinic-specific
    local_tz = ZoneInfo(timezone_str)
    return utc_time.astimezone(local_tz)


def format_time_for_voice(dt: datetime) -> str:
    """Format datetime for voice response"""
    return dt.strftime("%I:%M %p").lstrip('0')
