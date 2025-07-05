# tools/timezone_utils.py
"""Centralized timezone handling utilities"""

from datetime import datetime, date, time, timezone as tz
from zoneinfo import ZoneInfo
from typing import Union, Optional
import logging
import os

logger = logging.getLogger(__name__)

# Define timezone constants
UTC = tz.utc
DEFAULT_TIMEZONE_STR = os.environ.get("DEFAULT_TIMEZONE", "Australia/Sydney")
DEFAULT_TZ = ZoneInfo(DEFAULT_TIMEZONE_STR)


def ensure_utc(dt: datetime) -> datetime:
    """Ensure datetime is in UTC"""
    if dt.tzinfo is None:
        # Assume naive datetimes are in Sydney timezone
        logger.warning(f"Converting naive datetime {dt} to UTC (assuming Sydney timezone)")
        return dt.replace(tzinfo=DEFAULT_TZ).astimezone(UTC)
    return dt.astimezone(UTC)


def ensure_aware(dt: datetime, timezone: ZoneInfo) -> datetime:
    """Ensure datetime is timezone-aware"""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone)
    return dt


def parse_cliniko_time(time_str: str) -> datetime:
    """Parse time string from Cliniko API to UTC datetime"""
    if not time_str:
        raise ValueError("Empty time string")
    
    # Handle 'Z' suffix (Zulu/UTC time)
    if time_str.endswith('Z'):
        dt = datetime.fromisoformat(time_str.replace('Z', '+00:00'))
    else:
        dt = datetime.fromisoformat(time_str)
    
    # Ensure timezone aware
    if dt.tzinfo is None:
        logger.warning(f"Cliniko returned naive datetime: {time_str}")
        dt = dt.replace(tzinfo=UTC)
    
    return dt.astimezone(UTC)


def local_to_utc(local_dt: datetime, timezone: ZoneInfo) -> datetime:
    """Convert local datetime to UTC"""
    if local_dt.tzinfo is None:
        local_dt = local_dt.replace(tzinfo=timezone)
    return local_dt.astimezone(UTC)


def utc_to_local(utc_dt: datetime, timezone: ZoneInfo = DEFAULT_TZ) -> datetime:
    """Convert UTC datetime to local timezone"""
    if utc_dt.tzinfo is None:
        utc_dt = utc_dt.replace(tzinfo=UTC)
    return utc_dt.astimezone(timezone)


def combine_date_time_local(
    date_obj: date, 
    hour: int, 
    minute: int, 
    timezone: ZoneInfo
) -> datetime:
    """Combine date and time in local timezone"""
    local_dt = datetime.combine(
        date_obj,
        time(hour=hour, minute=minute),
        tzinfo=timezone
    )
    return local_dt.astimezone(UTC)


def format_for_display(dt: datetime, timezone: ZoneInfo = DEFAULT_TZ) -> str:
    """Format datetime for user display in local timezone"""
    local_dt = utc_to_local(dt, timezone)
    return local_dt.strftime("%I:%M %p").lstrip('0')


def format_date_for_display(dt: datetime, timezone: ZoneInfo = DEFAULT_TZ) -> str:
    """Format date for user display"""
    local_dt = utc_to_local(dt, timezone)
    return local_dt.strftime("%A, %B %d, %Y")


def get_clinic_timezone(clinic) -> ZoneInfo:
    """Get timezone for clinic with robust fallback"""
    if clinic is None:
        return DEFAULT_TZ
    # Try to get timezone string from clinic object
    timezone_str = None
    if hasattr(clinic, 'timezone'):
        timezone_str = getattr(clinic, 'timezone', None)
    elif hasattr(clinic, '__getitem__'):
        try:
            timezone_str = clinic['timezone']
        except:
            pass
    # Validate and return
    if timezone_str and timezone_str.strip():
        try:
            return ZoneInfo(timezone_str)
        except:
            pass
    return DEFAULT_TZ


def convert_utc_to_local(utc_time_str: str, timezone: Union[str, ZoneInfo, None] = None) -> datetime:
    """Convert UTC time string to local timezone"""
    if timezone is None:
        timezone = DEFAULT_TZ
    # Handle both string and ZoneInfo
    if isinstance(timezone, str):
        local_tz = ZoneInfo(timezone)
    elif isinstance(timezone, ZoneInfo):
        local_tz = timezone
    else:
        raise ValueError(f"Invalid timezone type: {type(timezone)}")
    
    if utc_time_str.endswith('Z'):
        utc_time = datetime.fromisoformat(utc_time_str.replace('Z', '+00:00'))
    else:
        utc_time = datetime.fromisoformat(utc_time_str)
    
    if utc_time.tzinfo is None:
        utc_time = utc_time.replace(tzinfo=UTC)
    
    return utc_time.astimezone(local_tz)


def format_time_for_voice(dt: datetime) -> str:
    """Format datetime for voice response"""
    return dt.strftime("%I:%M %p").lstrip('0')