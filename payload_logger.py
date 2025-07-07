# payload_logger.py
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional
from zoneinfo import ZoneInfo


class PayloadLogger:


    def __init__(self, log_dir: str = "elevenlabs_payloads"):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(exist_ok=True)


    def log_payload(self, endpoint: str, payload: Dict[str, Any],
                    response: Optional[Dict[str, Any]] = None,
                    headers: Optional[Dict[str, str]] = None) -> str:
        """Log a payload with timestamp and unique ID"""
        timestamp = datetime.now()
        date_str = timestamp.strftime("%Y%m%d")
        time_str = timestamp.strftime("%H%M%S")

        # Create daily subdirectory
        daily_dir = self.log_dir / date_str
        daily_dir.mkdir(exist_ok=True)

        # Generate filename
        session_id = payload.get("sessionId", "unknown")
        action = payload.get("action", endpoint.replace("/", "_"))
        filename = f"{time_str}_{action}_{session_id}.json"
        filepath = daily_dir / filename

        # Prepare log data
        log_data = {
            "timestamp": timestamp.isoformat(),
            "endpoint": endpoint,
            "headers": headers or {},
            "payload": payload,
            "response": response,
            "metadata": {
                "practitioner": payload.get("practitioner"),
                "patient_name": payload.get("patientName"),
                "appointment_type": payload.get("appointmentType"),
                "date": payload.get("appointmentDate") or payload.get("date"),
                "time": payload.get("appointmentTime"),
                "caller_phone": payload.get("callerPhone"),
                "dialed_number": payload.get("dialedNumber")
            }
        }

        # Write to file
        with open(filepath, 'w') as f:
            json.dump(log_data, f, indent=2, default=str)

        return str(filepath)


    def list_payloads(self, date: Optional[str] = None,
                      action: Optional[str] = None) -> list[Path]:  # Changed to lowercase list
        """List captured payloads with optional filters"""
        if date:
            pattern = f"{date}/*.json"
        else:
            pattern = "*/*.json"

        files = list(self.log_dir.glob(pattern))

        if action:
            files = [f for f in files if action in f.name]

        return sorted(files, reverse=True)


    def load_payload(self, filepath: str) -> Dict[str, Any]:
        """Load a captured payload"""
        with open(filepath, 'r') as f:
            return json.load(f)


    def get_latest(self, endpoint: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Get the most recent payload for an endpoint"""
        files = self.list_payloads()

        for file in files:
            data = self.load_payload(file)
            if not endpoint or data.get("endpoint") == endpoint:
                return data

        return None


def get_clinic_timezone_from_settings() -> ZoneInfo:
    """Get timezone from settings"""
    from tools.shared import get_settings
    return ZoneInfo(get_settings().default_timezone)

# Global logger instance
payload_logger = PayloadLogger()