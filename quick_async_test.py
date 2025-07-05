import asyncio
import httpx

async def main():
    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(
            'http://localhost:8000/availability-checker',
            headers={'Content-Type': 'application/json'},
            json={
                'sessionId': 'test',
                'dialedNumber': '0478621276',
                'practitioner': 'Brendan Smith',
                'appointmentType': 'Acupuncture (Follow up)'
                # No date parameter - should return error directing to find_next_available
            }
        )
        print(response.json())

if __name__ == "__main__":
    asyncio.run(main()) 