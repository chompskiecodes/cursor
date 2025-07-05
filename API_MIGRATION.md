# API Migration Guide

## Overview
This guide documents the API response structure changes for voice agent compatibility.

## Changed Fields

### All Endpoints
- Added consistent `success`, `sessionId`, `message`, `error` fields
- Nested data in structured objects instead of flat fields

### Location Resolver
| Old Field | New Field | Notes |
|-----------|-----------|-------|
| `business_id` | `location.id` | Nested in location object |
| `business_name` | `location.name` | Nested in location object |
| `location_resolved` | `resolved` | Simplified name |
| `action_completed` | `resolved` | Unified field |
| `needs_clarification` | `needsClarification` | camelCase |

### Get Practitioners
| Old Field | New Field | Notes |
|-----------|-----------|-------|
| `practitioners` (mixed) | `practitioners` (always objects) | Consistent structure |
| `practitionerNames` | Still available | For backward compatibility |
| `locationName` | `location.name` | Nested in location object |

### Availability Checker
| Old Field | New Field | Notes |
|-----------|-----------|-------|
| `practitioner` (string) | `practitioner` (object) | Full practitioner data |
| `slots` (varied) | `slots` (TimeSlotData) | Consistent slot structure |

### Booking Response
| Old Field | New Field | Notes |
|-----------|-----------|-------|
| `appointmentDetails` | Still included | For compatibility |
| - | `bookingId` | Direct field |
| - | `confirmationNumber` | Direct field |
| - | Structured data objects | Better organization |

## Backward Compatibility

All old fields are maintained during the transition period:
- Old field names still work
- New structure is preferred
- Plan to deprecate old fields in 6 months 