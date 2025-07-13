# ElevenLabs-Compatible Multi-Location Voice Booking System

**(FastAPI + Supabase + Cliniko API)**

---

## Overview

This project is an AI-powered voice receptionist system for multi-location clinics, integrating FastAPI, Supabase, and the Cliniko API. It enables intelligent location disambiguation, robust validation, and fast, JSON-compliant webhook communication with ElevenLabs' Conversational AI platform.

- **All appointment availability and booking checks require practitioner, business (location), and treatment type.**
- **All API payloads and code use `business_id` for location references.**
- **All conversational logic is handled by the voice agent; the backend only validates, queries, and responds.**

---

## Key Features

- Multi-location, multi-practitioner support
- Robust timezone handling (UTC internally, clinic-local for users)
- Fast, structured JSON webhooks for ElevenLabs
- Caching and parallel processing for performance
- **Real-time Cliniko fallback:** If the cache is missing or stale, the system automatically fetches live availability from Cliniko, updates the cache, and uses the fresh data for all practitioner/location/date checks and bookings.
- Session-based rejected slot tracking (see below)

---

## Quick Start

1. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```
2. **Set environment variables:**
   See `.env.example` or below for required keys (DATABASE_URL, SUPABASE_URL, etc).
3. **Run locally:**
   ```bash
   uvicorn main:app --host 0.0.0.0 --port 8000
   ```
4. **Run tests:**
   ```bash
   python test_all_webhooks.py
   ```

---

## Session-Based Rejected Slot Tracking

- The backend tracks rejected appointment slots per session in Supabase (`session_rejected_slots` table).
- When a user rejects offered slots, those slots are stored and not offered again in the same session.
- If the user changes search criteria or books, the rejected slots are reset.
- This logic is fully backend-managed and does not require the voice agent to track state.
- **Cache fallback:** If the cache is missing or stale when checking availability, the backend will fetch live data from Cliniko, update the cache, and use the fresh data. This ensures users always get the most accurate, up-to-date availability.
- See [GRANULAR_ARCHITECTURE.md](./GRANULAR_ARCHITECTURE.md#session-based-rejected-slot-tracking) for details.

---

## Cliniko API Key Management

- All production code (API endpoints, routers, background jobs) retrieves the Cliniko API key securely from Supabase, per clinic.
- Environment variables for the Cliniko API key are only used in non-production scripts (e.g., onboarding, debugging, or local utilities) and are not used in any production or user-facing code paths.
- This ensures secure, scalable, and per-client management of API credentials.
- When onboarding a new clinic, the key is collected and stored in Supabase, never in environment variables for production use.

---

## Practitioner Schedule Initialization & Optimization

- **Initial Data Population:**
  - Use the `probe_practitioner_schedules.py` script to probe all practitioner-business pairs for their working days and hours, up to 1 year in the future.
  - The script uses a `force_full_scan` flag (default `True`) to check all days for all pairs during the initialization phase, ensuring a complete schedule is captured.
  - Results are written to both a CSV file and upserted into the `practitioner_schedules` table in Supabase/Postgres.

- **Production Optimization:**
  - Once the `practitioner_schedules` table is populated, all API endpoints (availability checks, booking, etc.) use this table to determine which days to check for each practitioner at each business/location.
  - **Endpoints always use the optimized, schedule-aware logic**—they only check days when the practitioner is scheduled to work at a location, never performing a full scan.
  - The full scan logic is only present in the probe script for initialization or full refreshes, not in production endpoints.

- **No Code Duplication:**
  - The same codebase supports both initialization and production by using the `force_full_scan` flag in the probe script.
  - Endpoints do not require or support this flag; they always use the optimized logic.

---

## API & Endpoint Reference

For full technical documentation, endpoint details, and architectural notes, see:

➡️ **[GRANULAR_ARCHITECTURE.md](./GRANULAR_ARCHITECTURE.md)**

---

## Troubleshooting & FAQ

- If bookings fail with `time_not_available`, check practitioner/service/location IDs and availability in Cliniko.
- All times sent to Cliniko are in UTC; all user-facing times are in the clinic's local timezone.
- For error codes, response structure, and more, see [GRANULAR_ARCHITECTURE.md](./GRANULAR_ARCHITECTURE.md#webhook-response-structure--migration-2025).

---

## Test Requirements

To run the test suite, you need the following Python packages:

- `pytest` (for running tests)
- `requests` (for HTTP API tests)
- `python-dotenv` (for environment variable loading in tests)
- Any other dependencies listed in `requirements.txt`

**Install all requirements:**
```bash
pip install -r requirements.txt
pip install pytest
```

**Run all tests:**
```bash
pytest
```

Or run a specific test file:
```bash
python test_all_webhooks.py
```

---

## License
MIT