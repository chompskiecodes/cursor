# ElevenLabs Tool Configuration: Find Next Available

Add this tool to your ElevenLabs agent:

```json
{
  "name": "find-next-available",
  "description": "Find the next available appointment for a practitioner across all locations OR for a service type across all practitioners/locations. Use for 'next available' or 'earliest available' requests.",
  "type": "webhook",
  "url": "https://your-api-domain.com/find-next-available",
  "method": "POST",
  "headers": {
    "X-API-Key": "your-api-key-here"
  },
  "parameters": [
    {
      "name": "practitioner",
      "type": "string",
      "description": "Practitioner name (use this OR service, not both)",
      "required": false
    },
    {
      "name": "service",
      "type": "string",
      "description": "Service type like 'massage' or 'consultation' (use this OR practitioner)",
      "required": false
    },
    {
      "name": "locationId",
      "type": "string",
      "description": "Optional: specific location ID to search within",
      "required": false
    },
    {
      "name": "locationName",
      "type": "string",
      "description": "Location name for natural speech (if locationId provided)",
      "required": false
    },
    {
      "name": "maxDays",
      "type": "number",
      "description": "How many days ahead to search (default 14)",
      "required": false,
      "default": 14
    },
    {
      "name": "sessionId",
      "type": "string",
      "description": "Current conversation session ID",
      "required": true
    },
    {
      "name": "dialedNumber",
      "type": "string",
      "description": "The clinic phone number that was dialed",
      "required": true
    }
  ],
  "response_handling": {
    "wait_for_response": true,
    "timeout": 10000
  }
}
```

## Usage Examples for the Agent

### Example 1: Next Available Practitioner
```
Caller: "When's Brendan next available?"
Tool Call: {
  "practitioner": "Brendan",
  "sessionId": "...",
  "dialedNumber": "..."
}
Response: "The next available appointment with Brendan is Thursday at 2pm at our City location."
```

### Example 2: Next Available Service
```
Caller: "I need the next available massage"
Tool Call: {
  "service": "massage",
  "sessionId": "...",
  "dialedNumber": "..."
}
Response: "The next available massage is tomorrow at 10am with Sarah at our Burwood location."
```

### Example 3: Service at Specific Location
```
Caller: "When's the next massage at your Parramatta clinic?"
[First resolve location with location-resolver]
Tool Call: {
  "service": "massage",
  "locationId": "abc123",
  "locationName": "Parramatta",
  "sessionId": "...",
  "dialedNumber": "..."
}
Response: "The next available massage at Parramatta is Friday at 3pm with Michael."
```

## Key Points

- Use EITHER `practitioner` OR `service`, not both
- If location matters, resolve it first with location-resolver
- The tool returns all details needed for booking (practitionerId, locationId, serviceId, time)
- If nothing found within maxDays, it tells you clearly
- Always leads to a booking opportunity: "Would you like to book that?"