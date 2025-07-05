# Complete ElevenLabs Tool Creation Guide

## Overview
This guide contains all lessons learned from creating ElevenLabs webhook tools, including all nuances, requirements, and gotchas discovered through trial and error.

## API Endpoint & Authentication

### Endpoint
```
POST https://api.elevenlabs.io/v1/convai/tools
```

### Required Headers
```json
{
  "xi-api-key": "your-elevenlabs-api-key",
  "Content-Type": "application/json"
}
```

## Tool Configuration Structure

### Complete JSON Structure
```json
{
  "tool_config": {
    "name": "tool_name",
    "description": "Tool description for the AI agent",
    "response_timeout_secs": 20,
    "type": "webhook",
    "api_schema": {
      "url": "https://your-webhook-url/endpoint",
      "method": "POST",
      "path_params_schema": {},
      "query_params_schema": null,
      "request_body_schema": {
        "type": "object",
        "required": ["field1", "field2"],
        "description": "Description of the request body",
        "properties": {
          // Property definitions (see below)
        }
      },
      "request_headers": {
        "X-API-Key": "your-webhook-api-key",
        "Content-Type": "application/json"
      },
      "auth_connection": null
    },
    "dynamic_variables": {
      "dynamic_variable_placeholders": {}
    }
  }
}
```

## Critical Requirements & Lessons Learned

### 1. Tool Type
- **MUST** include `"type": "webhook"` at the `tool_config` level
- This is NOT part of the standard JSON Schema - it's ElevenLabs specific

### 2. Query Parameters Schema
- If you don't need query parameters, set to `null`:
  ```json
  "query_params_schema": null
  ```
- If you include it as an object, `properties` CANNOT be empty:
  ```json
  // ❌ WRONG - This will fail
  "query_params_schema": {
    "properties": {},  // Empty properties causes error
    "required": []
  }
  
  // ✅ CORRECT - Either null or with at least one property
  "query_params_schema": null
  // OR
  "query_params_schema": {
    "properties": {
      "dummy": {
        "type": "string",
        "description": "Placeholder"
      }
    },
    "required": []
  }
  ```

### 3. Path Parameters Schema
- Can be an empty object if not needed:
  ```json
  "path_params_schema": {}
  ```
- Do NOT use empty array `[]` - must be object

### 4. Property Definitions

#### String Properties
For string, number, boolean properties, ElevenLabs expects these fields:
```json
"propertyName": {
  "type": "string",
  "description": "Description for the AI agent",
  "dynamic_variable": "",    // Required but can be empty
  "constant_value": ""       // Required but can be empty
}
```

#### Array Properties
Arrays have different requirements:
```json
"arrayProperty": {
  "type": "array",
  "description": "Array description",
  // NO dynamic_variable or constant_value for arrays!
  "items": {
    "type": "string",
    "description": "Description of array items"  // REQUIRED!
  }
}
```

**Critical**: Array items MUST have at least one of:
- `description`
- `dynamic_variable` 
- `constant_value`

### 5. Request Headers
- Must be a simple object, NOT an array:
```json
"request_headers": {
  "Header-Name": "value",
  "Another-Header": "value"
}
```

### 6. Additional Required Fields
- `response_timeout_secs`: Number (e.g., 10, 20)
- `auth_connection`: Set to `null` if not using connection-based auth
- `dynamic_variables`: Must include even if empty:
  ```json
  "dynamic_variables": {
    "dynamic_variable_placeholders": {}
  }
  ```

### 7. Common Errors and Solutions

| Error | Cause | Solution |
|-------|-------|----------|
| "Unable to extract tag using discriminator 'type'" | Missing `type` field | Add `"type": "webhook"` to `tool_config` |
| "Dictionary should have at least 1 item" | Empty `properties` in query_params_schema | Set `query_params_schema` to `null` or add a property |
| "Input should be a valid dictionary" | Using array instead of object | Use `{}` not `[]` for schema objects |
| "Extra inputs are not permitted" | Wrong fields for property type | Remove `dynamic_variable`/`constant_value` from arrays |
| "Must set one of: description, dynamic_variable, or constant_value" | Missing required field in array items | Add `description` to array `items` |

## Complete Working PowerShell Script Template

```powershell
# ElevenLabs Tool Creation Script

$apiKey = "your-elevenlabs-api-key"
$apiUrl = "https://api.elevenlabs.io/v1/convai/tools"
$webhookBaseUrl = "https://your-ngrok-url.ngrok-free.app"
$webhookApiKey = "your-webhook-api-key"

$toolConfig = @{
    tool_config = @{
        name = "your_tool_name"
        description = "What this tool does"
        response_timeout_secs = 20
        type = "webhook"  # CRITICAL - Must be here
        api_schema = @{
            url = "$webhookBaseUrl/your-endpoint"
            method = "POST"
            path_params_schema = @{}
            query_params_schema = $null  # Use null if no query params
            request_body_schema = @{
                type = "object"
                required = @("requiredField1", "requiredField2")
                description = "Request body description"
                properties = @{
                    # String property example
                    stringField = @{
                        type = "string"
                        description = "Field description"
                        dynamic_variable = ""
                        constant_value = ""
                    }
                    # Array property example
                    arrayField = @{
                        type = "array"
                        description = "Array description"
                        items = @{
                            type = "string"
                            description = "Item description"  # Required!
                        }
                        # NO dynamic_variable or constant_value for arrays
                    }
                }
            }
            request_headers = @{
                "X-API-Key" = $webhookApiKey
                "Content-Type" = "application/json"
            }
            auth_connection = $null
        }
        dynamic_variables = @{
            dynamic_variable_placeholders = @{}
        }
    }
}

# Convert and send
$jsonBody = $toolConfig | ConvertTo-Json -Depth 10
$headers = @{
    "xi-api-key" = $apiKey
    "Content-Type" = "application/json"
}

$response = Invoke-WebRequest -Uri $apiUrl -Method Post -Headers $headers -Body $jsonBody -UseBasicParsing
```

## Response Structure

Successful response includes:
```json
{
  "id": "generated-tool-id",
  "tool_config": { /* your tool config */ },
  "access_info": {
    "is_creator": true,
    "creator_name": "your-name",
    "creator_email": "your-email",
    "role": "admin"
  }
}
```

## Best Practices

1. **Always validate JSON** before sending - use `ConvertTo-Json -Depth 10` to see full structure
2. **Save tool IDs** - You'll need them for updates/deletions
3. **Test webhooks separately** - Ensure your webhook endpoint works before creating the tool
4. **Use descriptive names** - The AI agent uses these to decide when to call tools
5. **Be specific in descriptions** - Help the AI understand exactly when to use each tool

## Debugging Tips

1. **Check exact error paths** - ElevenLabs errors show the exact location (e.g., `body.tool_config.webhook.api_schema...`)
2. **Compare with working tools** - Fetch existing tools to see working structures
3. **Save all responses** - Both success and error responses for debugging
4. **Watch for type mismatches** - PowerShell `@()` creates arrays, `@{}` creates objects

## Field Reference

### Required Fields by Type

**All Properties**:
- `type`: The data type (string, number, boolean, array, object)
- `description`: Human-readable description

**String/Number/Boolean Properties Only**:
- `dynamic_variable`: Usually empty string `""`
- `constant_value`: Usually empty string `""`

**Array Properties Only**:
- `items`: Object defining the array element type
- `items.type`: Type of array elements
- `items.description`: Description of array elements (REQUIRED)

**Object Properties**:
- `properties`: Nested property definitions
- `required`: Array of required property names

This guide represents all discovered requirements and nuances for successfully creating ElevenLabs webhook tools.