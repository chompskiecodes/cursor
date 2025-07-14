# tests/test_location_resolver_simplified.py
"""Tests for simplified location resolver using pg_trgm"""

import pytest
from unittest.mock import AsyncMock, patch
from datetime import datetime, timedelta

@pytest.fixture
def mock_pool():
    """Mock database pool"""
    pool = AsyncMock()
    conn = AsyncMock()
    pool.acquire.return_value.__aenter__.return_value = conn
    return pool, conn

@pytest.fixture
def mock_cache():
    """Mock cache manager"""
    cache = AsyncMock()
    cache.get_booking_context.return_value = None
    cache.set_booking_context.return_value = True
    return cache

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
        businesses=[
            {"business_id": "loc-001", "business_name": "City Clinic", "is_primary": True},
            {"business_id": "loc-002", "business_name": "Suburb Clinic", "is_primary": False}
        ],
        timezone="Australia/Sydney"
    )

class TestLocationResolver:
    """Test simplified location resolver"""
    
    @pytest.mark.asyncio
    async def test_location_high_confidence_match(self, mock_pool, mock_cache, mock_clinic):
        """Test high confidence location match"""
        pool, conn = mock_pool
        
        # Mock query result with high confidence match
        mock_result = {
            "matches": [
                {
                    "business_id": "loc-001",
                    "business_name": "City Clinic",
                    "is_primary": True,
                    "match_score": 0.95,
                    "visit_count": 0,
                    "match_details": {
                        "name_similarity": 0.95,
                        "is_primary": True,
                        "visit_count": 0,
                        "matched_alias": None
                    }
                }
            ],
            "summary": {
                "total_matches": 1,
                "best_score": 0.95,
                "high_confidence_matches": 1,
                "medium_confidence_matches": 0
            },
            "all_locations": [
                {"business_id": "loc-001", "business_name": "City Clinic", "is_primary": True},
                {"business_id": "loc-002", "business_name": "Suburb Clinic", "is_primary": False}
            ]
        }
        
        conn.fetchval.return_value = mock_result
        
        with patch('tools.location_router_simplified.get_db', return_value=pool):
            with patch('tools.location_router_simplified.get_cache', return_value=mock_cache):
                with patch('tools.location_router_simplified.get_clinic_by_dialed_number', return_value=mock_clinic):
                    from tools.location_router_simplified import resolve_location
                    from models import LocationResolverRequest
                    
                    response = await resolve_location(
                        LocationResolverRequest(
                            locationQuery="city clinic",
                            sessionId="test-123",
                            dialedNumber="0412345678",
                            callerPhone="0411111111"
                        ),
                        authenticated=True
                    )
        
        assert response["success"] is True
        assert response["action_completed"] is True
        assert response["needs_clarification"] is False
        assert response["business_id"] == "loc-001"
        assert response["business_name"] == "City Clinic"
        assert response["confidence"] == 0.95
        assert "I'll book you at our City Clinic location" in response["message"]
    
    @pytest.mark.asyncio
    async def test_location_medium_confidence_needs_confirmation(self, mock_pool, mock_cache, mock_clinic):
        """Test medium confidence match needing confirmation"""
        pool, conn = mock_pool
        
        # Mock query result with medium confidence
        mock_result = {
            "matches": [
                {
                    "business_id": "loc-002",
                    "business_name": "Suburb Clinic",
                    "is_primary": False,
                    "match_score": 0.65,
                    "visit_count": 0,
                    "match_details": {
                        "name_similarity": 0.65,
                        "is_primary": False,
                        "visit_count": 0,
                        "matched_alias": None
                    }
                }
            ],
            "summary": {
                "total_matches": 1,
                "best_score": 0.65,
                "high_confidence_matches": 0,
                "medium_confidence_matches": 1
            },
            "all_locations": [
                {"business_id": "loc-001", "business_name": "City Clinic", "is_primary": True},
                {"business_id": "loc-002", "business_name": "Suburb Clinic", "is_primary": False}
            ]
        }
        
        conn.fetchval.return_value = mock_result
        
        with patch('tools.location_router_simplified.get_db', return_value=pool):
            with patch('tools.location_router_simplified.get_cache', return_value=mock_cache):
                with patch('tools.location_router_simplified.get_clinic_by_dialed_number', return_value=mock_clinic):
                    from tools.location_router_simplified import resolve_location
                    from models import LocationResolverRequest
                    
                    response = await resolve_location(
                        LocationResolverRequest(
                            locationQuery="suburb",
                            sessionId="test-456",
                            dialedNumber="0412345678"
                        ),
                        authenticated=True
                    )
        
        assert response["success"] is True
        assert response["action_completed"] is False
        assert response["needs_clarification"] is True
        assert "Did you mean our Suburb Clinic location?" in response["message"]
        assert response["options"] == ["Suburb Clinic"]
        assert response["confidence"] == 0.65
    
    @pytest.mark.asyncio
    async def test_location_caller_history_match(self, mock_pool, mock_cache, mock_clinic):
        """Test location match based on caller history"""
        pool, conn = mock_pool
        
        # Mock query result with history-based match
        mock_result = {
            "matches": [
                {
                    "business_id": "loc-002",
                    "business_name": "Suburb Clinic",
                    "is_primary": False,
                    "match_score": 0.95,  # High score due to "my usual" match
                    "visit_count": 5,
                    "match_details": {
                        "name_similarity": 0.1,
                        "is_primary": False,
                        "visit_count": 5,
                        "matched_alias": None
                    }
                }
            ],
            "summary": {
                "total_matches": 1,
                "best_score": 0.95,
                "high_confidence_matches": 1,
                "medium_confidence_matches": 0
            },
            "all_locations": [
                {"business_id": "loc-001", "business_name": "City Clinic", "is_primary": True},
                {"business_id": "loc-002", "business_name": "Suburb Clinic", "is_primary": False}
            ]
        }
        
        conn.fetchval.return_value = mock_result
        
        with patch('tools.location_router_simplified.get_db', return_value=pool):
            with patch('tools.location_router_simplified.get_cache', return_value=mock_cache):
                with patch('tools.location_router_simplified.get_clinic_by_dialed_number', return_value=mock_clinic):
                    from tools.location_router_simplified import resolve_location
                    from models import LocationResolverRequest
                    
                    response = await resolve_location(
                        LocationResolverRequest(
                            locationQuery="my usual place",
                            sessionId="test-789",
                            dialedNumber="0412345678",
                            callerPhone="0411111111"
                        ),
                        authenticated=True
                    )
        
        assert response["success"] is True
        assert response["action_completed"] is True
        assert response["business_id"] == "loc-002"
        assert "where you've been before" in response["message"]
        
        # Verify cache was updated
        mock_cache.set_booking_context.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_location_primary_keyword_match(self, mock_pool, mock_cache, mock_clinic):
        """Test matching primary location with keywords"""
        pool, conn = mock_pool
        
        # Mock query result for "main" keyword
        mock_result = {
            "matches": [
                {
                    "business_id": "loc-001",
                    "business_name": "City Clinic",
                    "is_primary": True,
                    "match_score": 0.9,  # High score for primary keyword
                    "visit_count": 0,
                    "match_details": {
                        "name_similarity": 0.1,
                        "is_primary": True,
                        "visit_count": 0,
                        "matched_alias": None
                    }
                }
            ],
            "summary": {
                "total_matches": 1,
                "best_score": 0.9,
                "high_confidence_matches": 1,
                "medium_confidence_matches": 0
            },
            "all_locations": [
                {"business_id": "loc-001", "business_name": "City Clinic", "is_primary": True},
                {"business_id": "loc-002", "business_name": "Suburb Clinic", "is_primary": False}
            ]
        }
        
        conn.fetchval.return_value = mock_result
        
        with patch('tools.location_router_simplified.get_db', return_value=pool):
            with patch('tools.location_router_simplified.get_cache', return_value=mock_cache):
                with patch('tools.location_router_simplified.get_clinic_by_dialed_number', return_value=mock_clinic):
                    from tools.location_router_simplified import resolve_location
                    from models import LocationResolverRequest
                    
                    response = await resolve_location(
                        LocationResolverRequest(
                            locationQuery="main clinic",
                            sessionId="test-main",
                            dialedNumber="0412345678"
                        ),
                        authenticated=True
                    )
        
        assert response["success"] is True
        assert response["action_completed"] is True
        assert response["business_id"] == "loc-001"
        assert response["confidence"] == 0.9
    
    @pytest.mark.asyncio
    async def test_location_no_matches(self, mock_pool, mock_cache, mock_clinic):
        """Test when no location matches"""
        pool, conn = mock_pool
        
        # Mock query result with no matches
        mock_result = {
            "matches": [],
            "summary": {
                "total_matches": 0,
                "best_score": 0,
                "high_confidence_matches": 0,
                "medium_confidence_matches": 0
            },
            "all_locations": [
                {"business_id": "loc-001", "business_name": "City Clinic", "is_primary": True},
                {"business_id": "loc-002", "business_name": "Suburb Clinic", "is_primary": False}
            ]
        }
        
        conn.fetchval.return_value = mock_result
        
        with patch('tools.location_router_simplified.get_db', return_value=pool):
            with patch('tools.location_router_simplified.get_cache', return_value=mock_cache):
                with patch('tools.location_router_simplified.get_clinic_by_dialed_number', return_value=mock_clinic):
                    from tools.location_router_simplified import resolve_location
                    from models import LocationResolverRequest
                    
                    response = await resolve_location(
                        LocationResolverRequest(
                            locationQuery="downtown office",
                            sessionId="test-no-match",
                            dialedNumber="0412345678"
                        ),
                        authenticated=True
                    )
        
        assert response["success"] is True
        assert response["action_completed"] is False
        assert response["needs_clarification"] is True
        assert "We have: City Clinic, Suburb Clinic" in response["message"]
        assert response["options"] == ["City Clinic", "Suburb Clinic"]
        assert response["confidence"] == 0.0
    
    @pytest.mark.asyncio
    async def test_location_single_location_clinic(self, mock_pool, mock_cache, mock_clinic):
        """Test clinic with only one location"""
        pool, conn = mock_pool
        
        # Mock single location clinic
        single_loc_clinic = mock_clinic.copy()
        single_loc_clinic.businesses = [{"business_id": "loc-001", "business_name": "Main Clinic", "is_primary": True}]
        
        # Mock query result with no matches
        mock_result = {
            "matches": [],
            "summary": {"total_matches": 0},
            "all_locations": [
                {"business_id": "loc-001", "business_name": "Main Clinic", "is_primary": True}
            ]
        }
        
        conn.fetchval.return_value = mock_result
        
        with patch('tools.location_router_simplified.get_db', return_value=pool):
            with patch('tools.location_router_simplified.get_cache', return_value=mock_cache):
                with patch('tools.location_router_simplified.get_clinic_by_dialed_number', return_value=single_loc_clinic):
                    from tools.location_router_simplified import resolve_location
                    from models import LocationResolverRequest
                    
                    response = await resolve_location(
                        LocationResolverRequest(
                            locationQuery="anywhere",
                            sessionId="test-single",
                            dialedNumber="0412345678"
                        ),
                        authenticated=True
                    )
        
        assert response["success"] is True
        assert response["action_completed"] is True
        assert response["needs_clarification"] is False
        assert response["business_id"] == "loc-001"
        assert response["business_name"] == "Main Clinic"
        assert response["confidence"] == 1.0
        assert "I'll book you at our Main Clinic location" in response["message"]
    
    @pytest.mark.asyncio
    async def test_location_multiple_low_confidence_matches(self, mock_pool, mock_cache, mock_clinic):
        """Test multiple low confidence matches"""
        pool, conn = mock_pool
        
        # Mock query result with multiple low confidence matches
        mock_result = {
            "matches": [
                {
                    "business_id": "loc-001",
                    "business_name": "City Clinic",
                    "is_primary": True,
                    "match_score": 0.35,
                    "visit_count": 0,
                    "match_details": {}
                },
                {
                    "business_id": "loc-002",
                    "business_name": "Suburb Clinic",
                    "is_primary": False,
                    "match_score": 0.32,
                    "visit_count": 0,
                    "match_details": {}
                }
            ],
            "summary": {
                "total_matches": 2,
                "best_score": 0.35,
                "high_confidence_matches": 0,
                "medium_confidence_matches": 0
            },
            "all_locations": [
                {"business_id": "loc-001", "business_name": "City Clinic", "is_primary": True},
                {"business_id": "loc-002", "business_name": "Suburb Clinic", "is_primary": False}
            ]
        }
        
        conn.fetchval.return_value = mock_result
        
        with patch('tools.location_router_simplified.get_db', return_value=pool):
            with patch('tools.location_router_simplified.get_cache', return_value=mock_cache):
                with patch('tools.location_router_simplified.get_clinic_by_dialed_number', return_value=mock_clinic):
                    from tools.location_router_simplified import resolve_location
                    from models import LocationResolverRequest
                    
                    response = await resolve_location(
                        LocationResolverRequest(
                            locationQuery="clinic",
                            sessionId="test-multi-low",
                            dialedNumber="0412345678"
                        ),
                        authenticated=True
                    )
        
        assert response["success"] is True
        assert response["action_completed"] is False
        assert response["needs_clarification"] is True
        assert "Did you mean: City Clinic, Suburb Clinic?" in response["message"]
        assert response["options"] == ["City Clinic", "Suburb Clinic"]
        assert response["confidence"] == 0.35