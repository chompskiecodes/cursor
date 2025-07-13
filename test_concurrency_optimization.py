#!/usr/bin/env python3
"""
Concurrency Optimization Test

This test finds the optimal concurrency settings for maximum performance
while respecting Cliniko's 59 calls per minute limit.
"""

import asyncio
import time
from typing import Dict, Any, List
from tools.enhanced_parallel_manager import EnhancedRateLimiter, EnhancedParallelManager
from tools.enhanced_parallel_manager import MAX_CONCURRENT_API_CALLS, RATE_LIMIT_CALLS_PER_MINUTE

# Mock dependencies for testing
class MockClinic:
    cliniko_api_key = "test_key"
    cliniko_shard = "test"
    clinic_id = "test_clinic"
    clinic_name = "Test Clinic"
    timezone = "Australia/Sydney"

class MockCacheManager:
    def __init__(self):
        self.cache = {}
    
    async def get_availability(self, practitioner_id: str, business_id: str, check_date):
        return None
    
    async def set_availability(self, practitioner_id: str, business_id: str, check_date, clinic_id: str, slots):
        pass

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

async def test_concurrency_levels():
    """Test different concurrency levels to find optimal settings"""
    print("=== Concurrency Optimization Test ===")
    print("Testing different concurrency levels to maximize performance")
    print("while respecting Cliniko's 59 calls/minute limit")
    print()
    
    # Test different concurrency levels
    concurrency_levels = [5, 10, 15, 20, 25, 30, 35, 40, 45, 50]
    n_calls = 100  # Test with 100 calls
    api_call_duration = 0.5  # Simulate 500ms API call duration
    
    results = {}
    
    for concurrency in concurrency_levels:
        print(f"Testing concurrency level: {concurrency}")
        
        # Create manager with custom concurrency
        mock_pool = MockDatabasePool()
        mock_cache = MockCacheManager()
        mock_clinic = MockClinic()
        
        manager = EnhancedParallelManager(mock_pool, mock_cache, mock_clinic)
        manager.semaphore = asyncio.Semaphore(concurrency)
        
        # Create tasks
        async def mock_api_call():
            await asyncio.sleep(api_call_duration)  # Simulate API call
            return {"data": "success"}
        
        tasks = [mock_api_call for _ in range(n_calls)]
        
        # Execute test
        start_time = time.time()
        api_results = await manager.execute_parallel_calls(tasks, timeout=120.0)
        total_time = time.time() - start_time
        
        metrics = manager.get_metrics()
        
        # Calculate performance metrics
        success_rate = (metrics.successful_calls / metrics.total_calls) * 100 if metrics.total_calls > 0 else 0
        calls_per_minute = n_calls / (total_time / 60)
        theoretical_max_calls_per_minute = concurrency * (60 / api_call_duration)
        
        results[concurrency] = {
            'total_time': total_time,
            'success_rate': success_rate,
            'calls_per_minute': calls_per_minute,
            'theoretical_max': theoretical_max_calls_per_minute,
            'rate_limit_delays': metrics.rate_limit_delays,
            'total_delay_time': metrics.total_delay_time,
            'efficiency': calls_per_minute / theoretical_max_calls_per_minute if theoretical_max_calls_per_minute > 0 else 0
        }
        
        print(f"  Total time: {total_time:.2f}s")
        print(f"  Success rate: {success_rate:.1f}%")
        print(f"  Calls per minute: {calls_per_minute:.1f}")
        print(f"  Rate limit delays: {metrics.rate_limit_delays}")
        print(f"  Efficiency: {results[concurrency]['efficiency']:.2%}")
        print()
    
    # Analyze results
    print("=== Concurrency Analysis ===")
    print("Concurrency | Time | Calls/min | Efficiency | Rate Delays | Recommendation")
    print("-" * 75)
    
    optimal_concurrency = None
    best_efficiency = 0
    
    for concurrency, result in results.items():
        # Determine recommendation
        if result['calls_per_minute'] >= 58 and result['efficiency'] > 0.8:
            recommendation = "✅ OPTIMAL"
            if result['efficiency'] > best_efficiency:
                optimal_concurrency = concurrency
                best_efficiency = result['efficiency']
        elif result['calls_per_minute'] >= 58:
            recommendation = "⚠ GOOD (low efficiency)"
        elif result['rate_limit_delays'] > 0:
            recommendation = "❌ OVER-LIMIT"
        else:
            recommendation = "📈 UNDER-UTILIZED"
        
        print(f"{concurrency:11d} | {result['total_time']:4.1f}s | {result['calls_per_minute']:8.1f} | {result['efficiency']:9.1%} | {result['rate_limit_delays']:11d} | {recommendation}")
    
    print()
    print("=== Recommendations ===")
    
    if optimal_concurrency:
        print(f"✅ OPTIMAL CONCURRENCY: {optimal_concurrency}")
        print(f"   - Achieves {results[optimal_concurrency]['calls_per_minute']:.1f} calls/minute")
        print(f"   - {results[optimal_concurrency]['efficiency']:.1%} efficiency")
        print(f"   - {results[optimal_concurrency]['rate_limit_delays']} rate limit delays")
        print(f"   - Total time: {results[optimal_concurrency]['total_time']:.1f}s for {n_calls} calls")
    else:
        print("❌ No optimal concurrency found")
        print("   Consider adjusting API call duration or rate limits")
    
    # Find safe maximum
    safe_concurrency = None
    for concurrency in sorted(results.keys()):
        if results[concurrency]['calls_per_minute'] <= 58 and results[concurrency]['rate_limit_delays'] == 0:
            safe_concurrency = concurrency
    
    if safe_concurrency:
        print(f"\n🛡️  SAFE MAXIMUM: {safe_concurrency}")
        print(f"   - Guaranteed to stay under rate limits")
        print(f"   - {results[safe_concurrency]['calls_per_minute']:.1f} calls/minute")
    
    return results

async def test_rate_limit_behavior():
    """Test rate limit behavior with different concurrency levels"""
    print("\n=== Rate Limit Behavior Test ===")
    
    # Test with high concurrency to see rate limiting in action
    concurrency_levels = [10, 20, 30, 40, 50]
    n_calls = 80  # More than 59 to trigger rate limiting
    
    for concurrency in concurrency_levels:
        print(f"\nTesting concurrency {concurrency} with {n_calls} calls:")
        
        # Create rate limiter
        rate_limiter = EnhancedRateLimiter(max_calls_per_minute=59)
        
        # Create semaphore
        semaphore = asyncio.Semaphore(concurrency)
        
        async def single_call(i):
            async with semaphore:
                await rate_limiter.acquire()
                await asyncio.sleep(0.1)  # Simulate API call
                return i
        
        start_time = time.time()
        results = await asyncio.gather(*[single_call(i) for i in range(n_calls)])
        total_time = time.time() - start_time
        
        calls_per_minute = n_calls / (total_time / 60)
        
        print(f"  Total time: {total_time:.2f}s")
        print(f"  Calls per minute: {calls_per_minute:.1f}")
        print(f"  Rate limit delays: {rate_limiter.delay_count}")
        print(f"  Total delay time: {rate_limiter.total_delay_time:.2f}s")

async def main():
    """Run all concurrency optimization tests"""
    print("Concurrency Optimization Analysis")
    print("=" * 50)
    
    # Test different concurrency levels
    results = await test_concurrency_levels()
    
    # Test rate limit behavior
    await test_rate_limit_behavior()
    
    print("\n=== Summary ===")
    print("Based on the analysis, the optimal concurrency settings are:")
    print("1. Use the recommended concurrency level for maximum performance")
    print("2. The rate limiter will handle any overflow automatically")
    print("3. Monitor rate limit delays in production to fine-tune settings")

if __name__ == "__main__":
    asyncio.run(main()) 