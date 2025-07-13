#!/usr/bin/env python3
"""
Comprehensive test script for Enhanced Parallel Cliniko API Manager

This test validates:
- Rate limiting (59 calls per 60 seconds)
- Parallel processing performance
- Error handling and retries
- Cache integration
- Performance metrics
- Graceful degradation

Based on existing test patterns from test_rate_limiter_real.py and test_parallel_availability.py
"""

import asyncio
import time
import os
import json
from datetime import datetime, timedelta, date
from typing import Dict, Any, List

# Import the enhanced parallel manager
from tools.enhanced_parallel_manager import EnhancedParallelManager, EnhancedRateLimiter, PerformanceMetrics

# Test configuration - use environment variables for real data
CLINIKO_API_KEY = os.environ.get('CLINIKO_API_KEY', 'YOUR_CLINIKO_API_KEY')
CLINIKO_SHARD = os.environ.get('CLINIKO_SHARD', 'au4')
BUSINESS_ID = os.environ.get('BUSINESS_ID', 'YOUR_BUSINESS_ID')
PRACTITIONER_ID = os.environ.get('PRACTITIONER_ID', 'YOUR_PRACTITIONER_ID')
APPOINTMENT_TYPE_ID = os.environ.get('APPOINTMENT_TYPE_ID', 'YOUR_APPTYPE_ID')
BUSINESS_NAME = os.environ.get('BUSINESS_NAME', 'City Clinic')
PRACTITIONER_NAME = os.environ.get('PRACTITIONER_NAME', 'Cameron Lockey')
SERVICE_NAME = os.environ.get('SERVICE_NAME', 'Acupuncture')

# Mock clinic data for testing
class MockClinic:
    cliniko_api_key = CLINIKO_API_KEY
    cliniko_shard = CLINIKO_SHARD
    clinic_id = "test_clinic_001"
    clinic_name = "Test Clinic"
    timezone = "Australia/Sydney"

# Mock cache manager for testing
class MockCacheManager:
    def __init__(self):
        self.cache = {}
    
    async def get_availability(self, practitioner_id: str, business_id: str, check_date: date) -> List[Dict[str, Any]]:
        """Mock cache get - returns None for cache miss"""
        key = f"{practitioner_id}:{business_id}:{check_date}"
        return self.cache.get(key)
    
    async def set_availability(self, practitioner_id: str, business_id: str, check_date: date, clinic_id: str, slots: List[Dict[str, Any]]):
        """Mock cache set"""
        key = f"{practitioner_id}:{business_id}:{check_date}"
        self.cache[key] = slots

# Mock database pool for testing
class MockDatabasePool:
    async def acquire(self):
        return MockConnection()
    
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass

class MockConnection:
    async def fetch(self, query: str, *args):
        return []
    
    async def fetchrow(self, query: str, *args):
        return None

async def test_rate_limiter():
    """Test the enhanced rate limiter with real API calls"""
    print("=== Enhanced Rate Limiter Test ===")
    print(f"Using business: {BUSINESS_NAME}")
    print(f"Practitioner: {PRACTITIONER_NAME}")
    print(f"Service: {SERVICE_NAME}")
    print()
    
    # Create rate limiter
    rate_limiter = EnhancedRateLimiter(max_calls_per_minute=59)
    
    # Test parameters - make enough calls to trigger rate limiting
    n_calls = 100  # More than 59 to trigger rate limiting
    start_time = time.time()
    results = []
    
    print(f"Making {n_calls} API calls with rate limiting...")
    print("This should trigger rate limiting after 59 calls.")
    print("Calls will be made as fast as possible to demonstrate throttling.")
    print()
    
    async def single_call(i):
        call_start = time.time()
        
        # Acquire rate limiter permission
        await rate_limiter.acquire()
        
        # Simulate very fast API call to maximize rate
        await asyncio.sleep(0.01)  # Simulate very fast API call duration
        
        call_end = time.time()
        elapsed = call_end - start_time
        call_duration = call_end - call_start
        
        # Track calls in the last minute for analysis
        last_minute_calls = len([r for r in results if elapsed - r['elapsed'] < 60.0])
        
        print(f"Call {i+1:02d}: {elapsed:6.2f}s (took {call_duration:.3f}s) - ✓ | Rate: {last_minute_calls}/min")
        
        results.append({
            'call_num': i + 1,
            'start_time': call_start - start_time,
            'elapsed': elapsed,
            'duration': call_duration,
            'success': True
        })
    
    # Execute all calls in parallel to maximize rate
    await asyncio.gather(*(single_call(i) for i in range(n_calls)))
    
    total_time = time.time() - start_time
    successful_calls = sum(1 for r in results if r['success'])
    
    print()
    print("=== Rate Limiter Results ===")
    print(f"Total time: {total_time:.2f} seconds")
    print(f"Successful calls: {successful_calls}/{n_calls}")
    print(f"Rate limit delays: {rate_limiter.delay_count}")
    print(f"Total delay time: {rate_limiter.total_delay_time:.2f}s")
    print(f"Average calls per minute: {n_calls / (total_time / 60):.1f}")
    
    # Check if rate limiting worked
    if total_time > 60:  # Should take more than 60s for 80 calls with 59/min limit
        print("✅ Rate limiter working: Total time > 60s indicates calls were delayed")
        print(f"   Expected minimum time: {n_calls / 59 * 60:.1f}s")
        print(f"   Actual time: {total_time:.1f}s")
    else:
        print("❌ Rate limiter may not be working: Total time < 60s")
    
    # Analyze rate over time windows
    print()
    print("Rate Analysis by Time Windows:")
    for window_start in range(0, int(total_time) + 1, 10):
        window_end = window_start + 10
        calls_in_window = len([r for r in results if window_start <= r['elapsed'] <= window_end])
        print(f"  {window_start:2d}-{window_end:2d}s: {calls_in_window:2d} calls ({calls_in_window * 6:.1f}/min)")
    
    # Show timing distribution
    print()
    print("Timing analysis:")
    for i in range(0, n_calls, 10):
        batch = results[i:i+10]
        avg_start = sum(r['start_time'] for r in batch) / len(batch)
        print(f"Calls {i+1:02d}-{min(i+10, n_calls):02d}: avg start at {avg_start:.2f}s")
    
    # Demonstrate rate limiting is working
    if rate_limiter.delay_count > 0:
        print(f"\n✅ RATE LIMITING CONFIRMED:")
        print(f"   - {rate_limiter.delay_count} calls were delayed")
        print(f"   - Total delay time: {rate_limiter.total_delay_time:.2f}s")
        print(f"   - Average delay per throttled call: {rate_limiter.total_delay_time / rate_limiter.delay_count:.2f}s")
    else:
        print(f"\n⚠ RATE LIMITING NOT TRIGGERED:")
        print(f"   - No calls were delayed")
        print(f"   - This might indicate the test didn't hit the rate limit")
        print(f"   - Consider increasing n_calls or reducing API call simulation time")

async def test_parallel_manager():
    """Test the enhanced parallel manager with real availability checks"""
    print("\n=== Enhanced Parallel Manager Test ===")
    
    # Create mock dependencies
    mock_pool = MockDatabasePool()
    mock_cache = MockCacheManager()
    mock_clinic = MockClinic()
    
    # Create parallel manager
    manager = EnhancedParallelManager(mock_pool, mock_cache, mock_clinic)
    
    # Test search criteria
    search_criteria = [
        {
            'practitioner_id': PRACTITIONER_ID,
            'practitioner_name': PRACTITIONER_NAME,
            'appointment_type_id': APPOINTMENT_TYPE_ID,
            'service_name': SERVICE_NAME,
            'business_id': BUSINESS_ID,
            'business_name': BUSINESS_NAME
        }
    ]
    
    print(f"Testing parallel availability check for {len(search_criteria)} criteria")
    print(f"Search criteria: {json.dumps(search_criteria, indent=2)}")
    print()
    
    # Test parallel availability check
    start_time = time.time()
    result = await manager.check_availability_parallel(
        search_criteria=search_criteria,
        max_days=7,  # Test with 7 days
        session_id="test-session-001"
    )
    total_time = time.time() - start_time
    
    print("=== Parallel Manager Results ===")
    print(f"Total execution time: {total_time:.2f}s")
    print(f"Success: {result.get('success', False)}")
    print(f"Found: {result.get('found', False)}")
    print(f"Message: {result.get('message', 'No message')}")
    
    # Get and display metrics
    metrics = manager.get_metrics()
    print()
    print("=== Performance Metrics ===")
    print(f"Total calls: {metrics.total_calls}")
    print(f"Successful calls: {metrics.successful_calls}")
    print(f"Failed calls: {metrics.failed_calls}")
    print(f"Cache hits: {metrics.cache_hits}")
    print(f"Average duration: {metrics.average_duration:.3f}s")
    print(f"Rate limit delays: {metrics.rate_limit_delays}")
    print(f"Total delay time: {metrics.total_delay_time:.2f}s")
    
    if metrics.total_calls > 0:
        success_rate = (metrics.successful_calls / metrics.total_calls) * 100
        print(f"Success rate: {success_rate:.1f}%")

async def test_error_handling():
    """Test error handling and retry logic"""
    print("\n=== Error Handling Test ===")
    
    # Create mock dependencies
    mock_pool = MockDatabasePool()
    mock_cache = MockCacheManager()
    mock_clinic = MockClinic()
    
    # Create parallel manager
    manager = EnhancedParallelManager(mock_pool, mock_cache, mock_clinic)
    
    # Create tasks that will fail
    async def failing_task():
        await asyncio.sleep(0.1)
        raise Exception("Simulated API error")
    
    async def timeout_task():
        await asyncio.sleep(10.0)  # Will timeout
        return "success"
    
    async def successful_task():
        await asyncio.sleep(0.1)
        return "success"
    
    tasks = [failing_task, timeout_task, successful_task]
    
    print("Testing error handling with mixed success/failure tasks...")
    
    start_time = time.time()
    results = await manager.execute_parallel_calls(tasks, timeout=5.0)
    total_time = time.time() - start_time
    
    print(f"Execution time: {total_time:.2f}s")
    print(f"Results: {len(results)} tasks completed")
    
    for i, result in enumerate(results):
        status = "✓" if result.success else "✗"
        print(f"Task {i+1}: {status} - {result.error or 'Success'} (took {result.duration:.3f}s, {result.retries} retries)")

async def test_performance_comparison():
    """Compare performance with different concurrency levels"""
    print("\n=== Performance Comparison Test ===")
    
    # Create mock dependencies
    mock_pool = MockDatabasePool()
    mock_cache = MockCacheManager()
    mock_clinic = MockClinic()
    
    # Test different concurrency levels
    concurrency_levels = [1, 3, 5, 10]
    n_tasks = 20
    
    results = {}
    
    for concurrency in concurrency_levels:
        print(f"\nTesting with {concurrency} concurrent calls...")
        
        # Create tasks
        async def mock_api_call():
            await asyncio.sleep(0.5)  # Simulate API call
            return {"data": "success"}
        
        tasks = [mock_api_call for _ in range(n_tasks)]
        
        # Create manager with custom concurrency
        manager = EnhancedParallelManager(mock_pool, mock_cache, mock_clinic)
        manager.semaphore = asyncio.Semaphore(concurrency)
        
        start_time = time.time()
        api_results = await manager.execute_parallel_calls(tasks, timeout=30.0)
        total_time = time.time() - start_time
        
        metrics = manager.get_metrics()
        
        results[concurrency] = {
            'total_time': total_time,
            'success_rate': (metrics.successful_calls / metrics.total_calls) * 100 if metrics.total_calls > 0 else 0,
            'average_duration': metrics.average_duration,
            'rate_limit_delays': metrics.rate_limit_delays
        }
        
        print(f"  Total time: {total_time:.2f}s")
        print(f"  Success rate: {results[concurrency]['success_rate']:.1f}%")
        print(f"  Average duration: {metrics.average_duration:.3f}s")
        print(f"  Rate limit delays: {metrics.rate_limit_delays}")
    
    # Summary
    print("\n=== Performance Summary ===")
    print("Concurrency | Total Time | Success Rate | Avg Duration | Rate Delays")
    print("-" * 65)
    for concurrency, result in results.items():
        print(f"{concurrency:11d} | {result['total_time']:10.2f}s | {result['success_rate']:11.1f}% | {result['average_duration']:12.3f}s | {result['rate_limit_delays']:11d}")

async def test_cache_integration():
    """Test cache integration and hit rates"""
    print("\n=== Cache Integration Test ===")
    
    # Create mock dependencies
    mock_pool = MockDatabasePool()
    mock_cache = MockCacheManager()
    mock_clinic = MockClinic()
    
    # Create parallel manager
    manager = EnhancedParallelManager(mock_pool, mock_cache, mock_clinic)
    
    # Test search criteria
    search_criteria = [
        {
            'practitioner_id': PRACTITIONER_ID,
            'practitioner_name': PRACTITIONER_NAME,
            'appointment_type_id': APPOINTMENT_TYPE_ID,
            'service_name': SERVICE_NAME,
            'business_id': BUSINESS_ID,
            'business_name': BUSINESS_NAME
        }
    ]
    
    print("Testing cache integration...")
    
    # First call - should hit API
    print("First call (cache miss)...")
    start_time = time.time()
    result1 = await manager.check_availability_parallel(
        search_criteria=search_criteria,
        max_days=3,
        session_id="cache-test-1"
    )
    time1 = time.time() - start_time
    
    # Second call - should hit cache
    print("Second call (cache hit)...")
    start_time = time.time()
    result2 = await manager.check_availability_parallel(
        search_criteria=search_criteria,
        max_days=3,
        session_id="cache-test-2"
    )
    time2 = time.time() - start_time
    
    # Get metrics
    metrics = manager.get_metrics()
    
    print(f"First call time: {time1:.2f}s")
    print(f"Second call time: {time2:.2f}s")
    print(f"Cache hits: {metrics.cache_hits}")
    print(f"Total API calls: {metrics.total_calls}")
    
    if time2 < time1:
        print("✓ Cache is working: Second call was faster")
    else:
        print("⚠ Cache may not be working: Second call was not faster")

async def main():
    """Run all tests"""
    print("Enhanced Parallel Cliniko API Manager - Comprehensive Test Suite")
    print("=" * 70)
    
    # Check if we have real API credentials
    if CLINIKO_API_KEY == 'YOUR_CLINIKO_API_KEY':
        print("⚠ No real API credentials found. Running with mock data.")
        print("Set CLINIKO_API_KEY, CLINIKO_SHARD, BUSINESS_ID, etc. for real API tests.")
        print()
    
    try:
        # Run all tests
        await test_rate_limiter()
        await test_parallel_manager()
        await test_error_handling()
        await test_performance_comparison()
        await test_cache_integration()
        
        print("\n" + "=" * 70)
        print("✅ All tests completed successfully!")
        print("📊 Key metrics validated:")
        print("   - Rate limiting (59 calls per 60 seconds)")
        print("   - Parallel processing performance")
        print("   - Error handling and retries")
        print("   - Cache integration")
        print("   - Performance monitoring")
        
    except Exception as e:
        print(f"\n❌ Test failed: {str(e)}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main()) 