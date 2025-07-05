## ElevenLabs-Compatible Multi-Location Voice Booking System

**(FastAPI + Supabase + Cliniko API)**

---

### 🔹 Overview

This project implements an AI-powered voice receptionist system using FastAPI and Supabase, integrated with the Cliniko API. It supports multi-location clinics, enabling intelligent location disambiguation, robust validation, and fast, JSON-compliant webhook communication with ElevenLabs' Conversational AI platform.

---

### 🤖 Key Components

1. **Voice Agent (ElevenLabs)**

   * Handles natural language
   * Extracts structured parameters (e.g., practitioner, service, date, location)
   * Validates availability and confirms details
   * Manages clarification, corrections, and conversational flow

2. **Backend API (FastAPI)**

   * Validates structured input
   * Interfaces with Cliniko and Supabase
   * Returns fast, structured JSON responses
   * Logs all interactions
   * Avoids logic branching or conversational handling

---

### 🚫 Core Principle: Keep Python Dumb

All conversational intelligence (clarification, fuzzy matching, assumptions) must reside in the voice agent. The Python API must:

* Only validate, query, and respond
* Return structured success or clear errors
* Never guess, ask clarifying questions, or handle ambiguous intent

---

### 🔧 Implementation Requirements

* **Webhook Protocol:**

  * Standard HTTP POST only
  * No Server-Sent Events (SSE)
  * Respond with **one complete JSON object**
  * Always return in under 500ms (ideal: <300ms)

* **Internal Behavior:**

  * Async allowed internally
  * Caching and parallel processing encouraged
  * Must appear synchronous to ElevenLabs

---

## 🎯 Webhook Architecture & Usage Patterns

The system implements **10 specialized webhook tools** designed for different conversation scenarios:

### **1. Location Resolution Tools**
- **`location_resolver`** - Resolves any location reference to a business_id
- **`confirm_location`** - Confirms location after disambiguation

### **2. Availability & Scheduling Tools**
- **`availability_checker`** - Shows ALL available times on a SPECIFIC date
- **`find_next_available`** - Finds the FIRST/NEXT available appointment across multiple days

### **3. Practitioner Information Tools**
- **`get_practitioner_services`** - Lists services for ONE practitioner
- **`get_practitioner_info`** - Gets EVERYTHING about a practitioner (all services + all locations)
- **`get_location_practitioners`** - Gets all practitioners who work at a specific business
- **`get_available_practitioners`** - Gets practitioners with availability on a specific date at a specific business

### **4. Booking & Management Tools**
- **`appointment_handler`** - Books an appointment with all required details
- **`cancel_appointment`** - Cancels existing appointments

### **Intended Usage Patterns**

#### **Scenario 1: "I want to see Dr. Smith" (Any Location)**
1. `get_practitioner_services` → Shows what services Dr. Smith offers
2. `get_practitioner_info` → Shows all locations where Dr. Smith works
3. `find_next_available` → Finds next available slot across all locations

#### **Scenario 2: "I want to see Dr. Smith at Balmain" (Specific Location)**
1. `location_resolver` → Resolves "Balmain" to business_id
2. `availability_checker` → Shows available times at Balmain on specific date
3. `appointment_handler` → Books the appointment

#### **Scenario 3: "I want a massage" (Service-First)**
1. `find_next_available` → Finds next available massage appointment
2. `appointment_handler` → Books the appointment

#### **Scenario 4: "Who's available at City Clinic tomorrow?" (Location + Date)**
1. `location_resolver` → Resolves "City Clinic" to business_id
2. `get_available_practitioners` → Shows practitioners with availability tomorrow at City Clinic

### **⚠️ Current Implementation Deviations**

**Issue Identified:** The `availability_checker` endpoint has been modified to handle both specific date queries AND general availability queries, which deviates from the original design intent.

**Original Design:**
- `availability_checker` → Specific dates only
- `find_next_available` → General availability
- `get_practitioner_info` → General practitioner information

**Current Implementation:**
- `availability_checker` → Handles both specific dates AND general queries
- This creates confusion and may lead to suboptimal responses

**Recommended Fix:**
- Restore `availability_checker` to handle only specific date queries
- Ensure `find_next_available` is used for general availability searches
- Use `get_practitioner_info` for general practitioner information

---

### 📂 API Endpoints

#### 1. `POST /availability-checker`

**Purpose:** Check practitioner availability
**Expected Time:** <500ms
**Request:**

```json
{
  "practitioner": "Cameron",
  "date": "tomorrow",
  "sessionId": "unique_session_id",
  "dialedNumber": "0478621267",
  "appointmentType": "Massage",
  "location": "City Clinic"
}
```

**Response:**

```json
{
  "success": true,
  "practitioner": "Cameron Lockey",
  "date": "2025-06-24",
  "availability": {
    "City Clinic": {
      "location_id": "loc_001",
      "slots": [
        {"time": "09:00", "service_name": "Massage (60 min)", "duration": 60},
        {"time": "10:00", "service_name": "Massage (60 min)", "duration": 60}
      ],
      "total_slots": 2
    }
  },
  "disambiguation_needed": false,
  "message": "Cameron Lockey has 2 appointments available at City Clinic on Tuesday, June 24.",
  "sessionId": "unique_session_id"
}
```

---

#### 2. `POST /appointment-handler`

**Purpose:** Book, cancel, or modify an appointment
**Expected Time:** <500ms
**Request:**

```json
{
  "action": "book",
  "appointmentType": "Massage (60 min)",
  "callerPhone": "0412345678",
  "bookingFor": "self",
  "patientPhone": "0412345678",
  "patientName": "John Smith",
  "practitioner": "Cameron",
  "appointmentDate": "tomorrow",
  "appointmentTime": "10:00 AM",
  "sessionId": "unique_session_id",
  "dialedNumber": "0478621267",
  "location": "City Clinic",
  "locationId": "loc_001",
  "notes": "First time patient"
}
```

**Response (Success):**

```json
{
  "success": true,
  "message": "Perfect! I've booked your Massage (60 min) appointment with Cameron Lockey at City Clinic on Tuesday, June 24 at 10:00 AM.",
  "appointmentDetails": {
    "appointmentId": "apt_123456",
    "practitionerId": "prac_001",
    "service": "Massage (60 min)",
    "location": "City Clinic",
    "locationId": "loc_001",
    "date": "2025-06-24",
    "time": "10:00 AM",
    "patient": "John Smith",
    "confirmationNumber": "apt_1234"
  },
  "sessionId": "unique_session_id"
}
```

**Response (Error):**

```json
{
  "success": false,
  "error": "slot_no_longer_available",
  "message": "Sorry, that time was just booked. Would 3:00 PM work instead?",
  "sessionId": "unique_session_id"
}
```

---

#### 3. `POST /location-resolver`

**Purpose:** Resolve vague or user-defined location references
**Expected Time:** <300ms
**Request:**

```json
{
  "locationQuery": "main clinic",
  "practitionerId": "prac_001",
  "sessionId": "unique_session_id",
  "dialedNumber": "0478621267"
}
```

**Response:**

```json
{
  "success": true,
  "suggested_location": "loc_001",
  "message": "That's our City Clinic location at 123 Main St.",
  "sessionId": "unique_session_id"
}
```

---

### ❗ Standard Error Format

All errors follow this shape:

```json
{
  "success": false,
  "error": "error_code",
  "message": "Human-readable explanation",
  "sessionId": "unique_session_id"
}
```

**Example error codes:**

* `clinic_not_found`
* `practitioner_not_found`
* `service_not_found`
* `location_required`
* `time_not_available`
* `booking_failed`

---

### ⚙️ Performance Optimization

* **Availability Caching**: TTL 5 minutes, invalidated on booking, reduces API calls by \~80%
* **Parallel Processing**: Multi-location queries run in parallel
* **Connection Pooling**: 5–20 concurrent DB connections

---

### 🧪 Installation & Testing

1. **Install Dependencies:**

```bash
pip install -r requirements.txt
```

2. **Set Environment Variables:**

```env
DATABASE_URL=postgresql://user:pass@localhost/voice_booking
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your-supabase-key
API_KEY=your-api-key
ENVIRONMENT=production
DEFAULT_TIMEZONE=Australia/Sydney
AVAILABILITY_CACHE_TTL=300
```

3. **Run Locally:**

```bash
uvicorn main:app --host 0.0.0.0 --port 8000
```

4. **Run Compatibility Test:**

```bash
python test_elevenlabs.py
```

---

### 🔌 ElevenLabs Tool Config

**Tool: availability\_checker**

* URL: `https://your-domain.com/availability-checker`
* Method: POST
* Inputs: `practitioner`, `date`, `sessionId`, `dialedNumber`, `appointmentType`, `location`

**Tool: appointment\_handler**

* URL: `https://your-domain.com/appointment-handler`
* Method: POST
* Inputs: As described above

**Tool: location\_resolver**

* URL: `https://your-domain.com/location-resolver`
* Method: POST
* Inputs: `locationQuery`, `practitionerId`, `sessionId`, `dialedNumber`

---

### 🏥 Cliniko API Integration Notes

**Critical Learnings from Testing:**

#### 1. **Date Format Requirements**
- **Available Times Endpoint**: Use simple date format `YYYY-MM-DD` for `from` and `to` parameters
  ```python
  # ✅ CORRECT
  params = {
      "from": "2025-07-02",
      "to": "2025-07-02",
      "page": 1,
      "per_page": 100
  }
  
  # ❌ WRONG - Don't use datetime with timezone
  params = {
      "from": "2025-07-02T00:00:00Z",
      "to": "2025-07-02T23:59:59Z"
  }
  ```

#### 2. **Appointment Creation**
- **Appointment Start/End**: Must be in UTC with ISO 8601 format
  ```python
  # ✅ CORRECT - Convert local time to UTC
  appointment_start = local_time.astimezone(ZoneInfo("UTC")).isoformat()
  appointment_end = (local_time + timedelta(minutes=30)).astimezone(ZoneInfo("UTC")).isoformat()
  ```

#### 3. **Common API Errors & Solutions**

| Error | Cause | Solution |
|-------|-------|----------|
| `"Invalid time frame definition"` | Wrong date format for available_times | Use `YYYY-MM-DD` format only |
| `"Invalid time frame definition"` | Date range > 7 days | Limit range to 7 days or less |
| `"Invalid time frame definition"` | Past dates | Use future dates only |
| `"No available times"` | Practitioner not available | Check practitioner schedule in Cliniko |
| `"booking_too_soon"` | Advance notice requirement | Book further in advance |

#### 4. **Testing Direct API Calls**
Use this PowerShell pattern for direct testing:

```powershell
# Set credentials
$apiKey = "your-api-key"
$shard = "au4"
$baseUrl = "https://api.$shard.cliniko.com/v1"
$base64Auth = [Convert]::ToBase64String([Text.Encoding]::ASCII.GetBytes("${apiKey}:"))

$headers = @{
    "Authorization" = "Basic $base64Auth"
    "Accept" = "application/json"
    "Content-Type" = "application/json"
}

# Get available times
$availableTimesUrl = "$baseUrl/businesses/{business_id}/practitioners/{practitioner_id}/appointment_types/{appointment_type_id}/available_times?from=2025-07-02&to=2025-07-02"
$availableTimes = Invoke-RestMethod -Uri $availableTimesUrl -Headers $headers -Method Get
```

#### 5. **Required IDs for API Calls**
- **Business ID**: Primary clinic location
- **Practitioner ID**: Specific practitioner (e.g., Brendan, Chomps)
- **Appointment Type ID**: Service type (e.g., Massage, Consultation)
- **Patient ID**: Created automatically or retrieved from existing

#### 6. **Timezone Handling**
- Cliniko API expects all times in UTC
- Convert local clinic time to UTC before sending
- Account for daylight saving time changes
- Use `zoneinfo.ZoneInfo` for proper timezone conversion

#### 7. **Rate Limiting**
- Cliniko API has rate limits (typically 1000 requests/hour)
- Implement exponential backoff for retries
- Cache availability data to reduce API calls

---

### 🚨 Troubleshooting

**If bookings fail with "time_not_available":**
1. Check practitioner availability in Cliniko dashboard
2. Verify appointment type is enabled for online bookings
3. Confirm business/practitioner/appointment type IDs are correct
4. Test with direct API call using PowerShell script above

**If you get "Invalid time frame definition":**
1. Use simple date format (`YYYY-MM-DD`) for available_times
2. Ensure date range is ≤ 7 days
3. Use future dates only
4. Check that all IDs exist and are linked correctly

**If authentication fails:**
1. Verify API key format: `MS0-{key}-{shard}`
2. Check shard is correct (e.g., `au4` for Australia)
3. Ensure API key has proper permissions in Cliniko

---

## Timezone Handling Rules

### Timezone Strategy

- **UTC everywhere internally:** All times in the database and all interactions with the Cliniko API use UTC. This ensures consistency and avoids timezone-related bugs.
- **Clinic-specific timezones:** Each clinic can have its own timezone, which is used for all user-facing times and communications.
- **Conversion only at boundaries:** Times are only converted to the clinic's local timezone when displaying to users or callers. All internal logic and storage remains in UTC.
- **Proper fallbacks:** If a clinic's timezone is missing or invalid, the system defaults to 'Australia/Sydney' to ensure robust operation.

- **All times sent to Cliniko are in UTC.**
  - The backend ensures that any appointment, availability, or booking data sent to the Cliniko API is always in UTC, as required by Cliniko.

- **All times presented to callers/users are in the clinic's local timezone.**
  - Any time spoken to a caller, shown in a confirmation, or displayed in a user-facing message is always converted to the clinic's local timezone.

- **Centralized Timezone Handling:**
  - The codebase uses a centralized helper (`get_clinic_timezone`) for robust timezone validation and conversion.
  - All timezone conversions use Python's `ZoneInfo` and the app's default timezone as a fallback if a clinic's timezone is invalid or missing.
  - Utility functions for timezone handling are located in `tools/shared.py`.

- **Test Files:**
  - Test files may use hardcoded timezones (e.g., "Australia/Sydney") for consistent and repeatable testing.

- **Developer Guidance:**
  - Always use `get_clinic_timezone(clinic)` when you need a clinic's timezone as a `ZoneInfo` object.
  - Always use `convert_utc_to_local()` for converting UTC times to local times for display.
  - Never pass a timezone string directly to a function expecting a `ZoneInfo` object—use the helper instead.

- **Summary:**
  - All API interactions with Cliniko: **UTC**
  - All user/caller-facing times: **Clinic Local Timezone**
  - All conversions: **Centralized, validated, and robust**

---

## 🛠️ Webhook Response Structure & Migration (2025)

All API endpoints now return **standardized, nested response objects** for maximum clarity and voice agent compatibility. Flat/legacy fields have been removed. See `API_MIGRATION.md` for a full mapping of old to new fields.

### Key Webhook Response Principles
- All responses use a consistent structure: `success`, `sessionId`, `message`, and (if error) `error`.
- Data is always nested in objects (e.g., `location`, `practitioner`, `service`, `timeSlot`).
- No legacy/flat fields are present in the response.
- All lists (e.g., practitioners, services) are lists of objects, not strings.
- Error responses always use the same shape.

### Example: Location Resolver
```json
{
  "success": true,
  "sessionId": "session_123",
  "message": "That's our City Clinic location at 123 Main St.",
  "resolved": true,
  "needsClarification": false,
  "location": {
    "id": "loc_001",
    "name": "City Clinic"
  },
  "confidence": 0.98
}
```

### Example: Practitioners List
```json
{
  "success": true,
  "sessionId": "session_123",
  "message": "Found 2 available practitioners.",
  "location": {
    "id": "loc_001",
    "name": "City Clinic"
  },
  "practitioners": [
    {"id": "prac_001", "name": "Cameron Lockey", "firstName": "Cameron", "servicesCount": 3},
    {"id": "prac_002", "name": "Alex Smith", "firstName": "Alex", "servicesCount": 2}
  ],
  "date": "2025-06-24"
}
```

### Example: Booking Response
```json
{
  "success": true,
  "sessionId": "session_123",
  "message": "Perfect! I've booked your Massage (60 min) appointment with Cameron Lockey at City Clinic on Tuesday, June 24 at 10:00 AM.",
  "bookingId": "apt_123456",
  "confirmationNumber": "APT-123456",
  "practitioner": {"id": "prac_001", "name": "Cameron Lockey", "firstName": "Cameron"},
  "service": {"id": "srv_001", "name": "Massage (60 min)", "duration": 60},
  "location": {"id": "loc_001", "name": "City Clinic"},
  "timeSlot": {"date": "2025-06-24", "time": "10:00", "displayTime": "10:00 AM"},
  "patientName": "John Smith"
}
```

### Example: Error Response
```json
{
  "success": false,
  "error": "slot_no_longer_available",
  "message": "Sorry, that time was just booked. Would 3:00 PM work instead?",
  "sessionId": "unique_session_id"
}
```

### Developer Note: Date Handling in Sync Scripts

When writing sync or cleanup scripts that interact with the database, always ensure that date strings (e.g., '2025-06-05') are converted to `datetime.date` objects before passing them to SQL queries. Passing strings directly will cause type errors in asyncpg or psycopg2 (e.g., "expected a datetime.date or datetime.datetime instance, got 'str'").

**Example:**

```python
from datetime import datetime
from_date_obj = datetime.strptime(from_date, "%Y-%m-%d").date()
to_date_obj = datetime.strptime(to_date, "%Y-%m-%d").date()
```

Use these objects in your queries, not the original strings.

This is especially important for appointment deletion or cleanup logic after syncing with Cliniko.

---

### 🧑‍⚕️ Practitioner Name Matching Logic

When the backend receives a practitioner name (e.g., "Dr. Smith", "Brendan", "Brendan Smith"), it uses a comprehensive matching algorithm to resolve the correct practitioner:

- **First name only** (e.g., "Brendan")
- **Last name only** (e.g., "Smith")
- **Prefix + last name** (e.g., "Dr. Smith")
- **First and last name** (e.g., "Brendan Smith")
- **Fuzzy and substring matches** for all of the above

The system parses the input and calculates a match score for each practitioner in the clinic. If a match is found above a threshold, it is used; otherwise, the system may ask for clarification.

This ensures robust handling of natural language input from the voice agent, supporting a wide range of user queries.

---

### 🛠️ Developer Note: Using match_practitioner

The `match_practitioner` function returns a result dictionary with a `matches` key (a list of practitioner dicts), not a single practitioner dict. You must extract the practitioner from the `matches` list before accessing fields like `full_name`, `first_name`, or `practitioner_id`.

**Example:**

```python
practitioner_result = await match_practitioner(clinic_id, requested_name, pool)
if not practitioner_result or not practitioner_result.get("matches"):
    # handle error
practitioner = practitioner_result["matches"][0]
# Now you can use practitioner['full_name'], etc.
```

Do **not** use the result of `match_practitioner` directly as a practitioner dict.