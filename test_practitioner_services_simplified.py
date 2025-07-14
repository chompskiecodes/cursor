# tests/test_practitioner_services_simplified.py
"""Tests for simplified practitioner services endpoint"""

import pytest
from unittest.mock import AsyncMock, patch

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

class TestPractitionerServices:
    """Test simplified get-practitioner-services endpoint"""
    
    @pytest.mark.asyncio
    async def test_get_services_success_multiple(self, mock_pool, mock_clinic):
        """Test getting services for practitioner with multiple services"""
        pool, conn = mock_pool
        
        # Mock query result with multiple services
        mock_result = {
            "practitioner": {
                "id": "prac-123",
                "name": "Dr. Jane Smith",
                "first_name": "Jane",
                "active": True,
                "match_score": 0.95
            },
            "services": [
                {
                    "id": "svc-001",
                    "name": "Consultation (60 min)",
                    "duration": 60,
                    "price": 150.00,
                    "category": "Consultation",
                    "keywords": ["60 minute"]
                },
                {
                    "id": "svc-002",
                    "name": "Consultation (30 min)",
                    "duration": 30,
                    "price": 90.00,
                    "category": "Consultation",
                    "keywords": ["30 minute"]
                },
                {
                    "id": "svc-003",
                    "name": "Follow Up (15 min)",
                    "duration": 15,
                    "price": 50.00,
                    "category": "Follow Up",
                    "keywords": ["follow up"]
                }
            ],
            "summary": {
                "total_services": 3,
                "category_count": 2,
                "categories": ["Consultation", "Follow Up"],
                "min_duration": 15,
                "max_duration": 60,
                "has_new_patient": False,
                "has_follow_up": True
            },
            "suggestions": []
        }
        
        conn.fetchval.return_value = mock_result
        
        with patch('tools.practitioner_router_simplified.get_db', return_value=pool):
            with patch('tools.practitioner_router_simplified.get_clinic_by_dialed_number', return_value=mock_clinic):
                from tools.practitioner_router_simplified import get_practitioner_services, GetPractitionerServicesRequest
                
                response = await get_practitioner_services(
                    GetPractitionerServicesRequest(
                        practitioner="Jane Smith",
                        sessionId="test-123",
                        dialedNumber="0412345678"
                    ),
                    authenticated=True
                )
        
        assert response["success"] is True
        assert response["practitioner"] == "Dr. Jane Smith"
        assert response["practitionerId"] == "prac-123"
        assert len(response["services"]) == 3
        assert "Consultation (60 min)" in response["services"]
        assert "3 services" in response["message"]
        assert "consultation, and follow up" in response["message"].lower()
        assert response["summary"]["durationRange"] == "15-60 minutes"
    
    @pytest.mark.asyncio
    async def test_get_services_single_service(self, mock_pool, mock_clinic):
        """Test practitioner with single service"""
        pool, conn = mock_pool
        
        # Mock result with single service
        mock_result = {
            "practitioner": {
                "id": "prac-456",
                "name": "Dr. John Doe",
                "first_name": "John",
                "active": True,
                "match_score": 0.9
            },
            "services": [
                {
                    "id": "svc-001",
                    "name": "Massage (60 min)",
                    "duration": 60,
                    "price": 120.00,
                    "category": "Massage",
                    "keywords": ["60 minute"]
                }
            ],
            "summary": {
                "total_services": 1,
                "category_count": 1,
                "categories": ["Massage"],
                "min_duration": 60,
                "max_duration": 60,
                "has_new_patient": False,
                "has_follow_up": False
            },
            "suggestions": []
        }
        
        conn.fetchval.return_value = mock_result
        
        with patch('tools.practitioner_router_simplified.get_db', return_value=pool):
            with patch('tools.practitioner_router_simplified.get_clinic_by_dialed_number', return_value=mock_clinic):
                from tools.practitioner_router_simplified import get_practitioner_services, GetPractitionerServicesRequest
                
                response = await get_practitioner_services(
                    GetPractitionerServicesRequest(
                        practitioner="John Doe",
                        sessionId="test-456",
                        dialedNumber="0412345678"
                    ),
                    authenticated=True
                )
        
        assert response["success"] is True
        assert response["message"] == "Dr. John Doe offers Massage (60 min)."
        assert len(response["services"]) == 1
        assert response["summary"]["durationRange"] == "60 minutes"
    
    @pytest.mark.asyncio
    async def test_get_services_with_acupuncture(self, mock_pool, mock_clinic):
        """Test special handling for acupuncture services"""
        pool, conn = mock_pool
        
        # Mock result with acupuncture services
        mock_result = {
            "practitioner": {
                "id": "prac-789",
                "name": "Dr. Sarah Chen",
                "first_name": "Sarah",
                "active": True,
                "match_score": 0.95
            },
            "services": [
                {
                    "id": "svc-001",
                    "name": "Acupuncture Initial (90 min)",
                    "duration": 90,
                    "price": 180.00,
                    "category": "New Patient",
                    "keywords": ["90 minute", "initial"]
                },
                {
                    "id": "svc-002",
                    "name": "Acupuncture Follow Up (60 min)",
                    "duration": 60,
                    "price": 120.00,
                    "category": "Follow Up",
                    "keywords": ["60 minute", "follow up"]
                }
            ],
            "summary": {
                "total_services": 2,
                "category_count": 2,
                "categories": ["New Patient", "Follow Up"],
                "min_duration": 60,
                "max_duration": 90,
                "has_new_patient": True,
                "has_follow_up": True
            },
            "suggestions": []
        }
        
        conn.fetchval.return_value = mock_result
        
        with patch('tools.practitioner_router_simplified.get_db', return_value=pool):
            with patch('tools.practitioner_router_simplified.get_clinic_by_dialed_number', return_value=mock_clinic):
                from tools.practitioner_router_simplified import get_practitioner_services, GetPractitionerServicesRequest
                
                response = await get_practitioner_services(
                    GetPractitionerServicesRequest(
                        practitioner="Sarah Chen",
                        sessionId="test-789",
                        dialedNumber="0412345678"
                    ),
                    authenticated=True
                )
        
        assert response["success"] is True
        assert "For acupuncture, please specify if you're a new or returning patient" in response["message"]
        assert response["summary"]["hasNewPatient"] is True
        assert response["summary"]["hasFollowUp"] is True
    
    @pytest.mark.asyncio
    async def test_get_services_practitioner_not_found(self, mock_pool, mock_clinic):
        """Test when practitioner not found"""
        pool, conn = mock_pool
        
        # Mock result with no practitioner match
        mock_result = {
            "practitioner": None,
            "services": [],
            "summary": None,
            "suggestions": ["Dr. Jane Smith", "Dr. John Doe", "Dr. Sarah Chen"]
        }
        
        conn.fetchval.return_value = mock_result
        
        with patch('tools.practitioner_router_simplified.get_db', return_value=pool):
            with patch('tools.practitioner_router_simplified.get_clinic_by_dialed_number', return_value=mock_clinic):
                from tools.practitioner_router_simplified import get_practitioner_services, GetPractitionerServicesRequest
                
                response = await get_practitioner_services(
                    GetPractitionerServicesRequest(
                        practitioner="Dr. Nobody",
                        sessionId="test-not-found",
                        dialedNumber="0412345678"
                    ),
                    authenticated=True
                )
        
        assert response["success"] is False
        assert response["error"] == "practitioner_not_found"
        assert "Dr. Nobody" in response["message"]
        assert len(response["suggestions"]) == 3
        assert "Dr. Jane Smith" in response["suggestions"]
    
    @pytest.mark.asyncio
    async def test_get_services_practitioner_inactive(self, mock_pool, mock_clinic):
        """Test when practitioner is inactive"""
        pool, conn = mock_pool
        
        # Mock result with inactive practitioner
        mock_result = {
            "practitioner": {
                "id": "prac-old",
                "name": "Dr. Retired Person",
                "first_name": "Retired",
                "active": False,
                "match_score": 0.9
            },
            "services": [],
            "summary": None,
            "suggestions": ["Dr. Jane Smith", "Dr. John Doe"]
        }
        
        conn.fetchval.return_value = mock_result
        
        with patch('tools.practitioner_router_simplified.get_db', return_value=pool):
            with patch('tools.practitioner_router_simplified.get_clinic_by_dialed_number', return_value=mock_clinic):
                from tools.practitioner_router_simplified import get_practitioner_services, GetPractitionerServicesRequest
                
                response = await get_practitioner_services(
                    GetPractitionerServicesRequest(
                        practitioner="Retired Person",
                        sessionId="test-inactive",
                        dialedNumber="0412345678"
                    ),
                    authenticated=True
                )
        
        assert response["success"] is False
        assert response["error"] == "practitioner_inactive"
        assert "no longer taking appointments" in response["message"]
        assert "You might want to see" in response["message"]
        assert len(response["suggestions"]) == 2
    
    @pytest.mark.asyncio
    async def test_get_services_no_services_configured(self, mock_pool, mock_clinic):
        """Test practitioner with no services configured"""
        pool, conn = mock_pool
        
        # Mock result with practitioner but no services
        mock_result = {
            "practitioner": {
                "id": "prac-new",
                "name": "Dr. New Practitioner",
                "first_name": "New",
                "active": True,
                "match_score": 0.95
            },
            "services": [],
            "summary": {
                "total_services": 0,
                "category_count": 0,
                "categories": []
            },
            "suggestions": []
        }
        
        conn.fetchval.return_value = mock_result
        
        with patch('tools.practitioner_router_simplified.get_db', return_value=pool):
            with patch('tools.practitioner_router_simplified.get_clinic_by_dialed_number', return_value=mock_clinic):
                from tools.practitioner_router_simplified import get_practitioner_services, GetPractitionerServicesRequest
                
                response = await get_practitioner_services(
                    GetPractitionerServicesRequest(
                        practitioner="New Practitioner",
                        sessionId="test-no-services",
                        dialedNumber="0412345678"
                    ),
                    authenticated=True
                )
        
        assert response["success"] is True  # Still successful, just no services
        assert response["practitioner"] == "Dr. New Practitioner"
        assert len(response["services"]) == 0
        assert "doesn't have any services configured" in response["message"]
        assert response["serviceNames"] == []  # Backward compatibility field
    
    @pytest.mark.asyncio
    async def test_get_services_varied_durations(self, mock_pool, mock_clinic):
        """Test message formatting with varied service durations"""
        pool, conn = mock_pool
        
        # Mock result with varied durations
        mock_result = {
            "practitioner": {
                "id": "prac-123",
                "name": "Dr. Jane Smith",
                "first_name": "Jane",
                "active": True,
                "match_score": 0.95
            },
            "services": [
                {"id": "svc-001", "name": "Quick Check (15 min)", "duration": 15, "category": "Consultation"},
                {"id": "svc-002", "name": "Standard (30 min)", "duration": 30, "category": "Consultation"},
                {"id": "svc-003", "name": "Extended (45 min)", "duration": 45, "category": "Consultation"},
                {"id": "svc-004", "name": "Comprehensive (90 min)", "duration": 90, "category": "Consultation"}
            ],
            "summary": {
                "total_services": 4,
                "category_count": 1,
                "categories": ["Consultation"],
                "min_duration": 15,
                "max_duration": 90,
                "has_new_patient": False,
                "has_follow_up": False
            },
            "suggestions": []
        }
        
        conn.fetchval.return_value = mock_result
        
        with patch('tools.practitioner_router_simplified.get_db', return_value=pool):
            with patch('tools.practitioner_router_simplified.get_clinic_by_dialed_number', return_value=mock_clinic):
                from tools.practitioner_router_simplified import get_practitioner_services, GetPractitionerServicesRequest
                
                response = await get_practitioner_services(
                    GetPractitionerServicesRequest(
                        practitioner="Jane Smith",
                        sessionId="test-varied",
                        dialedNumber="0412345678"
                    ),
                    authenticated=True
                )
        
        assert response["success"] is True
        assert "4 consultation services" in response["message"].lower()
        assert "Sessions range from 15 to 90 minutes" in response["message"]
        assert response["summary"]["durationRange"] == "15-90 minutes"