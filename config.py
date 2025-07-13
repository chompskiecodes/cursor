# config.py - Pydantic V2 Updated Version
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, field_validator
from typing import Optional, List
import os
from dotenv import load_dotenv

# Load .env file if it exists (for local development)
load_dotenv()

class Settings(BaseSettings):
    """Application settings with validation"""
    
    # Database
    database_url: str = Field(
        default="postgresql://user:pass@localhost/voice_booking",
        alias="DATABASE_URL"
    )
    db_pool_size_min: int = Field(default=10, alias="DB_POOL_SIZE_MIN")
    db_pool_size_max: int = Field(default=25, alias="DB_POOL_SIZE_MAX")
    
    # Supabase
    supabase_url: str = Field(
        default="https://xdnjnrrnehximkxteidq.supabase.co",
        alias="SUPABASE_URL"
    )
    supabase_key: Optional[str] = Field(default=None, alias="SUPABASE_KEY")
    
    # API Security
    api_key: str = Field(default="development-key", alias="API_KEY")
    api_key_header: str = Field(default="X-API-Key", alias="API_KEY_HEADER")
    
    # Application
    environment: str = Field(default="development", alias="ENVIRONMENT")
    debug: bool = Field(default=False, alias="DEBUG")
    app_name: str = Field(default="Voice Booking System", alias="APP_NAME")
    app_version: str = Field(default="2.0.0", alias="APP_VERSION")
    
    # CORS
    cors_origins: List[str] = Field(
        default=["*"],
        alias="CORS_ORIGINS"
    )
    
    # Logging
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    log_format: str = Field(
        default="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        alias="LOG_FORMAT"
    )
    
    # Matching thresholds
    practitioner_match_threshold: float = Field(
        default=0.6,
        alias="PRACTITIONER_MATCH_THRESHOLD"
    )
    service_match_threshold: float = Field(
        default=0.5,
        alias="SERVICE_MATCH_THRESHOLD"
    )
    
    # Timezone
    default_timezone: str = Field(
        default="Australia/Sydney",
        alias="DEFAULT_TIMEZONE"
    )
    
    @field_validator('environment')
    @classmethod
    def validate_environment(cls, v):
        allowed = ["development", "staging", "production"]
        if v not in allowed:
            raise ValueError(f"Environment must be one of {allowed}")
        return v
    
    @field_validator('database_url')
    @classmethod
    def validate_database_url(cls, v):
        if not v.startswith(("postgresql://", "postgres://")):
            raise ValueError("Database URL must be a PostgreSQL connection string")
        return v
    
    @field_validator('cors_origins', mode='before')
    @classmethod
    def parse_cors_origins(cls, v):
        if isinstance(v, str):
            # If it's a string, split by comma
            return [origin.strip() for origin in v.split(',')]
        return v
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        # This allows the Settings class to read from environment variables
        # even if they don't have the exact field name
        populate_by_name=True
    )

# Singleton instance
settings = Settings()