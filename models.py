# models.py - Pydantic V2 Updated Version
from pydantic import BaseModel, Field, field_validator, ConfigDict
from typing import List, Optional, Dict, Any, Literal
from datetime import datetime
from enum import Enum

# === Enums ===
class ActionType(str, Enum):
    BOOK = "book"
    CHECK = "check"
    MODIFY = "modify"
    CANCEL = "cancel"
    RESCHEDULE = "reschedule"

class BookingFor(str, Enum):
    SELF = "self"
    OTHER = "other"

# === Models ===
class TranscriptMessage(BaseModel):
    role: str
    message: str
    timestamp: Optional[datetime] = None

class BaseRequest(BaseModel):
    sessionId: str = Field(default_factory=lambda: f"session_{int(datetime.now().timestamp() * 1000)}")
    callerPhone: str = Field(..., description="Caller's phone number")
    dialedNumber: str = Field(..., description="The number that was dialed (clinic's number)")
    timestamp: datetime = Field(default_factory=datetime.now)

class BookingRequest(BaseModel):
    action: ActionType = ActionType.BOOK
    sessionId: str = Field(default_factory=lambda: f"session_{int(datetime.now().timestamp() * 1000)}")
    dialedNumber: str = Field(..., description="The number that was dialed (clinic's number)")
    timestamp: datetime = Field(default_factory=datetime.now)
    
    # Phone fields - handle both callerPhone and systemCallerID
    callerPhone: Optional[str] = Field(None, description="Caller's phone number")
    systemCallerID: Optional[str] = Field(None, description="System-provided caller ID")
    
    # Patient information
    patientName: Optional[str] = None
    patientPhone: Optional[str] = None
    appointmentType: Optional[str] = None
    practitioner: Optional[str] = None
    appointmentDate: Optional[str] = None
    appointmentTime: Optional[str] = None
    business_name: Optional[str] = None  # The business/location name
    business_id: Optional[str] = None    # Pre-resolved business ID from Cliniko
    location: Optional[str] = Field(None, description="Location name or reference")
    bookingFor: BookingFor = BookingFor.SELF
    transcript: List[TranscriptMessage] = []
    notes: Optional[str] = None
    appointmentId: Optional[str] = None
    
    # Reschedule-specific fields
    currentAppointmentDetails: Optional[str] = None
    newDate: Optional[str] = None
    newTime: Optional[str] = None
    newPractitioner: Optional[str] = None
    newAppointmentType: Optional[str] = None
    
    @field_validator('callerPhone', mode='before')
    @classmethod
    def set_caller_phone(cls, v, info):
        """If callerPhone is not provided, use systemCallerID"""
        if not v and 'systemCallerID' in info.data:
            return info.data['systemCallerID']
        return v
    
    @field_validator('patientPhone', mode='before')
    @classmethod
    def set_patient_phone(cls, v, info):
        """If patientPhone is not provided and booking for self, use callerPhone"""
        if not v and info.data.get('bookingFor', BookingFor.SELF) == BookingFor.SELF:
            return info.data.get('callerPhone') or info.data.get('systemCallerID')
        return v

class AvailabilityRequest(BaseModel):
    action: ActionType = ActionType.CHECK
    practitioner: str
    date: Optional[str] = "today"
    appointmentType: Optional[str] = None
    business_name: Optional[str] = None
    business_id: Optional[str] = None    # Pre-resolved business ID from Cliniko
    location: Optional[str] = Field(None, description="Location name or reference")
    sessionId: str = Field(default_factory=lambda: f"session_{int(datetime.now().timestamp() * 1000)}")
    dialedNumber: str
    callerPhone: Optional[str] = None
    systemCallerID: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.now)
    
    @field_validator('callerPhone', mode='before')
    @classmethod
    def set_caller_phone(cls, v, info):
        if not v and 'systemCallerID' in info.data:
            return info.data['systemCallerID']
        return v

class CancelRequest(BaseRequest):
    action: ActionType = ActionType.CANCEL
    appointmentId: Optional[str] = None
    appointmentDetails: Optional[str] = None
    reason: Optional[str] = None

class RescheduleRequest(BaseRequest):
    """Request model for rescheduling appointments"""
    action: ActionType = ActionType.RESCHEDULE
    appointmentId: Optional[str] = None
    currentAppointmentDetails: Optional[str] = None
    newDate: Optional[str] = None
    newTime: Optional[str] = None
    newPractitioner: Optional[str] = None
    newAppointmentType: Optional[str] = None
    notes: Optional[str] = None

class ClinicData(BaseModel):
    clinic_id: str
    clinic_name: str
    cliniko_api_key: str
    cliniko_shard: str
    contact_email: str
    businesses: List[Dict[str, Any]] = []
    timezone: str = Field(default="Australia/Sydney")

# === NEW: ElevenLabs-specific models with flexible parameter handling ===

class LocationResolverRequest(BaseModel):
    """Request model for location resolution"""
    locationQuery: str = Field(default="", description="The location reference to resolve")
    sessionId: str = Field(..., description="Session ID for tracking")
    dialedNumber: str = Field(..., description="The dialed clinic number")
    callerPhone: Optional[str] = Field(None, description="Caller's phone number")
    additionalContext: Optional[str] = Field(None, description="Additional context for resolution")

    model_config = ConfigDict(extra="forbid")

class LocationResolverResponse(BaseModel):
    """Response model for location resolution - simplified for ElevenLabs"""
    success: bool
    sessionId: str
    action_completed: bool = Field(..., description="Whether location was definitively resolved")
    needs_clarification: bool = Field(..., description="Whether agent should ask for clarification")
    message: str = Field(..., description="Voice-friendly message to read to caller")
    business_id: Optional[str] = Field(None, description="The resolved business ID from Cliniko")
    business_name: Optional[str] = Field(None, description="Human-readable business name")
    options: Optional[List[str]] = Field(None, description="Simple list of location names if ambiguous")
    confidence: float = Field(0.0, description="Confidence score 0-1")

class ConfirmLocationRequest(BaseModel):
    """Request model for confirming location selection"""
    userResponse: str = Field(..., alias="user_response", description="User's response to location options")
    options: List[str] = Field(..., description="The location options that were presented")
    sessionId: str = Field(..., alias="session_id", description="Session ID for tracking")
    dialedNumber: str = Field(..., alias="dialed_number", description="The dialed clinic number")
    selectedIndex: Optional[int] = Field(None, alias="selected_index", description="Pre-selected index if known")
    callerPhone: Optional[str] = Field(None, alias="caller_phone", description="Caller's phone number")
    systemCallerID: Optional[str] = Field(None, alias="system_caller_id", description="System-provided caller ID")
    
    model_config = ConfigDict(populate_by_name=True)
        
    @field_validator('callerPhone', mode='before')
    @classmethod
    def set_caller_phone(cls, v, info):
        if not v and 'systemCallerID' in info.data:
            return info.data['systemCallerID']
        return v

class ConfirmLocationResponse(BaseModel):
    """Response model for location confirmation"""
    success: bool
    sessionId: str
    location_confirmed: bool
    business_id: Optional[str] = None
    business_name: Optional[str] = None
    message: str
    options: Optional[List[str]] = None  # If still ambiguous

class AppointmentHandlerRequest(BaseModel):
    """Request model specifically for appointment-handler webhook from ElevenLabs"""
    sessionId: str
    dialedNumber: str
    callerPhone: Optional[str] = None
    systemCallerID: Optional[str] = None
    patientName: str
    patientPhone: Optional[str] = None
    practitioner: str
    appointmentType: str
    appointmentDate: str  # Format: YYYY-MM-DD
    appointmentTime: str  # Format: HH:MM
    business_id: str     # The resolved business ID from location-resolver
    location: Optional[str] = Field(None, description="Alternative field for business ID")
    notes: Optional[str] = None
    
    @field_validator('callerPhone', mode='before')
    @classmethod
    def set_caller_phone(cls, v, info):
        """If callerPhone is not provided, use systemCallerID"""
        if not v and 'systemCallerID' in info.data:
            return info.data['systemCallerID']
        return v
    
    @field_validator('patientPhone', mode='before')
    @classmethod
    def set_patient_phone(cls, v, info):
        """If patientPhone is not provided, use callerPhone"""
        if not v:
            return info.data.get('callerPhone') or info.data.get('systemCallerID')
        return v

# ============================================
# STANDARDIZED API RESPONSE MODELS
# For consistent voice agent responses
# ============================================

class BaseVoiceResponse(BaseModel):
    """Base response model that ALL API endpoints should use for consistency"""
    success: bool = Field(..., description="Whether request succeeded")
    sessionId: str = Field(..., description="Session tracking ID")
    message: str = Field(..., description="Human-readable message for voice output")
    error: Optional[str] = Field(None, description="Error code if success=false")
    
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "success": True,
                "sessionId": "session_123",
                "message": "Request processed successfully",
                "error": None
            }
        }
    )

# Consistent data structures used across endpoints
class LocationData(BaseModel):
    """Consistent location structure everywhere"""
    id: str = Field(..., description="Unique business ID from Cliniko")
    name: str = Field(..., description="Display name of the location")

class PractitionerData(BaseModel):
    """Consistent practitioner structure everywhere"""
    id: str = Field(..., description="Unique practitioner ID")
    name: str = Field(..., description="Full name")
    firstName: str = Field(..., description="First name only")
    servicesCount: Optional[int] = Field(0, description="Number of services offered")

class ServiceData(BaseModel):
    """Consistent service structure everywhere"""
    id: str = Field(..., description="Unique service ID")
    name: str = Field(..., description="Service name")
    duration: int = Field(..., description="Duration in minutes")

class TimeSlotData(BaseModel):
    """Consistent time slot structure everywhere"""
    date: str = Field(..., description="Date in YYYY-MM-DD format")
    time: str = Field(..., description="Time in HH:MM format (24-hour)")
    displayTime: str = Field(..., description="Human readable time (12-hour with AM/PM)")

# Updated LocationResolverResponse to extend BaseVoiceResponse
class LocationResolverResponse(BaseVoiceResponse):
    """Response for location resolution"""
    resolved: bool = Field(False, description="Whether location was definitively resolved")
    needsClarification: bool = Field(False, description="Whether agent needs to ask for clarification")
    location: Optional[LocationData] = Field(None, description="Resolved location (if resolved=true)")
    options: Optional[List[LocationData]] = Field(None, description="Available options (if needsClarification=true)")
    confidence: float = Field(0.0, ge=0.0, le=1.0, description="Confidence score of the match")
    # Backward compatibility fields (excluded from output)
    action_completed: Optional[bool] = Field(None, exclude=True)  # Old field name
    needs_clarification: Optional[bool] = Field(None, exclude=True)  # Old field name
    business_id: Optional[str] = Field(None, exclude=True)  # Old flat field
    business_name: Optional[str] = Field(None, exclude=True)  # Old flat field

    def model_post_init(self, __context):
        """Handle old field names"""
        # Map old fields to new ones
        if self.action_completed is not None:
            self.resolved = self.action_completed
        if self.needs_clarification is not None:
            self.needsClarification = self.needs_clarification
        # Create location object from flat fields
        if self.business_id and self.business_name and not self.location:
            self.location = LocationData(
                id=self.business_id,
                name=self.business_name
            )

# Practitioners endpoint response
class GetPractitionersResponse(BaseVoiceResponse):
    """Response for get-location-practitioners endpoint"""
    location: LocationData = Field(..., description="Location where practitioners work")
    practitioners: List[PractitionerData] = Field(..., description="List of available practitioners")

# Services endpoint response
class GetServicesResponse(BaseVoiceResponse):
    """Response for get-practitioner-services endpoint"""
    practitioner: PractitionerData = Field(..., description="Practitioner details")
    services: List[ServiceData] = Field(..., description="Available services")
    location: Optional[LocationData] = Field(None, description="Location if specified")

# Availability endpoint response
class AvailabilityResponse(BaseVoiceResponse):
    """Response for availability-checker endpoint"""
    practitioner: PractitionerData = Field(..., description="Practitioner details")
    date: str = Field(..., description="Date checked in YYYY-MM-DD format")
    slots: List[TimeSlotData] = Field(..., description="Available time slots")
    location: Optional[LocationData] = Field(None, description="Location if specified")

# Booking endpoint response
class BookingResponse(BaseVoiceResponse):
    """Response for appointment-handler endpoint when booking"""
    bookingId: str = Field(..., description="Unique booking ID")
    confirmationNumber: str = Field(..., description="Human-friendly confirmation number")
    practitioner: PractitionerData
    service: ServiceData
    location: LocationData
    timeSlot: TimeSlotData
    patientName: str = Field(..., description="Patient's name")

# Standardized error response
class ErrorResponse(BaseVoiceResponse):
    success: Literal[False] = Field(default=False)
    error: str = Field(..., description="The error message")
    needsClarification: Literal[False] = Field(default=False, description="Always false for errors")

def create_error_response(error_code: str, message: str, session_id: str) -> Dict[str, Any]:
    """Create a consistent error response"""
    return {
        "success": False,
        "sessionId": session_id,
        "message": message,
        "error": error_code,
        "resolved": False,
        "needsClarification": False
    }

class GetAvailablePractitionersResponse(BaseVoiceResponse):
    location: Optional[LocationData] = None
    practitioners: List[PractitionerData]
    date: str  # The date checked

class NextAvailableResponse(BaseVoiceResponse):
    found: bool
    slot: Optional[TimeSlotData] = None
    practitioner: Optional[PractitionerData] = None
    service: Optional[ServiceData] = None
    location: Optional[LocationData] = None

class CancellationResponse(BaseVoiceResponse):
    cancelled: bool
    appointmentId: str
    cancellationTime: str  # When it was cancelled

class PractitionerInfoResponse(BaseVoiceResponse):
    practitioner: PractitionerData
    services: List[ServiceData]
    locations: List[LocationData]