# tests/test_appointment_handler_simplified.py
"""Tests for simplified appointment handler with single transaction"""

import pytest
from datetime import datetime, date, time, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo
import asyncpg

@pytest.fixture
def mock_pool():
    """Mock database pool"""
    pool = AsyncMock()
    conn = AsyncMock()
    
    # Mock transaction context
    transaction = AsyncMock()
    conn.transaction.return_value.__aenter__.return_value = transaction
    pool.acquire.return_value.__aenter__.return_value = conn
    
    return pool, conn

@pytest.fixture
def mock_cache():
    """Mock cache manager"""
    return AsyncMock()

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

@pytest.fixture
def mock_cliniko():
    """Mock Cliniko API"""
    api = AsyncMock()
    api.create_patient.return_value = {
        "id": "12345",
        "first_name": "John",
        "last_name": "Smith"
    }
    api.create_individual_appointment.return_value = {
        "id": "appt-12345",
        "appointment_start": "2024-03-20T14:00:00+11:00"
    }
    return api

class TestAppointmentHandler:
    """Test simplified appointment handler"""
    
    @pytest.mark.asyncio
    async def test_successful_booking_new_patient(self, mock_pool, mock_cache, mock_clinic, mock_cliniko):
        """Test successful booking with new patient creation"""
        pool, conn = mock_pool
        
        # Mock database responses in order
        conn.fetchrow.side_effect = [
            # Patient lookup/create result - new patient
            {
                "patient_id": "temp_123e4567-e89b-12d3-a456-426614174000",
                "first_name": "John",
                "last_name": "Smith",
                "email": None,
                "phone_number": "0411111111"
            },
            # Practitioner match result
            {
                "practitioner_id": "prac-123",
                "full_name": "Dr. Jane Smith",
                "business_ids": ["loc-001"],
                "works_at_location": True
            },
            # Service match result
            {
                "appointment_type_id": "appt-type-123",
                "service_name": "Consultation (60 min)",
                "duration_minutes": 60
            },
            # Availability check result
            {"is_available": True},
            # Business name lookup
            {"business_name": "Main Clinic"}
        ]
        
        # No execute results needed (all are inserts/updates)
        conn.execute.return_value = None
        
        with patch('tools.booking_router_simplified.get_db', return_value=pool):
            with patch('tools.booking_router_simplified.get_cache', return_value=mock_cache):
                with patch('tools.booking_router_simplified.get_clinic_by_dialed_number', return_value=mock_clinic):
                    with patch('tools.booking_router_simplified.ClinikoAPI', return_value=mock_cliniko):
                        with patch('utils.parse_date_request', return_value=date(2024, 3, 20)):
                            with patch('utils.parse_time_request', return_value=time(14, 0)):
                                from tools.booking_router_simplified import handle_appointment
                                from models import BookingRequest
                                
                                response = await handle_appointment(
                                    BookingRequest(
                                        action="book",
                                        sessionId="test-123",
                                        dialedNumber="0412345678",
                                        callerPhone="0411111111",
                                        patientName="John Smith",
                                        patientPhone="0411111111",
                                        practitioner="Jane Smith",
                                        appointmentType="Consultation",
                                        appointmentDate="tomorrow",
                                        appointmentTime="2pm",
                                        locationId="loc-001"
                                    ),
                                    authenticated=True
                                )
        
        assert response["success"] is True
        assert "successfully booked" in response["message"]
        assert response["appointmentDetails"]["appointmentId"] == "appt-12345"
        assert response["appointmentDetails"]["practitioner"] == "Dr. Jane Smith"
        assert response["appointmentDetails"]["service"] == "Consultation (60 min)"
        assert response["appointmentDetails"]["time"] == "2:00 PM"
        
        # Verify patient was created in Cliniko
        mock_cliniko.create_patient.assert_called_once()
        
        # Verify appointment was created
        mock_cliniko.create_individual_appointment.assert_called_once()
        
        # Verify cache invalidation
        assert any("UPDATE availability_cache" in str(call) for call in conn.execute.call_args_list)
    
    @pytest.mark.asyncio
    async def test_successful_booking_existing_patient(self, mock_pool, mock_cache, mock_clinic, mock_cliniko):
        """Test successful booking with existing patient"""
        pool, conn = mock_pool
        
        # Mock database responses - existing patient
        conn.fetchrow.side_effect = [
            # Patient lookup - found existing
            {
                "patient_id": "patient-789",
                "first_name": "Jane",
                "last_name": "Doe",
                "email": "jane@example.com",
                "phone_number": "0411111111"
            },
            # Practitioner match
            {
                "practitioner_id": "prac-123",
                "full_name": "Dr. Jane Smith",
                "business_ids": ["loc-001"],
                "works_at_location": True
            },
            # Service match
            {
                "appointment_type_id": "appt-type-123",
                "service_name": "Follow-up (30 min)",
                "duration_minutes": 30
            },
            # Availability check
            {"is_available": True},
            # Business name
            {"business_name": "Main Clinic"}
        ]
        
        conn.execute.return_value = None
        
        with patch('tools.booking_router_simplified.get_db', return_value=pool):
            with patch('tools.booking_router_simplified.get_cache', return_value=mock_cache):
                with patch('tools.booking_router_simplified.get_clinic_by_dialed_number', return_value=mock_clinic):
                    with patch('tools.booking_router_simplified.ClinikoAPI', return_value=mock_cliniko):
                        with patch('utils.parse_date_request', return_value=date(2024, 3, 20)):
                            with patch('utils.parse_time_request', return_value=time(10, 30)):
                                from tools.booking_router_simplified import handle_appointment
                                from models import BookingRequest
                                
                                response = await handle_appointment(
                                    BookingRequest(
                                        sessionId="test-456",
                                        dialedNumber="0412345678",
                                        callerPhone="0411111111",
                                        patientPhone="0411111111",
                                        practitioner="Jane Smith",
                                        appointmentType="Follow-up",
                                        appointmentDate="tomorrow",
                                        appointmentTime="10:30am",
                                        locationId="loc-001"
                                    ),
                                    authenticated=True
                                )
        
        assert response["success"] is True
        assert response["appointmentDetails"]["patient"] == "Jane Doe"
        
        # Verify patient was NOT created (already exists)
        mock_cliniko.create_patient.assert_not_called()
        
        # Verify appointment was created
        mock_cliniko.create_individual_appointment.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_booking_practitioner_not_found(self, mock_pool, mock_cache, mock_clinic):
        """Test booking when practitioner not found"""
        pool, conn = mock_pool
        
        # Mock practitioner not found
        conn.fetchrow.side_effect = [
            # Patient found
            {"patient_id": "patient-123", "first_name": "John", "last_name": "Doe"},
            # Practitioner not found
            None
        ]
        
        with patch('tools.booking_router_simplified.get_db', return_value=pool):
            with patch('tools.booking_router_simplified.get_cache', return_value=mock_cache):
                with patch('tools.booking_router_simplified.get_clinic_by_dialed_number', return_value=mock_clinic):
                    with patch('utils.parse_date_request', return_value=date(2024, 3, 20)):
                        with patch('utils.parse_time_request', return_value=time(14, 0)):
                            from tools.booking_router_simplified import handle_appointment
                            from models import BookingRequest
                            
                            response = await handle_appointment(
                                BookingRequest(
                                    sessionId="test-789",
                                    dialedNumber="0412345678",
                                    callerPhone="0411111111",
                                    practitioner="Dr. Nobody",
                                    appointmentType="Consultation",
                                    appointmentDate="tomorrow",
                                    appointmentTime="2pm",
                                    locationId="loc-001"
                                ),
                                authenticated=True
                            )
        
        assert response["success"] is False
        assert response["error"] == "practitioner_not_found"
        assert "Dr. Nobody" in response["message"]
    
    @pytest.mark.asyncio
    async def test_booking_practitioner_wrong_location(self, mock_pool, mock_cache, mock_clinic):
        """Test booking when practitioner doesn't work at location"""
        pool, conn = mock_pool
        
        # Mock practitioner at different location
        conn.fetchrow.side_effect = [
            # Patient found
            {"patient_id": "patient-123", "first_name": "John", "last_name": "Doe"},
            # Practitioner found but wrong location
            {
                "practitioner_id": "prac-123",
                "full_name": "Dr. Jane Smith",
                "business_ids": ["loc-002"],  # Different location
                "works_at_location": False
            }
        ]
        
        with patch('tools.booking_router_simplified.get_db', return_value=pool):
            with patch('tools.booking_router_simplified.get_cache', return_value=mock_cache):
                with patch('tools.booking_router_simplified.get_clinic_by_dialed_number', return_value=mock_clinic):
                    from tools.booking_router_simplified import handle_appointment
                    from models import BookingRequest
                    
                    response = await handle_appointment(
                        BookingRequest(
                            sessionId="test-wrong-loc",
                            dialedNumber="0412345678",
                            callerPhone="0411111111",
                            practitioner="Jane Smith",
                            appointmentType="Consultation",
                            appointmentDate="tomorrow",
                            appointmentTime="2pm",
                            locationId="loc-001"
                        ),
                        authenticated=True
                    )
        
        assert response["success"] is False
        assert response["error"] == "practitioner_location_mismatch"
        assert "doesn't work at that location" in response["message"]
    
    @pytest.mark.asyncio
    async def test_booking_service_not_found(self, mock_pool, mock_cache, mock_clinic):
        """Test booking when service not found"""
        pool, conn = mock_pool
        
        # Mock service not found
        conn.fetchrow.side_effect = [
            # Patient found
            {"patient_id": "patient-123", "first_name": "John", "last_name": "Doe"},
            # Practitioner found
            {
                "practitioner_id": "prac-123",
                "full_name": "Dr. Jane Smith",
                "business_ids": ["loc-001"],
                "works_at_location": True
            },
            # Service not found
            None
        ]
        
        with patch('tools.booking_router_simplified.get_db', return_value=pool):
            with patch('tools.booking_router_simplified.get_cache', return_value=mock_cache):
                with patch('tools.booking_router_simplified.get_clinic_by_dialed_number', return_value=mock_clinic):
                    from tools.booking_router_simplified import handle_appointment
                    from models import BookingRequest
                    
                    response = await handle_appointment(
                        BookingRequest(
                            sessionId="test-no-service",
                            dialedNumber="0412345678",
                            callerPhone="0411111111",
                            practitioner="Jane Smith",
                            appointmentType="Massage",
                            appointmentDate="tomorrow",
                            appointmentTime="2pm",
                            locationId="loc-001"
                        ),
                        authenticated=True
                    )
        
        assert response["success"] is False
        assert response["error"] == "service_not_found"
        assert "doesn't offer Massage" in response["message"]
    
    @pytest.mark.asyncio
    async def test_booking_time_not_available(self, mock_pool, mock_cache, mock_clinic):
        """Test booking when time slot not available"""
        pool, conn = mock_pool
        
        # Mock time not available
        conn.fetchrow.side_effect = [
            # Patient found
            {"patient_id": "patient-123", "first_name": "John", "last_name": "Doe"},
            # Practitioner found
            {
                "practitioner_id": "prac-123",
                "full_name": "Dr. Jane Smith",
                "business_ids": ["loc-001"],
                "works_at_location": True
            },
            # Service found
            {
                "appointment_type_id": "appt-type-123",
                "service_name": "Consultation",
                "duration_minutes": 60
            },
            # Availability check - NOT available
            {"is_available": False}
        ]
        
        with patch('tools.booking_router_simplified.get_db', return_value=pool):
            with patch('tools.booking_router_simplified.get_cache', return_value=mock_cache):
                with patch('tools.booking_router_simplified.get_clinic_by_dialed_number', return_value=mock_clinic):
                    with patch('utils.parse_date_request', return_value=date(2024, 3, 20)):
                        with patch('utils.parse_time_request', return_value=time(14, 0)):
                            from tools.booking_router_simplified import handle_appointment
                            from models import BookingRequest
                            
                            response = await handle_appointment(
                                BookingRequest(
                                    sessionId="test-not-avail",
                                    dialedNumber="0412345678",
                                    callerPhone="0411111111",
                                    practitioner="Jane Smith",
                                    appointmentType="Consultation",
                                    appointmentDate="tomorrow",
                                    appointmentTime="2pm",
                                    locationId="loc-001"
                                ),
                                authenticated=True
                            )
        
        assert response["success"] is False
        assert response["error"] == "time_not_available"
        assert "no longer available" in response["message"]
    
    @pytest.mark.asyncio
    async def test_booking_slot_just_taken(self, mock_pool, mock_cache, mock_clinic, mock_cliniko):
        """Test when slot is taken during booking attempt"""
        pool, conn = mock_pool
        
        # Mock successful checks but Cliniko fails
        conn.fetchrow.side_effect = [
            {"patient_id": "patient-123", "first_name": "John", "last_name": "Doe"},
            {
                "practitioner_id": "prac-123",
                "full_name": "Dr. Jane Smith",
                "business_ids": ["loc-001"],
                "works_at_location": True
            },
            {"appointment_type_id": "appt-type-123", "service_name": "Consultation", "duration_minutes": 60},
            {"is_available": True},
            {"business_name": "Main Clinic"}
        ]
        
        # Mock Cliniko appointment creation failure
        mock_cliniko.create_individual_appointment.side_effect = Exception("Appointment time is not available")
        
        with patch('tools.booking_router_simplified.get_db', return_value=pool):
            with patch('tools.booking_router_simplified.get_cache', return_value=mock_cache):
                with patch('tools.booking_router_simplified.get_clinic_by_dialed_number', return_value=mock_clinic):
                    with patch('tools.booking_router_simplified.ClinikoAPI', return_value=mock_cliniko):
                        with patch('utils.parse_date_request', return_value=date(2024, 3, 20)):
                            with patch('utils.parse_time_request', return_value=time(14, 0)):
                                from tools.booking_router_simplified import handle_appointment
                                from models import BookingRequest
                                
                                response = await handle_appointment(
                                    BookingRequest(
                                        sessionId="test-race",
                                        dialedNumber="0412345678",
                                        callerPhone="0411111111",
                                        practitioner="Jane Smith",
                                        appointmentType="Consultation",
                                        appointmentDate="tomorrow",
                                        appointmentTime="2pm",
                                        locationId="loc-001"
                                    ),
                                    authenticated=True
                                )
        
        assert response["success"] is False
        assert response["error"] == "time_just_taken"
        assert "Someone just booked that time" in response["message"]
        
        # Verify cache was invalidated
        assert any("UPDATE availability_cache" in str(call) for call in conn.execute.call_args_list)
    
    @pytest.mark.asyncio
    async def test_booking_invalid_date(self, mock_pool, mock_cache, mock_clinic):
        """Test booking with invalid date"""
        pool, conn = mock_pool
        
        with patch('tools.booking_router_simplified.get_db', return_value=pool):
            with patch('tools.booking_router_simplified.get_cache', return_value=mock_cache):
                with patch('tools.booking_router_simplified.get_clinic_by_dialed_number', return_value=mock_clinic):
                    with patch('utils.parse_date_request', return_value=None):
                        from tools.booking_router_simplified import handle_appointment
                        from models import BookingRequest
                        
                        response = await handle_appointment(
                            BookingRequest(
                                sessionId="test-bad-date",
                                dialedNumber="0412345678",
                                callerPhone="0411111111",
                                practitioner="Jane Smith",
                                appointmentType="Consultation",
                                appointmentDate="someday",
                                appointmentTime="2pm",
                                locationId="loc-001"
                            ),
                            authenticated=True
                        )
        
        assert response["success"] is False
        assert response["error"] == "invalid_date"
        assert "couldn't understand the date" in response["message"]
    
    @pytest.mark.asyncio
    async def test_booking_database_error(self, mock_pool, mock_cache, mock_clinic):
        """Test handling of database errors"""
        pool, conn = mock_pool
        
        # Mock database error
        conn.fetchrow.side_effect = asyncpg.PostgresError("Connection failed")
        
        with patch('tools.booking_router_simplified.get_db', return_value=pool):
            with patch('tools.booking_router_simplified.get_cache', return_value=mock_cache):
                with patch('tools.booking_router_simplified.get_clinic_by_dialed_number', return_value=mock_clinic):
                    from tools.booking_router_simplified import handle_appointment
                    from models import BookingRequest
                    
                    response = await handle_appointment(
                        BookingRequest(
                            sessionId="test-db-error",
                            dialedNumber="0412345678",
                            callerPhone="0411111111",
                            practitioner="Jane Smith",
                            appointmentType="Consultation",
                            appointmentDate="tomorrow",
                            appointmentTime="2pm",
                            locationId="loc-001"
                        ),
                        authenticated=True
                    )
        
        assert response["success"] is False
        assert response["error"] == "database_error"
        assert "trouble accessing the booking system" in response["message"]