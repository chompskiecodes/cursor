# tools/shared.py
"""Shared utilities for all tools"""

from datetime import datetime, timezone, date
from zoneinfo import ZoneInfo
from functools import lru_cache
import logging
from typing import Dict, Any, Optional, List

import asyncpg


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


async def get_scheduled_working_days(conn: asyncpg.Connection, practitioner_id: str, business_id: str, date_range: List[date]) -> List[date]:
    """
    Returns a list of dates in date_range where the practitioner is scheduled to work at the business.
    Only includes dates where the weekday matches a schedule row and the date is within the effective range.
    The output matches Python's weekday() convention: 0=Monday, 6=Sunday.
    """
    import logging
    logging.info(f"[DEBUG] get_scheduled_working_days called with practitioner_id={practitioner_id}, business_id={business_id}, date_range={date_range}")
    rows = await conn.fetch(
        """
        SELECT day_of_week, effective_from, effective_until
        FROM practitioner_schedules
        WHERE practitioner_id = $1 AND business_id = $2
        """,
        practitioner_id, business_id
    )
    logging.info(f"[DEBUG] get_scheduled_working_days fetched rows: {rows}")
    allowed_dates = []
    for d in date_range:
        py_weekday = d.weekday()  # 0=Monday, 6=Sunday
        for row in rows:
            # Map DB's day_of_week (0=Sunday, 6=Saturday) to Python's weekday convention
            db_weekday = row['day_of_week']
            db_weekday_as_python = (db_weekday - 1) % 7  # 0=Monday, 6=Sunday
            eff_from = row['effective_from']
            eff_until = row['effective_until']
            if (eff_from is None or eff_from <= d) and (eff_until is None or eff_until >= d):
                if py_weekday == db_weekday_as_python:
                    allowed_dates.append(d)
                    break
    logging.info(f"[DEBUG] get_scheduled_working_days allowed_dates: {allowed_dates}")
    return allowed_dates
