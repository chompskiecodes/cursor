# tests/test_find_next_available_simplified.py
"""Tests for simplified find-next-available endpoint"""

import pytest
from datetime import datetime, date, timedelta
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

@pytest.fixture
def mock_pool():
    """Mock database pool"""
    pool = AsyncMock()
    conn = AsyncMock()
    pool.acquire.return_value.__aenter__.return_value = conn
    return pool, conn

@pytest.fixture
def mock_clinic():
    """Mock clinic data"""
    from models import ClinicData
    return ClinicData(
        clinic_id="test-clinic-123",
        clinic_name="Test Clinic",
        cliniko_api_key="test-api-key",
        cliniko_shard="au1",
        contact_email="test@clinic.com",
        businesses=[{"business_id": "loc-001", "business_name": "Main Clinic", "is_primary": True}],
        timezone="Australia/Sydney"
    )

class TestFindNextAvailable:
    """Test simplified find-next-available endpoint"""
    
    @pytest.mark.asyncio
    async def test_next_available_found_today(self, mock_pool, mock_clinic):
        """Test finding next available slot today"""
        pool, conn = mock_pool
        
        # Mock current time
        tz = ZoneInfo("Australia/Sydney")
        today = datetime.now(tz).date()
        slot_time = datetime.combine(today, datetime.min.time()).replace(
            hour=14, minute=30, tzinfo=tz
        )
        
        # Mock query result
        mock_result = {
            "practitioner": {
                "id": "prac-123",
                "name": "Dr. Jane Smith"
            },
            "next_slot": {
                "date": today,
                "time": "14:30",
                "display_time": "2:30 PM",
                "service": "Consultation (60 min)",
                "duration": 60,
                "location_id": "loc-001",
                "location": "Main Clinic",
                "datetime": slot_time
            },
            "alternatives": [
                {
                    "date": today,
                    "time": "15:30",
                    "display_time": "3:30 PM",
                    "service": "Consultation (60 min)",
                    "location": "Main Clinic"
                },
                {
                    "date": today + timedelta(days=1),
                    "time": "09:00",
                    "display_time": "9:00 AM",
                    "service": "Consultation (60 min)",
                    "location": "Main Clinic"
                }
            ],
            "summary": {
                "days_with_availability": 5,
                "total_slots": 25,
                "first_available_date": today,
                "available_dates": [today, today + timedelta(days=1), today + timedelta(days=2)]
            },
            "services": ["Consultation (60 min)", "Consultation (30 min)"]
        }
        
        conn.fetchval.return_value = mock_result
        
        with patch('tools.availability_router_find_next_simplified.get_db', return_value=pool):
            with patch('tools.availability_router_find_next_simplified.get_clinic_by_dialed_number', return_value=mock_clinic):
                with patch('tools.availability_router_find_next_simplified.datetime') as mock_datetime:
                    mock_datetime.now.return_value = datetime.now(tz)
                    
                    from tools.availability_router_find_next_simplified import find_next_available, FindNextAvailableRequest
                    
                    response = await find_next_available(
                        FindNextAvailableRequest(
                            practitioner="Jane Smith",
                            sessionId="test-123",
                            dialedNumber="0412345678",
                            appointmentType="Consultation"
                        ),
                        authenticated=True
                    )
        
        assert response["success"] is True
        assert response["practitioner"] == "Dr. Jane Smith"
        assert response["displayTime"] == "2:30 PM"
        assert "today at 2:30 PM" in response["message"]
        assert "I also have openings" in response["message"]
        assert len(response["alternatives"]) == 2
    
    @pytest.mark.asyncio
    async def test_next_available_found_next_week(self, mock_pool, mock_clinic):
        """Test finding next available slot next week"""
        pool, conn = mock_pool
        
        # Mock current time
        tz = ZoneInfo("Australia/Sydney")
        today = datetime.now(tz).date()
        next_week = today + timedelta(days=8)
        slot_time = datetime.combine(next_week, datetime.min.time()).replace(
            hour=10, tzinfo=tz
        )
        
        # Mock query result
        mock_result = {
            "practitioner": {
                "id": "prac-123",
                "name": "Dr. Jane Smith"
            },
            "next_slot": {
                "date": next_week,
                "time": "10:00",
                "display_time": "10:00 AM",
                "service": "Consultation",
                "duration": 60,
                "location_id": "loc-001",
                "location": "Main Clinic",
                "datetime": slot_time
            },
            "alternatives": [],
            "summary": {
                "days_with_availability": 1,
                "total_slots": 5,
                "first_available_date": next_week
            },
            "services": None
        }
        
        conn.fetchval.return_value = mock_result
        
        with patch('tools.availability_router_find_next_simplified.get_db', return_value=pool):
            with patch('tools.availability_router_find_next_simplified.get_clinic_by_dialed_number', return_value=mock_clinic):
                with patch('tools.availability_router_find_next_simplified.datetime') as mock_datetime:
                    mock_datetime.now.return_value = datetime.now(tz)
                    
                    from tools.availability_router_find_next_simplified import find_next_available, FindNextAvailableRequest
                    
                    response = await find_next_available(
                        FindNextAvailableRequest(
                            practitioner="Jane Smith",
                            sessionId="test-456",
                            dialedNumber="0412345678"
                        ),
                        authenticated=True
                    )
        
        assert response["success"] is True
        assert response["date"] == str(next_week)
        assert response["time"] == "10:00"
        assert next_week.strftime('%A, %B %d') in response["message"]
        assert response["availability_summary"]["next_available"] == next_week.strftime('%A, %B %d')
    
    @pytest.mark.asyncio
    async def test_next_available_practitioner_not_found(self, mock_pool, mock_clinic):
        """Test when practitioner not found"""
        pool, conn = mock_pool
        
        # Mock query result with no practitioner
        mock_result = {
            "practitioner": None,
            "next_slot": None,
            "alternatives": None,
            "summary": None,
            "services": None
        }
        
        conn.fetchval.return_value = mock_result
        
        with patch('tools.availability_router_find_next_simplified.get_db', return_value=pool):
            with patch('tools.availability_router_find_next_simplified.get_clinic_by_dialed_number', return_value=mock_clinic):
                from tools.availability_router_find_next_simplified import find_next_available, FindNextAvailableRequest
                
                response = await find_next_available(
                    FindNextAvailableRequest(
                        practitioner="Dr. Nobody",
                        sessionId="test-789",
                        dialedNumber="0412345678"
                    ),
                    authenticated=True
                )
        
        assert response["success"] is False
        assert response["error"] == "practitioner_not_found"
        assert "Dr. Nobody" in response["message"]
    
    @pytest.mark.asyncio
    async def test_next_available_no_slots(self, mock_pool, mock_clinic):
        """Test when no slots available in time range"""
        pool, conn = mock_pool
        
        # Mock query result with practitioner but no slots
        mock_result = {
            "practitioner": {
                "id": "prac-123",
                "name": "Dr. Jane Smith"
            },
            "next_slot": None,
            "alternatives": None,
            "summary": {
                "days_with_availability": 0,
                "total_slots": 0
            },
            "services": ["Consultation"]
        }
        
        conn.fetchval.return_value = mock_result
        
        with patch('tools.availability_router_find_next_simplified.get_db', return_value=pool):
            with patch('tools.availability_router_find_next_simplified.get_clinic_by_dialed_number', return_value=mock_clinic):
                from tools.availability_router_find_next_simplified import find_next_available, FindNextAvailableRequest
                
                response = await find_next_available(
                    FindNextAvailableRequest(
                        practitioner="Jane Smith",
                        sessionId="test-no-slots",
                        dialedNumber="0412345678",
                        maxDaysAhead=30
                    ),
                    authenticated=True
                )
        
        assert response["success"] is False
        assert response["error"] == "no_availability"
        assert "doesn't have any available appointments in the next 30 days" in response["message"]
    
    @pytest.mark.asyncio
    async def test_next_available_service_not_found(self, mock_pool, mock_clinic):
        """Test when specified service not found"""
        pool, conn = mock_pool
        
        # Mock query result with practitioner but wrong service
        mock_result = {
            "practitioner": {
                "id": "prac-123",
                "name": "Dr. Jane Smith"
            },
            "next_slot": None,
            "alternatives": None,
            "summary": None,
            "services": ["Consultation", "Follow-up"]
        }
        
        conn.fetchval.return_value = mock_result
        
        with patch('tools.availability_router_find_next_simplified.get_db', return_value=pool):
            with patch('tools.availability_router_find_next_simplified.get_clinic_by_dialed_number', return_value=mock_clinic):
                from tools.availability_router_find_next_simplified import find_next_available, FindNextAvailableRequest
                
                response = await find_next_available(
                    FindNextAvailableRequest(
                        practitioner="Jane Smith",
                        sessionId="test-wrong-service",
                        dialedNumber="0412345678",
                        appointmentType="Massage"
                    ),
                    authenticated=True
                )
        
        assert response["success"] is False
        assert response["error"] == "service_not_found"
        assert "doesn't offer Massage" in response["message"]
        assert "Consultation" in response["suggestions"]
        assert "Follow-up" in response["suggestions"]
    
    @pytest.mark.asyncio
    async def test_next_available_tomorrow(self, mock_pool, mock_clinic):
        """Test finding slot tomorrow with natural language"""
        pool, conn = mock_pool
        
        # Mock current time
        tz = ZoneInfo("Australia/Sydney")
        today = datetime.now(tz).date()
        tomorrow = today + timedelta(days=1)
        slot_time = datetime.combine(tomorrow, datetime.min.time()).replace(
            hour=9, tzinfo=tz
        )
        
        # Mock query result
        mock_result = {
            "practitioner": {
                "id": "prac-123",
                "name": "Dr. Jane Smith"
            },
            "next_slot": {
                "date": tomorrow,
                "time": "09:00",
                "display_time": "9:00 AM",
                "service": "Consultation",
                "duration": 60,
                "location_id": "loc-001",
                "location": "Main Clinic",
                "datetime": slot_time
            },
            "alternatives": [],
            "summary": {
                "days_with_availability": 5,
                "total_slots": 20
            },
            "services": None
        }
        
        conn.fetchval.return_value = mock_result
        
        with patch('tools.availability_router_find_next_simplified.get_db', return_value=pool):
            with patch('tools.availability_router_find_next_simplified.get_clinic_by_dialed_number', return_value=mock_clinic):
                with patch('tools.availability_router_find_next_simplified.datetime') as mock_datetime:
                    mock_datetime.now.return_value = datetime.now(tz)
                    
                    from tools.availability_router_find_next_simplified import find_next_available, FindNextAvailableRequest
                    
                    response = await find_next_available(
                        FindNextAvailableRequest(
                            practitioner="Jane Smith",
                            sessionId="test-tomorrow",
                            dialedNumber="0412345678"
                        ),
                        authenticated=True
                    )
        
        assert response["success"] is True
        assert "tomorrow at 9:00 AM" in response["message"]
        assert response["availability_summary"]["next_available"] == "tomorrow"