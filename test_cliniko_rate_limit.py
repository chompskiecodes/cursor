import asyncio
import time
from cliniko import ClinikoAPI

async def test_rate_limiter():
    api = ClinikoAPI('dummy_key', 'au4', 'TestAgent/1.0')
    n_calls = 70
    start = time.time()
    results = []

    async def single_call(i):
        t0 = time.time()
        try:
            # This will fail due to dummy key, but we only care about timing
            await api.get_available_times('dummy_biz', 'dummy_prac', 'dummy_type', '2025-07-24', '2025-07-25')
        except Exception as e:
            pass
        t1 = time.time()
        print(f"Call {i+1:02d} at {t1-start:.2f}s (waited {t1-t0:.2f}s)")
        results.append(t1)

    await asyncio.gather(*(single_call(i) for i in range(n_calls)))
    print(f"Total time for {n_calls} calls: {time.time()-start:.2f}s")

if __name__ == "__main__":
    asyncio.run(test_rate_limiter()) 