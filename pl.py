from payload_logger import payload_logger

# Test the logger
test_payload = {
    "sessionId": "test123",
    "action": "book",
    "practitioner": "Test Doctor",
    "appointmentType": "Test Service"
}

filepath = payload_logger.log_payload("/test-endpoint", test_payload)
print(f"Test payload saved to: {filepath}")
print(f"Folder exists: {payload_logger.log_dir.exists()}")