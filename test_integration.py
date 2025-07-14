# tests/test_integration.py
"""Integration tests for the complete voice booking system"""

import pytest
from datetime import datetime, date, time, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo
import json

@pytest.fixture
def mock_db_state():
    """Mock database state for integration tests"""
    return {
        "clinics": {
            "0412345678": {
                "clinic_id": "test-clinic-123",
                "clinic_name": "Test Medical Centre",
                "businesses": [
                    {"business_id": "loc-001", "business_name": "City Clinic", "is_primary": True},
                    {"business_id": "loc-002", "business_name": "Suburb Clinic", "is_primary": False}
                ]
            }
        },
        "practitioners": [
            {
                "practitioner_id": "prac-001",
                "name": "Dr. Jane Smith",
                "locations": ["loc-001", "loc-002"],
                "services": ["Consultation (60 min)", "Consultation (30 min)"]
            },
            {
                "practitioner_id": "prac-002", 
                "name": "Dr. John Doe",
                "locations": ["loc-001"],
                "services": ["Acupuncture Initial", "Acupuncture Follow Up"]
            }
        ],
        "availability": {
            "prac-001": {
                "2024-03-20": [
                    {"time": "09:00", "location": "loc-001"},
                    {"time": "10:00", "location": "loc-001"},
                    {"time": "14:00", "location": "loc-002"}
                ]
            }
        },
        "patients": {}
    }

class TestCompleteBookingFlow:
    """Test complete booking flow from start to finish"""
    
    @pytest.mark.asyncio
    async def test_new_patient_booking_flow(self):
        """Test complete flow for new patient booking"""
        
        # Step 1: Sync cache at call start
        with patch('tools.sync_router.get_db') as mock_db:
            with patch('tools.sync_router.get_cache') as mock_cache:
                with patch('tools.sync_router.get_clinic_by_dialed_number') as mock_get_clinic:
                    with patch('tools.sync_router.IncrementalCacheSync') as mock_sync_class:
                        # Setup mocks
                        mock_get_clinic.return_value = MagicMock(
                            clinic_id="test-clinic-123",
                            clinic_name="Test Medical Centre",
                            cliniko_api_key="test-key",
                            cliniko_shard="au1"
                        )
                        
                        mock_sync = AsyncMock()
                        mock_sync.sync_appointments_incremental.return_value = {
                            'updated': 50, 'deleted': 0, 'errors': 0
                        }
                        mock_sync_class.return_value = mock_sync
                        
                        from tools.sync_router import sync_cache
                        sync_response = await sync_cache({
                            "sessionId": "call-123",
                            "dialedNumber": "0412345678",
                            "forceFullSync": False
                        }, authenticated=True)
                        
                        assert sync_response["success"] is True
                        assert sync_response["syncType"] == "incremental"
        
        # Step 2: Resolve location
        with patch('tools.location_router_simplified.get_db') as mock_db:
            with patch('tools.location_router_simplified.get_cache') as mock_cache:
                with patch('tools.location_router_simplified.get_clinic_by_dialed_number') as mock_get_clinic:
                    # Setup location resolution
                    conn = AsyncMock()
                    conn.fetchval.return_value = {
                        "matches": [{
                            "business_id": "loc-001",
                            "business_name": "City Clinic",
                            "match_score": 0.95
                        }],
                        "summary": {"best_score": 0.95}
                    }
                    mock_db.return_value.acquire.return_value.__aenter__.return_value = conn
                    mock_get_clinic.return_value = MagicMock(clinic_id="test-clinic-123")
                    
                    from tools.location_router_simplified import resolve_location
                    from models import LocationResolverRequest
                    
                    location_response = await resolve_location(
                        LocationResolverRequest(
                            locationQuery="city clinic",
                            sessionId="call-123",
                            dialedNumber="0412345678"
                        ),
                        authenticated=True
                    )
                    
                    assert location_response["action_completed"] is True
                    assert location_response["business_id"] == "loc-001"
        
        # Step 3: Get practitioner services
        with patch('tools.practitioner_router_simplified.get_db') as mock_db:
            with patch('tools.practitioner_router_simplified.get_clinic_by_dialed_number') as mock_get_clinic:
                conn = AsyncMock()
                conn.fetchval.return_value = {
                    "practitioner": {"id": "prac-001", "name": "Dr. Jane Smith"},
                    "services": [
                        {"name": "Consultation (60 min)", "duration": 60},
                        {"name": "Consultation (30 min)", "duration": 30}
                    ],
                    "summary": {"total_services": 2}
                }
                mock_db.return_value.acquire.return_value.__aenter__.return_value = conn
                mock_get_clinic.return_value = MagicMock(clinic_id="test-clinic-123")
                
                from tools.practitioner_router_simplified import get_practitioner_services, GetPractitionerServicesRequest
                
                services_response = await get_practitioner_services(
                    GetPractitionerServicesRequest(
                        practitioner="Jane Smith",
                        sessionId="call-123",
                        dialedNumber="0412345678"
                    ),
                    authenticated=True
                )
                
                assert services_response["success"] is True
                assert len(services_response["services"]) == 2
        
        # Step 4: Check availability
        with patch('tools.availability_router_simplified.get_db') as mock_db:
            with patch('tools.availability_router_simplified.get_clinic_by_dialed_number') as mock_get_clinic:
                with patch('utils.parse_date_request', return_value=date(2024, 3, 20)):
                    conn = AsyncMock()
                    conn.fetchval.return_value = {
                        "practitioner": {"id": "prac-001", "name": "Dr. Jane Smith"},
                        "slots": [
                            {"time": "09:00", "display_time": "9:00 AM", "location": "City Clinic"},
                            {"time": "10:00", "display_time": "10:00 AM", "location": "City Clinic"}
                        ],
                        "summary": {"total_slots": 2, "availability_level": "limited availability"}
                    }
                    mock_db.return_value.acquire.return_value.__aenter__.return_value = conn
                    mock_get_clinic.return_value = MagicMock(clinic_id="test-clinic-123", timezone="Australia/Sydney")
                    
                    from tools.availability_router_simplified import check_availability
                    from models import AvailabilityRequest
                    
                    availability_response = await check_availability(
                        AvailabilityRequest(
                            practitioner="Jane Smith",
                            date="tomorrow",
                            sessionId="call-123",
                            dialedNumber="0412345678",
                            locationId="loc-001"
                        ),
                        authenticated=True
                    )
                    
                    assert availability_response["success"] is True
                    assert len(availability_response["slots"]) == 2
        
        # Step 5: Book appointment
        with patch('tools.booking_router_simplified.get_db') as mock_db:
            with patch('tools.booking_router_simplified.get_cache') as mock_cache:
                with patch('tools.booking_router_simplified.get_clinic_by_dialed_number') as mock_get_clinic:
                    with patch('tools.booking_router_simplified.ClinikoAPI') as mock_cliniko_class:
                        with patch('utils.parse_date_request', return_value=date(2024, 3, 20)):
                            with patch('utils.parse_time_request', return_value=time(9, 0)):
                                # Setup mocks
                                conn = AsyncMock()
                                conn.fetchrow.side_effect = [
                                    # Patient creation
                                    {"patient_id": "temp-123", "first_name": "John", "last_name": "Smith"},
                                    # Practitioner match
                                    {"practitioner_id": "prac-001", "full_name": "Dr. Jane Smith", "works_at_location": True},
                                    # Service match
                                    {"appointment_type_id": "appt-001", "service_name": "Consultation (60 min)", "duration_minutes": 60},
                                    # Availability check
                                    {"is_available": True},
                                    # Business name
                                    {"business_name": "City Clinic"}
                                ]
                                
                                transaction = AsyncMock()
                                conn.transaction.return_value.__aenter__.return_value = transaction
                                mock_db.return_value.acquire.return_value.__aenter__.return_value = conn
                                
                                mock_cliniko = AsyncMock()
                                mock_cliniko.create_patient.return_value = {"id": "patient-12345"}
                                mock_cliniko.create_individual_appointment.return_value = {"id": "appt-12345"}
                                mock_cliniko_class.return_value = mock_cliniko
                                
                                mock_get_clinic.return_value = MagicMock(
                                    clinic_id="test-clinic-123",
                                    timezone="Australia/Sydney",
                                    cliniko_api_key="test-key",
                                    cliniko_shard="au1"
                                )
                                
                                from tools.booking_router_simplified import handle_appointment
                                from models import BookingRequest
                                
                                booking_response = await handle_appointment(
                                    BookingRequest(
                                        sessionId="call-123",
                                        dialedNumber="0412345678",
                                        callerPhone="0411111111",
                                        patientName="John Smith",
                                        patientPhone="0411111111",
                                        practitioner="Jane Smith",
                                        appointmentType="Consultation",
                                        appointmentDate="tomorrow",
                                        appointmentTime="9am",
                                        locationId="loc-001"
                                    ),
                                    authenticated=True
                                )
                                
                                assert booking_response["success"] is True
                                assert "successfully booked" in booking_response["message"]
                                assert booking_response["appointmentDetails"]["appointmentId"] == "appt-12345"
    
    @pytest.mark.asyncio
    async def test_find_next_available_flow(self):
        """Test finding next available appointment flow"""
        
        # Step 1: Sync cache (same as above)
        # ... (sync step omitted for brevity)
        
        # Step 2: Find next available
        with patch('tools.availability_router_find_next_simplified.get_db') as mock_db:
            with patch('tools.availability_router_find_next_simplified.get_clinic_by_dialed_number') as mock_get_clinic:
                conn = AsyncMock()
                conn.fetchval.return_value = {
                    "practitioner": {"id": "prac-001", "name": "Dr. Jane Smith"},
                    "next_slot": {
                        "date": date(2024, 3, 20),
                        "time": "14:00",
                        "display_time": "2:00 PM",
                        "service": "Consultation",
                        "location_id": "loc-002",
                        "location": "Suburb Clinic",
                        "datetime": datetime(2024, 3, 20, 14, 0, tzinfo=ZoneInfo("Australia/Sydney"))
                    },
                    "alternatives": [],
                    "summary": {"days_with_availability": 5, "total_slots": 15}
                }
                mock_db.return_value.acquire.return_value.__aenter__.return_value = conn
                mock_get_clinic.return_value = MagicMock(
                    clinic_id="test-clinic-123",
                    timezone="Australia/Sydney"
                )
                
                from tools.availability_router_find_next_simplified import find_next_available, FindNextAvailableRequest
                
                next_response = await find_next_available(
                    FindNextAvailableRequest(
                        practitioner="Jane Smith",
                        sessionId="call-456",
                        dialedNumber="0412345678"
                    ),
                    authenticated=True
                )
                
                assert next_response["success"] is True
                assert next_response["locationId"] == "loc-002"
                assert next_response["location"] == "Suburb Clinic"
                assert "Suburb Clinic" in next_response["message"]
    
    @pytest.mark.asyncio
    async def test_error_recovery_flow(self):
        """Test error recovery and retry flow"""
        
        # Step 1: Practitioner not found
        with patch('tools.availability_router_simplified.get_db') as mock_db:
            with patch('tools.availability_router_simplified.get_clinic_by_dialed_number') as mock_get_clinic:
                conn = AsyncMock()
                conn.fetchval.return_value = {
                    "practitioner": None,
                    "all_practitioners": [
                        {"name": "Dr. Jane Smith", "id": "prac-001"},
                        {"name": "Dr. John Doe", "id": "prac-002"}
                    ]
                }
                mock_db.return_value.acquire.return_value.__aenter__.return_value = conn
                mock_get_clinic.return_value = MagicMock(clinic_id="test-clinic-123")
                
                from tools.availability_router_simplified import check_availability
                from models import AvailabilityRequest
                
                error_response = await check_availability(
                    AvailabilityRequest(
                        practitioner="Dr. Jones",  # Wrong name
                        date="tomorrow",
                        sessionId="call-789",
                        dialedNumber="0412345678"
                    ),
                    authenticated=True
                )
                
                assert error_response["success"] is False
                assert error_response["error"] == "practitioner_not_found"
                assert len(error_response["suggestions"]) > 0
                assert "Dr. Jane Smith" in error_response["suggestions"]
        
        # Step 2: Retry with correct practitioner
        with patch('tools.availability_router_simplified.get_db') as mock_db:
            with patch('tools.availability_router_simplified.get_clinic_by_dialed_number') as mock_get_clinic:
                with patch('utils.parse_date_request', return_value=date(2024, 3, 20)):
                    conn = AsyncMock()
                    conn.fetchval.return_value = {
                        "practitioner": {"id": "prac-001", "name": "Dr. Jane Smith"},
                        "slots": [{"time": "09:00", "display_time": "9:00 AM"}],
                        "summary": {"total_slots": 1}
                    }
                    mock_db.return_value.acquire.return_value.__aenter__.return_value = conn
                    mock_get_clinic.return_value = MagicMock(clinic_id="test-clinic-123")
                    
                    retry_response = await check_availability(
                        AvailabilityRequest(
                            practitioner="Jane Smith",  # Corrected name
                            date="tomorrow",
                            sessionId="call-789",
                            dialedNumber="0412345678"
                        ),
                        authenticated=True
                    )
                    
                    assert retry_response["success"] is True
                    assert len(retry_response["slots"]) > 0