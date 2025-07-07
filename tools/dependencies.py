# tools/dependencies.py
"""Shared dependencies for all tools"""

from fastapi import Header, HTTPException
import os
import logging
import asyncpg
from typing import Dict, Any
from functools import lru_cache
from .shared_dependencies import get_db_pool, get_cache_manager

# Settings


class Settings:
    """Application settings from environment variables"""


    def __init__(self):
        self.api_key = os.environ.get("X_API_KEY", "development-key")
        self.environment = os.environ.get("ENVIRONMENT", "development")
        self.default_timezone = os.environ.get("DEFAULT_TIMEZONE", "Australia/Sydney")

@lru_cache()


def get_settings():
    return Settings()

# API Key verification
async def verify_api_key(x_api_key: str = None) -> bool:
    """Verify API key for authentication"""
    settings = get_settings()
    
    if settings.environment == "development" and not x_api_key:
        return True
        
    if not x_api_key:
        raise HTTPException(status_code=401, detail="API key required")
        
    if x_api_key != settings.api_key:
        raise HTTPException(status_code=401, detail="Invalid API key")
        
    return True

# Database and cache access
async def get_db():
    """Get database pool"""
    db_pool = get_db_pool()
    if not db_pool:
        raise RuntimeError("Database pool not initialized")
    return db_pool

async def get_cache():
    """Get cache manager"""
    cache_manager = get_cache_manager()
    if not cache_manager:
        raise RuntimeError("Cache manager not initialized")
    return cache_manager
