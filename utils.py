# utils.py
import re
from datetime import datetime, date, timedelta, timezone
from typing import Tuple, Optional, List
from difflib import SequenceMatcher
from models import TranscriptMessage

# === Utility Functions ===
def normalize_phone(phone: str) -> str:
    """Normalize phone number to international format"""
    if not phone:
        return ''
    cleaned = re.sub(r'\D', '', phone)
    if cleaned.startswith('0'):
        cleaned = '61' + cleaned[1:]  # Australian format
    return cleaned

def mask_phone(phone: str) -> str:
    """Mask phone number for logging"""
    if len(phone) < 4:
        return "***"
    return f"{phone[:3]}***{phone[-2:]}"

def normalize_for_matching(text: str) -> str:
    """Normalize text for fuzzy matching - handle all Cliniko data quirks"""
    if not text:
        return ""
    return (text
        .strip()  # Remove leading/trailing spaces
        .lower()  # Case insensitive
        .replace("  ", " ")  # Multiple spaces to single
        .replace("\t", " ")  # Tabs to spaces
        .replace("\n", " ")  # Newlines to spaces
        .replace("\xa0", " ")  # Non-breaking spaces to regular spaces
    )

def fuzzy_match(str1: str, str2: str) -> float:
    """Calculate similarity between two strings"""
    return SequenceMatcher(None, str1.lower(), str2.lower()).ratio()

def extract_from_transcript(transcript: List[TranscriptMessage], pattern: str) -> Optional[str]:
    """Extract information from transcript using regex pattern"""
    full_text = " ".join([msg.message for msg in transcript if msg.role == "user"])
    match = re.search(pattern, full_text, re.IGNORECASE)
    return match.group(1) if match else None

def parse_date_request(date_str: str, clinic_timezone=None) -> date:
    """Parse various date formats and relative dates"""
    if clinic_timezone:
        today = datetime.now(clinic_timezone).date()
    else:
        # Fallback to UTC if no timezone provided
        today = datetime.now(timezone.utc).date()
    date_str = date_str.lower().strip()
    
    if "today" in date_str:
        return today
    elif "tomorrow" in date_str:
        return today + timedelta(days=1)
    elif "next week" in date_str:
        return today + timedelta(days=7)
    
    # Day of week parsing
    days = {
        "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
        "friday": 4, "saturday": 5, "sunday": 6
    }
    
    for day_name, day_num in days.items():
        if day_name in date_str:
            days_ahead = (day_num - today.weekday() + 7) % 7
            if days_ahead == 0 and "next" in date_str:
                days_ahead = 7
            return today + timedelta(days=days_ahead)
    
    # Try parsing as date
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").date()
    except:
        return today + timedelta(days=1)  # Default to tomorrow

def parse_time_request(time_str: str) -> Tuple[int, int]:
    """Parse time from various formats"""
    if not time_str:
        return 10, 0  # Default to 10:00 AM
        
    time_str = time_str.lower().strip()
    
    # Handle patterns like "10:30am", "2pm", "14:00"
    patterns = [
        (r'(\d{1,2}):(\d{2})\s*(am|pm)?', True),
        (r'(\d{1,2})\s*(am|pm)', False),
        (r'(\d{1,2})(\d{2})\s*(hours?)?', True)
    ]
    
    for pattern, has_minutes in patterns:
        match = re.search(pattern, time_str)
        if match:
            hour = int(match.group(1))
            minute = 0
            
            if has_minutes and len(match.groups()) > 1 and match.group(2):
                minute = int(match.group(2))
            
            # Handle AM/PM
            if len(match.groups()) >= 3 and match.group(3):
                period = match.group(3)
                if period == 'pm' and hour < 12:
                    hour += 12
                elif period == 'am' and hour == 12:
                    hour = 0
            
            return hour, minute
    
    # Default to 10:00 AM
    return 10, 0