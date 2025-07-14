# tests/test_sync_router.py
"""Tests for the sync-cache endpoint"""

import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch
import asyncpg
from fastapi.testclient import TestClient
from tools.sync_router import router, active_syncs, sync_sessions

# Mock dependencies
@pytest.fixture
def mock_pool():
    """Mock database pool"""
    pool = AsyncMock(spec=asyncpg.Pool)
    conn = AsyncMock()
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
        businesses=[],
        timezone="Australia/Sydney"
    )

@pytest.fixture
def test_client():
    """Create test client"""
    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)

class TestSyncCache:
    """Test sync-cache endpoint"""
    
    @pytest.mark.asyncio
    async def test_sync_cache_success(self, mock_pool, mock_cache, mock_clinic):
        """Test successful cache sync"""
        pool, conn = mock_pool
        
        # Mock database responses
        conn.fetchrow.side_effect = [
            # Last sync query
            {"last_sync": datetime.now(timezone.utc) - timedelta(hours=2), 
             "cached_practitioners": 5, "total_slots": 100},
            # Sync status check
            {"active_count": 0}
        ]
        
        # Mock sync execution
        with patch('tools.sync_router.get_db', return_value=pool):
            with patch('tools.sync_router.get_cache', return_value=mock_cache):
                with patch('tools.sync_router.get_clinic_by_dialed_number', return_value=mock_clinic):
                    with patch('tools.sync_router.IncrementalCacheSync') as mock_sync_class:
                        mock_sync = AsyncMock()
                        mock_sync.sync_appointments_incremental.return_value = {
                            'updated': 25, 'deleted': 2, 'errors': 0
                        }
                        mock_sync_class.return_value = mock_sync
                        
                        # Make request
                        from tools.sync_router import sync_cache
                        response = await sync_cache({
                            "sessionId": "test-session-123",
                            "dialedNumber": "0412345678",
                            "forceFullSync": False
                        }, authenticated=True)
        
        assert response["success"] is True
        assert response["syncType"] == "incremental"
        assert response["syncStats"]["updated"] == 25
        assert "test-session-123" in sync_sessions
    
    @pytest.mark.asyncio
    async def test_sync_cache_already_running(self, mock_pool, mock_cache, mock_clinic):
        """Test sync when another sync is already running"""
        pool, conn = mock_pool
        
        # Add clinic to active syncs
        active_syncs.add("test-clinic-123")
        
        try:
            with patch('tools.sync_router.get_db', return_value=pool):
                with patch('tools.sync_router.get_cache', return_value=mock_cache):
                    with patch('tools.sync_router.get_clinic_by_dialed_number', return_value=mock_clinic):
                        from tools.sync_router import sync_cache
                        response = await sync_cache({
                            "sessionId": "test-session-456",
                            "dialedNumber": "0412345678",
                            "forceFullSync": False
                        }, authenticated=True)
            
            assert response["success"] is True
            assert response["syncType"] == "skipped"
            assert response["syncInProgress"] is True
            assert response["message"] == "Cache sync is already in progress"
        finally:
            # Clean up
            active_syncs.discard("test-clinic-123")
    
    @pytest.mark.asyncio
    async def test_sync_cache_force_full_sync(self, mock_pool, mock_cache, mock_clinic):
        """Test forced full sync"""
        pool, conn = mock_pool
        
        # Mock no previous sync
        conn.fetchrow.side_effect = [
            {"last_sync": None, "cached_practitioners": 0, "total_slots": 0},
            {"active_count": 0}
        ]
        
        with patch('tools.sync_router.get_db', return_value=pool):
            with patch('tools.sync_router.get_cache', return_value=mock_cache):
                with patch('tools.sync_router.get_clinic_by_dialed_number', return_value=mock_clinic):
                    with patch('tools.sync_router.IncrementalCacheSync') as mock_sync_class:
                        mock_sync = AsyncMock()
                        mock_sync.sync_appointments_incremental.return_value = {
                            'updated': 150, 'deleted': 0, 'errors': 0
                        }
                        mock_sync_class.return_value = mock_sync
                        
                        from tools.sync_router import sync_cache
                        response = await sync_cache({
                            "sessionId": "test-session-789",
                            "dialedNumber": "0412345678",
                            "forceFullSync": True
                        }, authenticated=True)
        
        assert response["success"] is True
        assert response["syncType"] == "full"
        assert response["syncStats"]["updated"] == 150
        
        # Verify force_full_sync was passed
        mock_sync.sync_appointments_incremental.assert_called_once()
        call_args = mock_sync.sync_appointments_incremental.call_args
        assert call_args[1]["force_full_sync"] is True
    
    @pytest.mark.asyncio
    async def test_sync_cache_clinic_not_found(self, mock_pool, mock_cache):
        """Test sync when clinic not found"""
        pool, conn = mock_pool
        
        with patch('tools.sync_router.get_db', return_value=pool):
            with patch('tools.sync_router.get_cache', return_value=mock_cache):
                with patch('tools.sync_router.get_clinic_by_dialed_number', return_value=None):
                    from tools.sync_router import sync_cache
                    response = await sync_cache({
                        "sessionId": "test-session-404",
                        "dialedNumber": "0499999999",
                        "forceFullSync": False
                    }, authenticated=True)
        
        assert response["success"] is False
        assert response["message"] == "Unable to identify clinic"
    
    @pytest.mark.asyncio
    async def test_sync_cache_session_deduplication(self, mock_pool, mock_cache, mock_clinic):
        """Test that same session doesn't sync twice within 1 minute"""
        pool, conn = mock_pool
        
        # Add session to recent syncs
        sync_sessions["test-session-dup"] = datetime.now(timezone.utc)
        
        try:
            with patch('tools.sync_router.get_db', return_value=pool):
                with patch('tools.sync_router.get_cache', return_value=mock_cache):
                    with patch('tools.sync_router.get_clinic_by_dialed_number', return_value=mock_clinic):
                        from tools.sync_router import sync_cache
                        response = await sync_cache({
                            "sessionId": "test-session-dup",
                            "dialedNumber": "0412345678",
                            "forceFullSync": False
                        }, authenticated=True)
            
            assert response["success"] is True
            assert response["syncType"] == "skipped"
            assert response["message"] == "Cache is already up to date for this call"
        finally:
            # Clean up
            if "test-session-dup" in sync_sessions:
                del sync_sessions["test-session-dup"]
    
    @pytest.mark.asyncio
    async def test_sync_cache_error_handling(self, mock_pool, mock_cache, mock_clinic):
        """Test sync error handling"""
        pool, conn = mock_pool
        
        # Mock sync failure
        with patch('tools.sync_router.get_db', return_value=pool):
            with patch('tools.sync_router.get_cache', return_value=mock_cache):
                with patch('tools.sync_router.get_clinic_by_dialed_number', return_value=mock_clinic):
                    with patch('tools.sync_router.IncrementalCacheSync') as mock_sync_class:
                        mock_sync = AsyncMock()
                        mock_sync.sync_appointments_incremental.side_effect = Exception("Sync failed!")
                        mock_sync_class.return_value = mock_sync
                        
                        from tools.sync_router import sync_cache
                        response = await sync_cache({
                            "sessionId": "test-session-error",
                            "dialedNumber": "0412345678",
                            "forceFullSync": False
                        }, authenticated=True)
        
        assert response["success"] is False
        assert response["message"] == "Cache sync encountered an error"
        assert response["sessionId"] == "test-session-error"
    
    @pytest.mark.asyncio
    async def test_get_sync_status(self, mock_pool):
        """Test get sync status endpoint"""
        pool, conn = mock_pool
        
        # Mock last sync data
        conn.fetchrow.return_value = {
            "created_at": datetime.now(timezone.utc) - timedelta(minutes=30),
            "duration_ms": 2500,
            "total_slots_cached": 75,
            "warmup_type": "on_call"
        }
        
        with patch('tools.sync_router.get_db', return_value=pool):
            with patch('tools.sync_router.is_sync_running', return_value=False):
                from tools.sync_router import get_sync_status
                response = await get_sync_status("test-clinic-123", authenticated=True)
        
        assert response["syncInProgress"] is False
        assert response["lastSyncDurationMs"] == 2500
        assert response["lastSyncSlots"] == 75
        assert response["cacheStatus"] == "fresh"
        assert "secondsSinceSync" in response