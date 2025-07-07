# Granular Architecture: Voice Booking System

---

> For setup, installation, and high-level usage, see [README.md](./readme.md)

---

## Technical Overview

- All endpoints require API key authentication.
- All appointment/availability checks require practitioner, business (location), and treatment type.
- All times are UTC internally; user-facing times are in the clinic's local timezone.
- Caching, parallel processing, and session-based rejected slot tracking are implemented for performance and user experience.

---

## Session-Based Rejected Slot Tracking

- The backend uses a Supabase table (`session_rejected_slots`) to persist rejected slots per session.
- When a user rejects offered slots, those slots are stored and not offered again in the same session.
- If the user changes search criteria or books, the rejected slots are reset for that session.
- This logic is fully backend-managed and does not require the voice agent to track state.
- See [README.md](./readme.md#session-based-rejected-slot-tracking) for a user-facing summary.

---

## Endpoint & Router Reference

(Keep all existing endpoint, data flow, and technical details as in the current doc, but remove high-level usage/setup info.)

[...existing endpoint and technical content remains unchanged...]

## tools/location_router.py

### Overview
This router provides endpoints for resolving, confirming, and listing locations, as well as retrieving practitioners at a location. All endpoints require API key authentication.

---

### 1. `/location-resolver` (POST)
**Purpose:** Resolve ambiguous or partial location references from the user, returning either a resolved location or clarification options.

**Process:**
1. Logs the incoming request payload.
2. Looks up the clinic using the dialed number.
3. Triggers a background sync if needed.
4. Uses the LocationResolver to resolve the location query.
5. If a high-confidence match is found, returns the resolved location.
6. If multiple matches or ambiguity, returns clarification options.
7. If no match, returns a message requesting more specificity.
8. Returns a structured `LocationResolverResponse`.

**Requirements:**
- Location query and dialed number must be provided.
- Returns a structured response with resolved location or clarification options.

**Order of Operations:**
1. Log request
2. Lookup clinic
3. Trigger sync
4. Resolve location
5. Return structured response

---

### 2. `/confirm-location` (POST)
**Purpose:** Confirm the user's location choice from a set of options, handling natural language and index-based responses.

**Process:**
1. Parses the request for user response, options, session ID, dialed number, and caller phone.
2. If no options are provided, returns a message guiding the agent to use the location resolver first.
3. Attempts to match the user response to an option (by index, name, or partial match).
4. If a match is found, resolves the location to a business ID and updates the user's booking context in cache.
5. Returns a structured response confirming the location, or requests clarification if the response is ambiguous.

**Requirements:**
- Options and user response must be provided.
- Returns a structured response confirming the location or requesting clarification.

**Order of Operations:**
1. Parse request
2. Validate options
3. Match user response
4. Resolve location and update context
5. Return structured response

---

### 3. `/get-location-practitioners` (POST)
**Purpose:** Retrieve all practitioners who work at a specific location.

**Process:**
1. Parses the request for location ID, location name, dialed number, and session ID.
2. Looks up the clinic using the dialed number.
3. Queries the database for practitioners at the specified location.
4. Formats a message listing the practitioners available at the location.
5. Returns a structured response with practitioner details and a message.

**Requirements:**
- Location ID and dialed number must be provided.
- Returns a structured response with practitioners and a message.

**Order of Operations:**
1. Parse request
2. Lookup clinic
3. Query practitioners at location
4. Format and return structured response

---

## tools/availability_router.py

### Overview
This router provides endpoints for checking practitioner and service availability, finding available practitioners, and resolving next available appointment slots. All endpoints require API key authentication.

---

### 1. `/availability-checker` (POST)
**Purpose:** Check availability for a specific practitioner (and optionally service/location) on a given date, with support for location disambiguation and next-available logic.

**Process:**
1. Logs the incoming request payload.
2. Looks up the clinic using the dialed number.
3. Triggers a background sync if needed.
4. Matches the practitioner and retrieves their services.
5. Resolves the location (business) using business_id, location text, or defaults.
6. If multiple locations exist and none is specified, returns a clarification response.
7. Detects "next available" requests and searches up to 30 days ahead for the earliest slot.
8. Returns a structured response with availability, or a clarification/error message if needed.

**Requirements:**
- Practitioner name and dialed number must be provided.
- Returns a structured response with availability or clarification options.

**Order of Operations:**
1. Log request
2. Lookup clinic
3. Trigger sync
4. Match practitioner
5. Get services
6. Resolve location
7. Check for next-available logic
8. Return structured response

---

### 2. `/get-available-practitioners` (POST)
**Purpose:** Retrieve all practitioners with availability at a specific location on a given date.

**Process:**
1. Parses the request for business_id, date, dialed number, and session ID.
2. Looks up the clinic using the dialed number.
3. Parses the date and initializes the Cliniko API.
4. Queries all practitioners at the location.
5. Checks availability for each practitioner (using cache and Cliniko as needed).
6. Filters out practitioners with no available slots or recent failed booking attempts.
7. Returns a structured response listing available practitioners, the date, and location.

**Requirements:**
- Business_id and dialed number must be provided.
- Returns a structured response with available practitioners, date, and location.

**Order of Operations:**
1. Parse request
2. Lookup clinic
3. Parse date
4. Query practitioners
5. Check/filter availability
6. Return structured response

---

### 3. `/find-next-available` (POST)
**Purpose:** Find the next available appointment slot for a given practitioner or service, optionally filtered by location, searching up to a configurable number of days ahead.

**Process:**
1. Parses the request for service, practitioner, location, max days, dialed number, and session ID.
2. Looks up the clinic using the dialed number.
3. Builds search criteria based on practitioner, service, and location.
4. For each day up to max_days, checks availability for each practitioner/location combination.
5. Uses cache and Cliniko as needed, filtering out recently failed slots.
6. Returns the earliest available slot found, or a message if none are available.
7. Formats the response with slot, practitioner, and location details.

**Requirements:**
- Practitioner or service name and dialed number must be provided.
- Returns a structured response with the next available slot or a not-found message.

**Order of Operations:**
1. Parse request
2. Lookup clinic
3. Build search criteria
4. Search for availability (up to max_days)
5. Return structured response

---

## tools/booking_router.py

### Overview
This router handles all booking-related endpoints, including appointment creation, modification, rescheduling, and cancellation. All endpoints require API key authentication.

---

### 1. `/appointment-handler` (POST)
**Purpose:** Main entry point for booking, modifying, rescheduling, or cancelling appointments. Handles both structured BookingRequest and direct JSON payloads from ElevenLabs.

**Process:**
1. Logs the incoming request payload for auditing/debugging.
2. Determines the action (book, modify, reschedule, cancel) from the request.
3. For booking:
   - Validates required fields (patient, practitioner, service, date, time, location).
   - Looks up or creates the patient in Cliniko.
   - Matches practitioner and service.
   - Finds the business/location.
   - Parses and validates date/time, converts to UTC.
   - Creates the appointment in Cliniko and saves to the local DB.
   - Logs the booking and invalidates the cache.
   - Returns a structured `BookingResponse` with all details.
4. For modification/reschedule/cancel, routes to the appropriate handler.
5. Handles errors with standardized error responses.

**Requirements:**
- Request must include all required booking fields.
- Handles both BookingRequest model and raw JSON payloads.
- Returns a consistent, structured response for all outcomes.

**Order of Operations:**
1. Log request
2. Determine action
3. Validate and process booking
4. Lookup/create patient
5. Match practitioner/service
6. Find business/location
7. Parse/validate date/time
8. Create appointment
9. Save/log/invalidate cache
10. Return structured response

---

### 2. `/cancel-appointment` (POST)
**Purpose:** Cancel an existing appointment, either by ID or by searching for details.

**Process:**
1. Logs the incoming request payload.
2. Looks up the clinic by dialed number. If not found, returns an error response.
3. If appointment ID is not provided, searches for the appointment by details (practitioner, date, time, etc.).
4. Cancels the appointment in Cliniko and updates the local DB.
5. Logs the cancellation.
6. Returns a confirmation message or error response.

**Requirements:**
- Request must include enough information to identify the appointment.
- Returns a structured response indicating success or failure.

**Order of Operations:**
1. Log request
2. Lookup clinic
3. Find appointment (if needed)
4. Cancel in Cliniko
5. Update DB/log
6. Return structured response

---

## tools/practitioner_router.py

### Overview
This router provides endpoints for retrieving practitioner information, their services, and their association with locations. All endpoints require API key authentication.

---

### 1. `/get-practitioner-services` (POST)
**Purpose:** Retrieve the list of services offered by a specific practitioner, optionally filtered by location.

**Process:**
1. Parses the incoming request for practitioner name, location ID (optional), dialed number, and session ID.
2. Looks up the clinic using the dialed number.
3. Matches the practitioner by name within the clinic.
4. Queries the database for services offered by the practitioner, filtered by location if provided.
5. Formats the response to include the list of services, a default service, and a message suitable for voice agents.
6. Handles cases where no services or only one service is found, adjusting the message accordingly.

**Requirements:**
- Practitioner name and dialed number must be provided.
- Returns a structured response with service names, count, and a message.

**Order of Operations:**
1. Parse request
2. Lookup clinic
3. Match practitioner
4. Query services (with/without location filter)
5. Format and return structured response

---

### 2. `/get-practitioner-info` (POST)
**Purpose:** Retrieve comprehensive information about a practitioner, including all services and locations they are associated with.

**Process:**
1. Parses the request for practitioner name, dialed number, and session ID.
2. Looks up the clinic using the dialed number.
3. Matches the practitioner by name within the clinic.
4. Queries the database for all services and locations associated with the practitioner.
5. Formats a comprehensive message summarizing the practitioner's offerings and locations.
6. Returns a structured response with practitioner details, services, locations, and a message.

**Requirements:**
- Practitioner name and dialed number must be provided.
- Returns a structured response with practitioner, services, locations, and a message.

**Order of Operations:**
1. Parse request
2. Lookup clinic
3. Match practitioner
4. Query all services and locations
5. Format and return structured response

---

### 3. `/get-location-practitioners` (POST)
**Purpose:** Retrieve all practitioners available at a specific location.

**Process:**
1. Parses the request for business_id and session ID.
2. Looks up the location name using the business_id.
3. Queries the database for all practitioners associated with the location.
4. Formats the response to include practitioner details and a message suitable for voice agents.
5. Handles cases where no practitioners are found, returning a standardized error response.

**Requirements:**
- Business_id must be provided.
- Returns a structured response with practitioners, location, and a message.

**Order of Operations:**
1. Parse request
2. Lookup location
3. Query practitioners at location
4. Format and return structured response

---

## tools/timezone_utils.py

### Overview
This module centralizes all timezone handling logic for the voice booking system. It provides robust utilities for converting, parsing, and formatting datetimes between UTC and local clinic timezones, ensuring consistent and user-friendly time handling across all endpoints.

---

### Key Functions

- **ensure_utc(dt: datetime) -> datetime**
  - Ensures a datetime is in UTC. Naive datetimes are assumed to be in the default timezone (Australia/Sydney) and converted to UTC.
  - Used to standardize all datetimes before storage or API calls.

- **ensure_aware(dt: datetime, timezone: ZoneInfo) -> datetime**
  - Ensures a datetime is timezone-aware, assigning the provided timezone if naive.

- **parse_cliniko_time(time_str: str) -> datetime**
  - Parses a time string from the Cliniko API, handling both 'Z' (UTC) and offset formats. Returns a UTC datetime.
  - Used for ingesting appointment and availability times from Cliniko.

- **local_to_utc(local_dt: datetime, timezone: ZoneInfo) -> datetime**
  - Converts a local (timezone-aware or naive) datetime to UTC.

- **utc_to_local(utc_dt: datetime, timezone: ZoneInfo = DEFAULT_TZ) -> datetime**
  - Converts a UTC datetime to the specified local timezone (default: Australia/Sydney).

- **combine_date_time_local(date_obj: date, hour: int, minute: int, timezone: ZoneInfo) -> datetime**
  - Combines a date and time (hour, minute) in a local timezone, returning a UTC datetime.
  - Used for constructing appointment datetimes from user input.

- **format_for_display(dt: datetime, timezone: ZoneInfo = DEFAULT_TZ) -> str**
  - Formats a datetime for user display in local time (e.g., '9:30 AM').

- **format_date_for_display(dt: datetime, timezone: ZoneInfo = DEFAULT_TZ) -> str**
  - Formats a date for user display in local time (e.g., 'Monday, January 1, 2024').

- **get_clinic_timezone(clinic) -> ZoneInfo**
  - Retrieves the timezone for a clinic object, with robust fallback to the default timezone.
  - Used throughout the system to ensure all time calculations are clinic-local.

- **convert_utc_to_local(utc_time_str: str, timezone: Union[str, ZoneInfo, None] = None) -> datetime**
  - Converts a UTC time string to a local timezone-aware datetime.
  - Used for formatting and presenting times to users.

- **format_time_for_voice(dt: datetime) -> str**
  - Formats a datetime for voice agent responses (e.g., '9:30 AM').

---

### Usage
- All routers and booking logic use these utilities to ensure:
  - Consistent conversion between UTC (for storage/API) and local time (for user display).
  - Robust handling of naive datetimes and timezones from various sources (user input, Cliniko API, database).
  - User-facing messages always present times in the correct local timezone for the clinic.

---

## Cliniko API Integration: Webhook-by-Webhook Requirements & Limitations

This section details, for each webhook, the exact Cliniko API requirements, data flows, field mappings, limitations, and error/edge case handling. Use this as a reference for integration, debugging, and future maintenance.

---

### 1. `/availability-checker`
**Purpose:** Checks if a specific practitioner is available for a given appointment type at a specific location and date.

**Cliniko API Endpoints Used:**
- `GET /practitioners`
- `GET /businesses`
- `GET /appointment_types`
- `GET /practitioners/:id/availability`

**Data Flow & Field Mapping:**
- Input fields: `practitioner`, `appointmentType`, `location`, `date`, `dialedNumber`, `sessionId`
- Practitioner, appointment type, and business are resolved by name → ID using the respective endpoints.
- Availability is checked by calling `/practitioners/:id/availability` with `business_id`, `appointment_type_id`, and date range.

**Limitations:**
- Can only query one practitioner/business/type at a time.
- Must loop for multiple practitioners or days.
- Rate limits apply (60 req/min typical).
- Data may change between check and booking.

**Edge Cases:**
- Practitioner/type/location not found → error.
- No slots → return no availability message.
- Rate limit hit → retry or inform user.

**Example API Request:**
```
GET /practitioners/12345/availability?business_id=6789&appointment_type_id=1111&from=2024-07-01&to=2024-07-01
Authorization: Bearer <API_KEY>
```

---

### 2. `/get-available-practitioners`
**Purpose:** Lists all practitioners with availability at a location on a given date.

**Cliniko API Endpoints Used:**
- `GET /businesses/:id/practitioners`
- `GET /practitioners/:id/availability`

**Data Flow:**
- Input: `business_id`, `date`, `dialedNumber`, etc.
- Get all practitioners for the business.
- For each, check availability as above.

**Limitations:**
- Must loop over each practitioner.
- Rate limits apply.

**Edge Cases:**
- No practitioners found → error.
- No availability → return message.

---

### 3. `/find-next-available`
**Purpose:** Finds the next available slot for a practitioner or service, optionally filtered by location.

**Cliniko API Endpoints Used:**
- Same as above.

**Data Flow:**
- Input: `practitioner`, `service`, `business_id`, `maxDays`, etc.
- Build search criteria, loop over days/practitioners/locations.
- Stop at first available slot.

**Limitations:**
- No bulk search; must loop.
- Rate limits apply.

**Edge Cases:**
- No slots in window → return not found message.

---

### 4. `/appointment-handler` (BOOK, MODIFY, RESCHEDULE)
**Purpose:** Books, modifies, or reschedules appointments.

**Cliniko API Endpoints Used:**
- `POST /appointments`
- `PUT /appointments/:id`
- `GET /patients`
- `POST /patients`

**Data Flow:**
- Input: patient/practitioner/service/location/date/time.
- Lookup or create patient.
- Book appointment with all required IDs and times.
- For reschedule, update appointment.

**Limitations:**
- Slot must be available at booking time.
- Double-booking not allowed.
- Patient must exist (create if not).

**Edge Cases:**
- Slot taken between check and booking → error.
- Patient not found → create.
- API key permission errors.

**Example API Request:**
```
POST /appointments
Authorization: Bearer <API_KEY>
{
  "patient_id": "...",
  "practitioner_id": "...",
  "appointment_type_id": "...",
  "business_id": "...",
  "start_time": "2024-07-01T09:00:00Z",
  "end_time": "2024-07-01T09:30:00Z"
}
```

---

### 5. `/cancel-appointment`
**Purpose:** Cancels an appointment by ID.

**Cliniko API Endpoints Used:**
- `DELETE /appointments/:id`

**Data Flow:**
- Input: `appointmentId` (must exist).
- Call delete endpoint.

**Limitations:**
- Appointment must exist and not already be cancelled/completed.

**Edge Cases:**
- Not found or already cancelled → error.

---

### 6. `/get-practitioner-services`
**Purpose:** Lists services offered by a practitioner, optionally filtered by location.

**Cliniko API Endpoints Used:**
- `GET /practitioners/:id/appointment_types`

**Data Flow:**
- Input: `practitioner`, `business_id`, etc.
- Lookup practitioner, get their appointment types.
- Filter by location if needed.

**Limitations:**
- Not all services available at all locations.

**Edge Cases:**
- Practitioner not found → error.
- No services → return message.

---

### 7. `/get-practitioner-info`
**Purpose:** Returns comprehensive info about a practitioner (services, locations).

**Cliniko API Endpoints Used:**
- `GET /practitioners/:id`
- `GET /practitioners/:id/appointment_types`
- `GET /practitioners/:id/businesses`

**Data Flow:**
- Input: `practitioner`, etc.
- Lookup practitioner, get all associations.

**Limitations:**
- Data may be stale if cached.

**Edge Cases:**
- Practitioner not found → error.

---

### 8. `/get-location-practitioners`
**Purpose:** Lists all practitioners at a location.

**Cliniko API Endpoints Used:**
- `GET /businesses/:id/practitioners`

**Data Flow:**
- Input: `business_id`, etc.
- Lookup business, get practitioners.

**Limitations:**
- Not all practitioners work at all locations.

**Edge Cases:**
- Location not found → error.
- No practitioners → return message.

---

### 9. `/location-resolver`
**Purpose:** Resolves ambiguous location references to a business.

**Cliniko API Endpoints Used:**
- `GET /businesses`

**Data Flow:**
- Input: `locationQuery`, etc.
- Fuzzy match against business names.

**Limitations:**
- Names must match or require fuzzy logic.

**Edge Cases:**
- No match → return clarification options or error.

---

### 10. `/confirm-location`
**Purpose:** Confirms a user's location choice from options.

**Cliniko API Endpoints Used:**
- `GET /businesses`

**Data Flow:**
- Input: `userResponse`, `options`, etc.
- Match user response to business name.

**Limitations:**
- User input may be ambiguous; must handle partial matches.

**Edge Cases:**
- No match → ask for clarification.

---

**General API Key & Security Notes:**
- All requests require `Authorization: Bearer <API_KEY>`.
- API key must have access to all relevant data.
- Rate limits apply (60 req/min typical).
- All times are UTC in API; convert as needed.

---

*Continue this process for each router and webhook endpoint in the system for a complete granular architecture.* 