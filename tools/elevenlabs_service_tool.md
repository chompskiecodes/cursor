# ElevenLabs Tool: Get Practitioner Services

Add this tool to your ElevenLabs agent:

```json
{
  "name": "get-practitioner-services",
  "description": "Get available services/appointment types for a specific practitioner. Use this when you need to know what services a practitioner offers.",
  "type": "webhook",
  "url": "https://your-api-domain.com/get-practitioner-services",
  "method": "POST",
  "headers": {
    "X-API-Key": "your-api-key-here"
  },
  "parameters": [
    {
      "name": "practitioner",
      "type": "string",
      "description": "The practitioner's name",
      "required": true
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
    "timeout": 5000
  }
}
```

## Update your ElevenLabs Agent Prompt:

### Smart Service Handling

When booking appointments:

1. **If the caller doesn't specify a service type** (just says "appointment" or "booking"):
   - Call get-practitioner-services first
   - If serviceCount = 1, use the defaultService automatically
   - If serviceCount > 1, ask which service they want using the provided message

2. **If appointment-handler returns service_not_found**:
   - Call get-practitioner-services to get the correct service names
   - Tell the caller what's available using the message provided
   - Listen for their choice
   - Retry booking with the exact service name

3. **Example flow**:
   ```
   Caller: "I need to see Cameron"
   Agent: [Calls get-practitioner-services]
   Response: {serviceCount: 2, message: "Cameron offers Initial Assessment and Follow-up Consultation"}
   Agent: "Cameron offers Initial Assessment and Follow-up Consultation. Which would you like?"
   Caller: "The initial one"
   Agent: [Books with appointmentType: "Initial Assessment"]
   ```

4. **For single-service practitioners**:
   ```
   Caller: "Book me with Dr Smith"
   Agent: [Calls get-practitioner-services]
   Response: {serviceCount: 1, defaultService: "Standard Consultation"}
   Agent: [Automatically books with appointmentType: "Standard Consultation"]
   Agent: "I'm booking your Standard Consultation with Dr Smith..."
   ```