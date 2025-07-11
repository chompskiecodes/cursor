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
- See [GRANULAR_ARCHITECTURE.md](./GRANULAR_ARCHITECTURE.md#session-based-rejected-slot-tracking) for details.

---

## Cliniko API Key Management

- All production code (API endpoints, routers, background jobs) retrieves the Cliniko API key securely from Supabase, per clinic.
- Environment variables for the Cliniko API key are only used in non-production scripts (e.g., onboarding, debugging, or local utilities) and are not used in any production or user-facing code paths.
- This ensures secure, scalable, and per-client management of API credentials.
- When onboarding a new clinic, the key is collected and stored in Supabase, never in environment variables for production use.

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

## License
MIT