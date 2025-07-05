Voice Booking System - Webhook Functions Guide.md

22.18 KB •783 lines
•
Formatting may be inconsistent from source

# Voice Booking System - Comprehensive Webhook Functions Guide

## Overview

This system provides 10 webhook endpoints designed specifically for ElevenLabs Conversational AI integration. Each webhook follows a strict request/response pattern optimized for voice interactions with medical clinic appointment booking.

## Core Design Principles

1. **Stateless Operations**: Each webhook call is independent
2. **Fast Response Times**: All endpoints respond in <500ms
3. **Voice-First Responses**: Messages are crafted for natural speech
4. **Error Recovery**: Graceful handling with voice-friendly error messages
5. **Sequential Tool Usage**: Tools are designed to be called in specific sequences
6. **Flexible Parameter Handling**: Accepts various parameter formats for voice compatibility

## Webhook Endpoints

### 1. Location Resolution (`POST /location-resolver`)

**Purpose**: Resolves ambiguous location references to specific clinic IDs

**When to Use**:
- ALWAYS when caller mentions ANY location: "main clinic", "city", "Balmain", "your usual place", "downtown", etc.
- Before any booking operations that need a location
- When location context is unclear
- Even when location seems specific (e.g., "City Clinic" still needs resolution)

**Request**:
```json
{
  "locationQuery": "main clinic",
  "sessionId": "session_123",
  "dialedNumber": "0478621276",
  "callerPhone": "0412345678",
  "systemCallerID": "0412345678"
}
```

**Response Types**:

1. **High Confidence Match (score >= 0.8)**:
```json
{
  "success": true,
  "sessionId": "session_123",
  "action_completed": true,
  "needs_clarification": false,
  "message": "I'll book you at City Clinic",
  "business_id": "loc_001",
  "business_name": "City Clinic",
  "confidence": 0.95
}
```

2. **Medium Confidence (0.6 <= score < 0.8)**:
```json
{
  "success": true,
  "sessionId": "session_123",
  "action_completed": false,
  "needs_clarification": true,
  "message": "Did you mean our City Clinic?",
  "options": ["City Clinic"],
  "confidence": 0.65
}
```

3. **Low Confidence (score < 0.6)**:
```json
{
  "success": true,
  "sessionId": "session_123",
  "action_completed": false,
  "needs_clarification": true,
  "message": "We have two locations: City Clinic and Suburban Clinic. Which would you prefer?",
  "options": ["City Clinic", "Suburban Clinic"],
  "confidence": 0.4
}
```

**Important Notes**:
- Uses fuzzy matching with location keywords, previous booking history, and aliases
- Caches caller preferences for future calls
- Returns numeric business_id that MUST be used in all subsequent tools
- When needs_clarification=true, you MUST read the message exactly and use confirm-location

### 2. Confirm Location (`POST /confirm-location`)

**Purpose**: Confirms location selection after clarification

**When to Use**:
- ONLY after location-resolver returns `needs_clarification: true`
- After reading the exact message to the caller
- When you have the caller's response to location options
- NEVER call this without first calling location-resolver

**Request**:
```json
{
  "userResponse": "the city one",
  "options": ["City Clinic", "Suburban Clinic"],
  "sessionId": "session_123",
  "dialedNumber": "0478621276",
  "callerPhone": "0412345678"
}
```

**Response Types**:

1. **Successful Confirmation**:
```json
{
  "success": true,
  "sessionId": "session_123",
  "location_confirmed": true,
  "business_id": "loc_001",
  "business_name": "City Clinic",
  "message": "Perfect! I'll use our City Clinic for your appointment."
}
```

2. **Needs Re-clarification**:
```json
{
  "success": true,
  "sessionId": "session_123",
  "location_confirmed": false,
  "message": "I have two locations: City Clinic and Suburban Clinic. You can say 'first', 'second', or the location name.",
  "options": ["City Clinic", "Suburban Clinic"]
}
```

3. **Called Without Prior Resolution**:
```json
{
  "success": true,
  "location_confirmed": false,
  "message": "I need to check which locations are available first. Let me look that up for you.",
  "action": "need_location_resolver",
  "hint": "Please call location-resolver with the location name first"
}
```

**Response Parsing Logic**:
- Handles: "first", "second", "the city one", "city", partial names
- Updates caller's preferred location in cache
- Falls back gracefully if can't parse response

### 3. Find Next Available (`POST /find-next-available`)

**Purpose**: Finds the earliest available appointment slot across multiple days

**When to Use**:
- Caller asks for "next available", "earliest", "soonest", "first available"
- No specific date mentioned
- Looking for first available across locations/practitioners
- Searching up to maxDays ahead (default 14)

**Request Examples**:

**By Practitioner Only**:
```json
{
  "practitioner": "Brendan",
  "sessionId": "session_123",
  "dialedNumber": "0478621276",
  "maxDays": 14
}
```

**By Service at Location**:
```json
{
  "service": "massage",
  "locationId": "loc_001",
  "locationName": "City Clinic",
  "sessionId": "session_123",
  "dialedNumber": "0478621276"
}
```

**By Practitioner and Service**:
```json
{
  "practitioner": "Cameron",
  "service": "Massage (60 min)",
  "sessionId": "session_123",
  "dialedNumber": "0478621276"
}
```

**Response**:
```json
{
  "success": true,
  "found": true,
  "message": "The next available massage is tomorrow at 2:00 PM with Sarah at our City Clinic.",
  "practitioner": "Sarah Johnson",
  "practitionerId": "prac_002",
  "location": "City Clinic",
  "locationId": "loc_001",
  "service": "Massage (60 min)",
  "serviceId": "srv_001",
  "date": "Tuesday, June 24",
  "time": "2:00 PM",
  "dateISO": "2025-06-24",
  "appointmentStart": "2025-06-24T14:00:00Z",
  "appointmentEnd": "2025-06-24T15:00:00Z",
  "sessionId": "session_123"
}
```

**Not Found Response**:
```json
{
  "success": true,
  "found": false,
  "message": "I couldn't find any available massage appointments in the next 14 days.",
  "sessionId": "session_123"
}
```

**Search Logic**:
1. If practitioner specified → finds their next slot at any location
2. If service + location → finds any practitioner at that location
3. If just service → searches all practitioners at all locations
4. Returns the SINGLE earliest slot found
5. Searches chronologically day by day for efficiency

### 4. Availability Checker (`POST /availability-checker`)

**Purpose**: Check ALL available times on a SPECIFIC date

**When to Use**:
- Caller mentions a specific date: "tomorrow", "Monday", "June 24th", "next Tuesday"
- Showing multiple time slots on one day
- After resolving practitioner and service
- NOT for "next available" requests (use find-next-available instead)

**Request**:
```json
{
  "practitioner": "Cameron",
  "date": "tomorrow",
  "appointmentType": "Massage",
  "business_id": "loc_001",
  "sessionId": "session_123",
  "dialedNumber": "0478621276"
}
```

**Alternative Parameters**:
- `location`: Can be text (will be resolved) or use `business_id`
- `appointmentType`: Service name (fuzzy matched)
- `date`: Natural language date parsing

**Response Types**:

1. **Slots Found**:
```json
{
  "success": true,
  "message": "Cameron has the following times available at City Clinic on Tuesday, June 24: 9:00 AM, 10:00 AM, 2:00 PM, 3:30 PM",
  "practitioner": "Cameron Lockey",
  "location": "City Clinic",
  "date": "Tuesday, June 24, 2025",
  "slots": ["9:00 AM", "10:00 AM", "2:00 PM", "3:30 PM"],
  "totalSlots": 4,
  "sessionId": "session_123"
}
```

2. **No Availability**:
```json
{
  "success": true,
  "message": "I'm sorry, Cameron doesn't have any availability on Tuesday, June 24. Would you like me to check another day?",
  "practitioner": "Cameron Lockey",
  "location": "City Clinic",
  "date": "Tuesday, June 24, 2025",
  "slots": [],
  "totalSlots": 0,
  "sessionId": "session_123"
}
```

3. **Needs Location Clarification**:
```json
{
  "success": true,
  "action_completed": false,
  "needs_clarification": true,
  "message": "Which location would you like to check? We have: City Clinic, Suburban Clinic",
  "options": ["City Clinic", "Suburban Clinic"],
  "sessionId": "session_123"
}
```

**Important Notes**:
- Detects "next available" requests and redirects appropriately
- Handles location resolution inline if needed
- Caches availability for 5 minutes
- Returns ALL slots on the specific date

### 5. Appointment Handler (`POST /appointment-handler`)

**Purpose**: Handles appointment booking, rescheduling, modifications, and cancellations

**When to Use**:
- Creating new appointments (action: "book" or no action)
- Rescheduling existing appointments (action: "reschedule")
- Modifying appointment details (action: "modify")
- Cancelling appointments (action: "cancel")

#### A. Booking New Appointments

**Request**:
```json
{
  "action": "book",
  "sessionId": "session_123",
  "dialedNumber": "0478621276",
  "callerPhone": "0412345678",
  "patientName": "John Smith",
  "patientPhone": "0412345678",
  "practitioner": "Cameron",
  "appointmentType": "Massage (60 min)",
  "appointmentDate": "2025-06-24",
  "appointmentTime": "14:00",
  "business_id": "loc_001",
  "locationId": "loc_001",
  "notes": "First time patient, prefers firm pressure"
}
```

**Response**:
```json
{
  "success": true,
  "message": "Perfect! I've successfully booked your Massage appointment with Cameron Lockey for Tuesday, June 24 at 2:00 PM at our City Clinic.",
  "appointmentDetails": {
    "appointmentId": "apt_123456",
    "practitioner": "Cameron Lockey",
    "service": "Massage (60 min)",
    "date": "Tuesday, June 24, 2025",
    "time": "2:00 PM",
    "location": "City Clinic",
    "patient": "John Smith",
    "confirmationNumber": "apt_123456"
  },
  "sessionId": "session_123"
}
```

#### B. Rescheduling Appointments

**Request**:
```json
{
  "action": "reschedule",
  "sessionId": "session_123",
  "dialedNumber": "0478621276",
  "callerPhone": "0412345678",
  "appointmentId": "apt_123456",
  "currentAppointmentDetails": "my massage tomorrow with Cameron",
  "newDate": "2025-06-25",
  "newTime": "3:00 PM",
  "newPractitioner": null,
  "newAppointmentType": null,
  "notes": "Patient requested reschedule"
}
```

**Response**:
```json
{
  "success": true,
  "message": "Perfect! I've successfully rescheduled your appointment to Wednesday, June 25 at 3:00 PM.",
  "appointmentDetails": {
    "appointmentId": "apt_789012",
    "oldAppointmentId": "apt_123456",
    "practitioner": "Cameron Lockey",
    "date": "Wednesday, June 25, 2025",
    "time": "3:00 PM",
    "confirmationNumber": "apt_789012"
  },
  "sessionId": "session_123"
}
```

**Reschedule Behavior**:
- Creates new appointment first, then cancels old one (atomic operation)
- Can change date, time, practitioner, or service type
- Finds appointment by ID or natural language description
- Validates new slot availability before proceeding

#### C. Modify Action (Redirects to Reschedule)

**Request**:
```json
{
  "action": "modify",
  "sessionId": "session_123",
  "dialedNumber": "0478621276",
  "appointmentId": "apt_123456"
}
```

**Response**:
```json
{
  "success": false,
  "error": "modify_not_implemented",
  "message": "To change your appointment type, I'll need to reschedule your appointment. Please say 'reschedule' and provide the new details.",
  "sessionId": "session_123"
}
```

#### D. Cancel via Appointment Handler

**Request**:
```json
{
  "action": "cancel",
  "sessionId": "session_123",
  "dialedNumber": "0478621276",
  "callerPhone": "0412345678",
  "appointmentId": "apt_123456",
  "notes": "Patient can't make it"
}
```

**Note**: This internally converts to a CancelRequest and routes to the cancel-appointment endpoint

**Critical Format Requirements**:
- `appointmentDate`: YYYY-MM-DD format
- `appointmentTime`: HH:MM in 24-hour format for booking
- `newTime`: H:MM AM/PM format for rescheduling
- `business_id` or `locationId`: Must be the numeric ID from location-resolver
- Service names must be exact matches from practitioner's service list

### 6. Cancel Appointment (`POST /cancel-appointment`)

**Purpose**: Cancels existing appointments with natural language search

**When to Use**:
- Caller says "cancel", "can't make it", "need to cancel"
- Can find by appointment ID or natural description
- Confirms details before cancelling

**Request Examples**:

**With Appointment ID**:
```json
{
  "sessionId": "session_123",
  "dialedNumber": "0478621276",
  "callerPhone": "0412345678",
  "appointmentId": "apt_123456",
  "reason": "Feeling unwell"
}
```

**With Natural Language**:
```json
{
  "sessionId": "session_123",
  "dialedNumber": "0478621276",
  "callerPhone": "0412345678",
  "appointmentDetails": "my massage tomorrow with Cameron",
  "systemCallerID": "0412345678"
}
```

**Response**:
```json
{
  "success": true,
  "message": "I found your Massage appointment with Cameron Lockey on Tuesday, June 24 at 2:00 PM. Your appointment has been successfully cancelled.",
  "sessionId": "session_123"
}
```

**Search Logic**:
1. If appointmentId provided → use directly
2. If appointmentDetails → search by:
   - Caller's phone number
   - Practitioner name
   - Date/time references
   - Service type
3. Confirms found appointment before cancelling
4. Updates database and logs cancellation

### 7. Get Practitioner Services (`POST /get-practitioner-services`)

**Purpose**: Lists services offered by a specific practitioner

**When to Use**:
- Caller mentions practitioner but no service
- "I want to see Dr. Smith" (but for what?)
- Before booking to know available services
- Simplest practitioner info tool

**Request**:
```json
{
  "practitioner": "Cameron",
  "dialedNumber": "0478621276",
  "sessionId": "session_123"
}
```

**Response**:
```json
{
  "success": true,
  "practitioner": "Cameron Lockey",
  "serviceCount": 3,
  "services": ["Massage (30 min)", "Massage (60 min)", "Deep Tissue Massage"],
  "message": "Cameron Lockey offers Massage (30 min), Massage (60 min), and Deep Tissue Massage.",
  "sessionId": "session_123"
}
```

**Error Response**:
```json
{
  "success": false,
  "error": "practitioner_not_found",
  "message": "I couldn't find a practitioner by that name. Could you please tell me the practitioner's full name?",
  "sessionId": "session_123"
}
```

### 8. Get Practitioner Info (`POST /get-practitioner-info`)

**Purpose**: Gets comprehensive practitioner information including services AND locations

**When to Use**:
- "What does Dr. Smith do?"
- "Where does Cameron work?"
- Need both services AND locations
- More comprehensive than get-practitioner-services

**Request**:
```json
{
  "practitioner": "Cameron",
  "dialedNumber": "0478621276",
  "sessionId": "session_123"
}
```

**Response**:
```json
{
  "success": true,
  "practitioner": "Cameron Lockey",
  "services": ["Massage (30 min)", "Massage (60 min)", "Deep Tissue Massage"],
  "locations": ["City Clinic", "Suburban Clinic"],
  "message": "Cameron Lockey offers Massage (30 min), Massage (60 min), and Deep Tissue Massage at our City Clinic and Suburban Clinic locations.",
  "sessionId": "session_123"
}
```

### 9. Get Location Practitioners (`POST /get-location-practitioners`)

**Purpose**: Lists ALL practitioners at a specific location

**When to Use**:
- "Who works at City Clinic?"
- After resolving location with location-resolver
- When caller is flexible about practitioner
- Shows everyone at the location (not availability)

**Request**:
```json
{
  "locationId": "loc_001",
  "locationName": "City Clinic",
  "dialedNumber": "0478621276",
  "sessionId": "session_123"
}
```

**Response**:
```json
{
  "success": true,
  "locationName": "City Clinic",
  "practitioners": [
    {"practitioner_id": "prac_001", "practitioner_name": "Dr. Sarah Smith"},
    {"practitioner_id": "prac_002", "practitioner_name": "Cameron Lockey"},
    {"practitioner_id": "prac_003", "practitioner_name": "Jane Wilson"}
  ],
  "practitionerNames": ["Dr. Sarah Smith", "Cameron Lockey", "Jane Wilson"],
  "message": "At City Clinic, we have Dr. Sarah Smith, Cameron Lockey, and Jane Wilson available.",
  "sessionId": "session_123"
}
```

### 10. Get Available Practitioners (`POST /get-available-practitioners`)

**Purpose**: Shows who has availability at a location on a SPECIFIC date

**When to Use**:
- "Who's available at City Clinic tomorrow?"
- Caller is flexible about practitioner
- Combines location + date availability
- More specific than get-location-practitioners

**Request**:
```json
{
  "locationId": "loc_001",
  "locationName": "City Clinic",
  "date": "tomorrow",
  "dialedNumber": "0478621276",
  "sessionId": "session_123"
}
```

**Response**:
```json
{
  "success": true,
  "locationName": "City Clinic",
  "date": "Tuesday, June 24, 2025",
  "availablePractitioners": [
    {"practitioner_id": "prac_001", "practitioner_name": "Dr. Sarah Smith"},
    {"practitioner_id": "prac_002", "practitioner_name": "Cameron Lockey"}
  ],
  "practitionerNames": ["Dr. Sarah Smith", "Cameron Lockey"],
  "message": "On Tuesday, June 24 at City Clinic, Dr. Sarah Smith and Cameron Lockey have availability.",
  "sessionId": "session_123"
}
```

## Typical Call Flows

### Flow 1: Simple Next Available Booking
```
1. Caller: "I need to book a massage"
2. Agent → find-next-available (service: "massage")
3. Response: "Next available is tomorrow at 2pm with Sarah at City Clinic"
4. Caller: "That works"
5. Agent asks for name
6. Agent → appointment-handler (with all details including locationId)
7. Booking confirmed
```

### Flow 2: Specific Practitioner Booking
```
1. Caller: "I want to see Cameron tomorrow"
2. Agent → get-practitioner-services ("Cameron")
3. Response: Lists services
4. Agent asks which service
5. Agent → availability-checker (practitioner: "Cameron", date: "tomorrow")
6. Response: Lists available times
7. Caller picks time
8. Agent → appointment-handler
9. Booking confirmed
```

### Flow 3: Location-Specific Booking
```
1. Caller: "Book me at your Balmain clinic"
2. Agent → location-resolver ("Balmain clinic")
3. Response: needs_clarification with options
4. Agent reads options exactly
5. Caller chooses
6. Agent → confirm-location
7. Response: business_id confirmed
8. Continue with booking using the business_id
```

### Flow 4: Rescheduling
```
1. Caller: "I need to reschedule my appointment tomorrow"
2. Agent → appointment-handler (action: "reschedule", currentAppointmentDetails: "appointment tomorrow")
3. System finds appointment
4. Agent asks for new date/time
5. Agent → appointment-handler (with newDate, newTime)
6. System creates new appointment, cancels old
7. Confirmation includes new details
```

### Flow 5: Natural Language Cancellation
```
1. Caller: "I need to cancel my massage with Cameron next week"
2. Agent → cancel-appointment (appointmentDetails: "massage with Cameron next week")
3. System finds and confirms appointment details
4. Appointment cancelled
5. Confirmation message sent
```

## Error Handling

All endpoints return consistent error formats:

```json
{
  "success": false,
  "error": "error_code",
  "message": "Human-readable message for the voice agent to speak",
  "sessionId": "session_123"
}
```

### Common Error Codes

| Error Code | Meaning | Common Causes |
|------------|---------|---------------|
| `clinic_not_found` | Invalid dialed number | Wrong phone number in request |
| `practitioner_not_found` | No matching practitioner | Misspelled name, practitioner doesn't exist |
| `service_not_found` | Service not available | Wrong service name, practitioner doesn't offer it |
| `no_availability` | No slots available | Fully booked for requested timeframe |
| `time_not_available` | Specific time slot taken | Someone else booked it first |
| `missing_information` | Required fields missing | Missing patient name, date, etc. |
| `slot_taken` | Appointment no longer available | Race condition - slot booked by another patient |
| `invalid_business_id` | Location ID not valid | Using name instead of ID, wrong clinic |
| `appointment_not_found` | Can't find appointment to cancel/reschedule | Wrong details, already cancelled |
| `booking_too_soon` | Advance notice required | Clinic requires X hours notice |
| `invalid_time_format` | Time format incorrect | Using 12-hour for booking instead of 24-hour |

## Important Implementation Notes

1. **Always resolve location first**: Many operations require a numeric business_id
2. **Service names must be exact**: "Massage" vs "Massage (60 min)" - use exact names from get-practitioner-services
3. **Acupuncture special handling**: Always ask if new or returning patient
   - New: "Acupuncture (Initial)"
   - Returning: "Acupuncture (Follow up)"
4. **Time zones**: All times are handled in clinic's local timezone (usually Australia/Sydney)
5. **Phone validation**: Australian numbers only (10 digits, starting with 02, 03, 04, 07, 08)
6. **Caching**: Availability is cached for 5 minutes to improve performance
7. **Session tracking**: Always pass sessionId for conversation continuity
8. **Reschedule vs Cancel**: Use reschedule action to move appointments (atomic operation)
9. **Time formats**: 
   - Booking: 24-hour format (14:00)
   - Rescheduling: 12-hour format with AM/PM (2:00 PM)
10. **Natural language dates**: System parses "tomorrow", "next Monday", etc.
11. **Fuzzy matching**: Practitioner and service names use fuzzy matching
12. **Location precedence**: business_id takes precedence over location text
13. **Error recovery**: All errors return voice-friendly messages
14. **Availability checking**: Check before booking to avoid failures

## Advanced Features

### Booking Context Cache
- System remembers caller's previous preferences
- Speeds up repeat bookings
- 24-hour retention

### Smart Location Resolution
- Uses previous booking history
- Fuzzy matches location aliases
- Handles "my usual place"

### Natural Language Understanding
- Date parsing: "next Tuesday", "in 2 weeks"
- Time parsing: "2:30 PM", "half past two"
- Relative references: "same time as last week"

### Concurrent Request Handling
- Race condition prevention for slot booking
- Cache invalidation on bookings
- Optimistic locking for appointments

## Testing

Each endpoint includes validation and will return helpful error messages if fields are missing or invalid. The system is designed to guide the voice agent toward successful bookings while handling edge cases gracefully.

### Test Scenarios to Cover
1. Single vs multiple locations
2. Practitioner at multiple locations
3. Service name variations
4. Same-day bookings
5. Advance notice requirements
6. Fully booked scenarios
7. Reschedule conflicts
8. Natural language date/time parsing
9. Phone number validation
10. Session continuity